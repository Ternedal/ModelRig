from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
import time
import uuid
from copy import deepcopy
from pathlib import Path
from typing import Any, Iterable

from .core import AgentRun, AgentRunStore, AgentStep
from .replanner import ReadSuffixReplanner, ReplanError, ReplanReceipt


class ReplanJournalError(RuntimeError):
    pass


def plan_digest(run: AgentRun) -> str:
    """Digest the execution-relevant run shape, excluding timestamps.

    The digest intentionally includes step state, results, confirmation fields,
    route and request bindings. A concurrent execution/confirmation therefore
    cannot be mistaken for either side of a pending replan transaction.
    """

    payload = json.loads(run.to_json())
    canonical = {
        "run_id": payload["id"],
        "state": payload["state"],
        "current_step": payload["current_step"],
        "request": payload["request"],
        "route": payload["route"],
        "steps": payload["steps"],
        "proactive": payload["proactive"],
        "allow_private_cloud": payload["allow_private_cloud"],
    }
    raw = json.dumps(canonical, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class ReplanJournal:
    """Write-ahead journal for plan revisions.

    AgentRunStore and this journal use separate SQLite connections. Atomicity is
    achieved by a recoverable protocol instead of pretending the two commits are
    one transaction:

    1. persist PREPARED with before/after digests,
    2. save the revised AgentRun,
    3. mark COMMITTED.

    Recovery compares the persisted run digest with both sides. It commits,
    aborts or records a conflict; it never replays a revision blindly.
    """

    def __init__(self, path: str):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS agent_replans ("
            "id TEXT PRIMARY KEY, run_id TEXT NOT NULL, revision INTEGER NOT NULL, "
            "replan_number INTEGER NOT NULL, state TEXT NOT NULL, "
            "before_digest TEXT NOT NULL, after_digest TEXT NOT NULL, "
            "receipt TEXT NOT NULL, created_at REAL NOT NULL, updated_at REAL NOT NULL, "
            "error TEXT, UNIQUE(run_id, revision))"
        )
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_agent_replans_run "
            "ON agent_replans(run_id, revision)"
        )
        self._conn.commit()

    def prepare(
        self,
        run_id: str,
        receipt: ReplanReceipt,
        *,
        before_digest: str,
        after_digest: str,
    ) -> str:
        tx_id = str(uuid.uuid4())
        now = time.time()
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                open_row = self._conn.execute(
                    "SELECT state FROM agent_replans "
                    "WHERE run_id=? AND state IN ('prepared','conflict') LIMIT 1",
                    (run_id,),
                ).fetchone()
                if open_row:
                    raise ReplanJournalError(
                        f"run has unresolved replan transaction ({open_row[0]})"
                    )
                self._conn.execute(
                    "INSERT INTO agent_replans("
                    "id,run_id,revision,replan_number,state,before_digest,after_digest,"
                    "receipt,created_at,updated_at,error) VALUES(?,?,?,?,?,?,?,?,?,?,NULL)",
                    (
                        tx_id,
                        run_id,
                        receipt.to_revision,
                        receipt.replan_number,
                        "prepared",
                        before_digest,
                        after_digest,
                        json.dumps(receipt.to_dict(), ensure_ascii=False, sort_keys=True),
                        now,
                        now,
                    ),
                )
                self._conn.commit()
            except Exception:
                self._conn.rollback()
                raise
        return tx_id

    def transition(self, tx_id: str, state: str, error: str | None = None) -> None:
        if state not in {"committed", "aborted", "conflict"}:
            raise ReplanJournalError(f"invalid terminal journal state: {state}")
        with self._lock:
            changed = self._conn.execute(
                "UPDATE agent_replans SET state=?,updated_at=?,error=? "
                "WHERE id=? AND state='prepared'",
                (state, time.time(), error, tx_id),
            ).rowcount
            self._conn.commit()
        if changed != 1:
            raise ReplanJournalError("replan transaction is not prepared")

    def prepared(self, run_id: str) -> list[dict[str, Any]]:
        return self._rows(run_id, states=("prepared",))

    def conflicts(self, run_id: str) -> list[dict[str, Any]]:
        return self._rows(run_id, states=("conflict",))

    def history(self, run_id: str) -> list[dict[str, Any]]:
        return self._rows(run_id, states=None)

    def revision_state(self, run_id: str) -> tuple[int, int]:
        with self._lock:
            row = self._conn.execute(
                "SELECT COALESCE(MAX(revision),0), COUNT(*) FROM agent_replans "
                "WHERE run_id=? AND state='committed'",
                (run_id,),
            ).fetchone()
        return int(row[0]), int(row[1])

    def _rows(
        self,
        run_id: str,
        *,
        states: tuple[str, ...] | None,
    ) -> list[dict[str, Any]]:
        sql = (
            "SELECT id,revision,replan_number,state,before_digest,after_digest,"
            "receipt,created_at,updated_at,error FROM agent_replans WHERE run_id=?"
        )
        params: list[Any] = [run_id]
        if states:
            sql += " AND state IN (" + ",".join("?" for _ in states) + ")"
            params.extend(states)
        sql += " ORDER BY revision ASC, created_at ASC"
        with self._lock:
            rows = self._conn.execute(sql, params).fetchall()
        result = []
        for row in rows:
            result.append(
                {
                    "id": row[0],
                    "revision": row[1],
                    "replan_number": row[2],
                    "state": row[3],
                    "before_digest": row[4],
                    "after_digest": row[5],
                    "receipt": json.loads(row[6]),
                    "created_at": row[7],
                    "updated_at": row[8],
                    "error": row[9],
                }
            )
        return result


class PersistentReadReplanner:
    """Apply read-only replans with optimistic concurrency and recovery."""

    def __init__(
        self,
        run_store: AgentRunStore,
        journal: ReplanJournal,
        policy: ReadSuffixReplanner | None = None,
    ):
        self.run_store = run_store
        self.journal = journal
        self.policy = policy or ReadSuffixReplanner()
        self._lock = threading.RLock()

    def recover(self, run_id: str) -> list[dict[str, Any]]:
        outcomes: list[dict[str, Any]] = []
        with self._lock:
            run = self.run_store.load(run_id)
            if run is None:
                raise KeyError(run_id)
            current_digest = plan_digest(run)
            for tx in self.journal.prepared(run_id):
                if current_digest == tx["after_digest"]:
                    self.journal.transition(tx["id"], "committed")
                    outcome = "committed"
                    self.run_store.event(
                        run_id,
                        "replan_recovered_committed",
                        {"transaction_id": tx["id"], "revision": tx["revision"]},
                    )
                elif current_digest == tx["before_digest"]:
                    self.journal.transition(tx["id"], "aborted")
                    outcome = "aborted"
                    self.run_store.event(
                        run_id,
                        "replan_recovered_aborted",
                        {"transaction_id": tx["id"], "revision": tx["revision"]},
                    )
                else:
                    self.journal.transition(
                        tx["id"],
                        "conflict",
                        "persisted run matches neither side of prepared replan",
                    )
                    outcome = "conflict"
                    self.run_store.event(
                        run_id,
                        "replan_recovery_conflict",
                        {"transaction_id": tx["id"], "revision": tx["revision"]},
                    )
                outcomes.append({"transaction_id": tx["id"], "outcome": outcome})
        return outcomes

    def apply(
        self,
        run_id: str,
        replacement_steps: Iterable[AgentStep],
        *,
        reason: str,
    ) -> tuple[AgentRun, ReplanReceipt]:
        with self._lock:
            self.recover(run_id)
            if self.journal.conflicts(run_id):
                raise ReplanJournalError("run has an unresolved replan conflict")

            current = self.run_store.load(run_id)
            if current is None:
                raise KeyError(run_id)
            revision, replan_count = self.journal.revision_state(run_id)
            before_digest = plan_digest(current)
            revised = deepcopy(current)
            receipt = self.policy.apply(
                revised,
                replacement_steps,
                reason=reason,
                revision=revision,
                replan_count=replan_count,
            )
            after_digest = plan_digest(revised)
            tx_id = self.journal.prepare(
                run_id,
                receipt,
                before_digest=before_digest,
                after_digest=after_digest,
            )

            # Optimistic concurrency check immediately before the authoritative
            # run save. The worker is single-process today; a future multi-worker
            # deployment must replace this with a CAS update in AgentRunStore.
            latest = self.run_store.load(run_id)
            if latest is None:
                self.journal.transition(tx_id, "aborted", "run disappeared before save")
                raise KeyError(run_id)
            if plan_digest(latest) != before_digest:
                self.journal.transition(tx_id, "conflict", "run changed before replan save")
                raise ReplanJournalError("run changed concurrently before replan save")

            self.run_store.save(revised)
            saved = self.run_store.load(run_id)
            if saved is None or plan_digest(saved) != after_digest:
                # Leave PREPARED for deterministic recovery. Do not retry the
                # mutation or invent a terminal state here.
                raise ReplanJournalError("replan save could not be verified; recovery required")

            self.journal.transition(tx_id, "committed")
            self.run_store.event(
                run_id,
                "replan_committed",
                {
                    "transaction_id": tx_id,
                    "revision": receipt.to_revision,
                    "replan_number": receipt.replan_number,
                    "start": receipt.start,
                    "old_end": receipt.old_end,
                    "new_end": receipt.new_end,
                    "removed_step_ids": receipt.removed_step_ids,
                    "added_step_ids": receipt.added_step_ids,
                    "reason": receipt.reason,
                },
            )
            return saved, receipt
