"""Scheduled tasks: cadence, approval policy, and persistent schedule truth.

Nothing ticks merely because this module exists. ``KALIV_SCHEDULER`` remains
OFF by default, and the store deliberately has no model-visible route. A later
runner may claim due schedules, but only Anders-created records can exist.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass

from . import paths as _paths

SCHEDULES_DB_PATH = _paths.resolve(
    "./modelrig-schedules.db", env="KALIV_SCHEDULES_DB"
)

# "every:900" -> every 900 seconds. "daily:03:00" -> at 03:00 local time.
_EVERY = re.compile(r"^every:(\d+)$")
_DAILY = re.compile(r"^daily:([01]\d|2[0-3]):([0-5]\d)$")
MIN_INTERVAL_S = 60
_RESULT_LIMIT = 4000


class ScheduleError(ValueError):
    """A schedule that cannot be honoured. Never silently downgraded."""


def enabled() -> bool:
    """Dormant by default. Nothing ticks until Anders turns it on."""
    return os.getenv("KALIV_SCHEDULER", "").strip().lower() in ("1", "true", "on")


def fingerprint(tool: str, args: dict) -> str:
    """What exactly was approved. Argument order cannot change the identity."""
    blob = json.dumps(
        {"tool": tool, "args": args}, sort_keys=True, ensure_ascii=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(blob.encode()).hexdigest()[:32]


@dataclass(frozen=True)
class Cadence:
    kind: str          # "every" | "daily"
    seconds: int = 0   # for "every"
    hour: int = 0      # for "daily"
    minute: int = 0


def parse_cadence(spec: str) -> Cadence:
    m = _EVERY.match(spec or "")
    if m:
        secs = int(m.group(1))
        if secs < MIN_INTERVAL_S:
            raise ScheduleError(f"interval {secs}s er under minimum {MIN_INTERVAL_S}s")
        return Cadence("every", seconds=secs)
    m = _DAILY.match(spec or "")
    if m:
        return Cadence("daily", hour=int(m.group(1)), minute=int(m.group(2)))
    raise ScheduleError(
        f"ukendt kadence {spec!r} — brug 'every:<sekunder>' eller 'daily:HH:MM'"
    )


def next_run(cadence: Cadence, after: float) -> float:
    """The next moment this should fire, strictly after ``after``."""
    if cadence.kind == "every":
        return after + cadence.seconds
    if cadence.kind != "daily":
        raise ScheduleError(f"ukendt cadence-kind {cadence.kind!r}")
    lt = time.localtime(after)
    candidate = time.mktime((
        lt.tm_year, lt.tm_mon, lt.tm_mday,
        cadence.hour, cadence.minute, 0, 0, 0, -1,
    ))
    if candidate <= after:
        candidate = time.mktime((
            lt.tm_year, lt.tm_mon, lt.tm_mday + 1,
            cadence.hour, cadence.minute, 0, 0, 0, -1,
        ))
    return candidate


def catch_up(cadence: Cadence, due_at: float, now: float) -> tuple[int, float]:
    """Return ``(missed, next_due)``; missed runs are reported, never replayed.

    Intervals use arithmetic rather than one loop per missed minute. A rig that
    was offline for a year must not spend startup replaying half a million
    timestamps merely to decide that it will execute once now.
    """
    if now < due_at:
        return 0, due_at
    if cadence.kind == "every":
        occurrences = int((now - due_at) // cadence.seconds) + 1
        return max(0, occurrences - 1), due_at + occurrences * cadence.seconds
    missed = 0
    due = due_at
    while due <= now:
        due = next_run(cadence, due)
        missed += 1
    return max(0, missed - 1), due


def refusal(tool_risk: str, approved_fingerprint: str | None,
            current_fingerprint: str) -> str | None:
    """Why a scheduled action must not run, or ``None`` when it may."""
    if tool_risk == "desktop":
        return (
            "skrivebordshandlinger kan ikke planlægges: et klik kl. 03:00 lander "
            "i det vindue der tilfældigvis er der, og screenshot-bindingen kan "
            "ikke redde det — skærmen det blev planlagt mod findes ikke længere"
        )
    if tool_risk == "read":
        return None
    if tool_risk != "write":
        return f"ukendt tool-risk {tool_risk!r}; planen er afvist fail-closed"
    if not approved_fingerprint:
        return (
            "planlagte skrivninger kræver at du godkendte dem da du oprettede "
            "planen — der er ingen at spørge kl. 03:00"
        )
    if approved_fingerprint != current_fingerprint:
        return (
            "argumenterne er ændret siden du godkendte planen; godkendelsen "
            "gjaldt den handling, ikke denne"
        )
    return None


class ScheduleStore:
    """Persistent, local-only schedule records with atomic due claiming.

    Claiming advances ``next_due`` in the same SQLite transaction that returns
    the record. Two worker processes therefore cannot both fire the same due
    occurrence. The claim does not execute a tool; that remains a separate,
    gated runner concern.
    """

    def __init__(self, path: str = SCHEDULES_DB_PATH):
        self.path = path
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(path, check_same_thread=False)
        with self._lock:
            self._conn.execute("PRAGMA foreign_keys=ON")
            self._conn.execute(
                """CREATE TABLE IF NOT EXISTS schedules (
                       id TEXT PRIMARY KEY,
                       tool TEXT NOT NULL,
                       args_json TEXT NOT NULL,
                       cadence TEXT NOT NULL,
                       risk TEXT NOT NULL,
                       approved_fingerprint TEXT,
                       enabled INTEGER NOT NULL DEFAULT 1,
                       next_due REAL NOT NULL,
                       last_due REAL,
                       last_result TEXT NOT NULL DEFAULT '',
                       missed_runs INTEGER NOT NULL DEFAULT 0,
                       created REAL NOT NULL,
                       updated REAL NOT NULL)"""
            )
            self._conn.commit()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def create(self, *, tool: str, args: dict, cadence: str, risk: str,
               approved_fingerprint: str | None = None,
               now: float | None = None) -> str:
        """Create an Anders-approved schedule; refuse unsafe records up front."""
        if not isinstance(tool, str) or not tool.strip():
            raise ScheduleError("tool mangler")
        if not isinstance(args, dict):
            raise ScheduleError("args skal være et objekt")
        parsed = parse_cadence(cadence)
        current = fingerprint(tool, args)
        why = refusal(risk, approved_fingerprint, current)
        if why:
            raise ScheduleError(why)
        schedule_id = uuid.uuid4().hex[:12]
        created = time.time() if now is None else now
        due = next_run(parsed, created)
        args_json = json.dumps(
            args, sort_keys=True, ensure_ascii=False, separators=(",", ":")
        )
        with self._lock:
            self._conn.execute(
                "INSERT INTO schedules "
                "(id, tool, args_json, cadence, risk, approved_fingerprint, "
                "enabled, next_due, created, updated) "
                "VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?, ?)",
                (schedule_id, tool, args_json, cadence, risk,
                 approved_fingerprint, due, created, created),
            )
            self._conn.commit()
        return schedule_id

    def get(self, schedule_id: str) -> dict | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT id, tool, args_json, cadence, risk, approved_fingerprint, "
                "enabled, next_due, last_due, last_result, missed_runs, created, updated "
                "FROM schedules WHERE id=?", (schedule_id,),
            ).fetchone()
        return self._to_dict(row) if row else None

    def list(self, limit: int = 100) -> list[dict]:
        n = max(1, min(int(limit), 500))
        with self._lock:
            rows = self._conn.execute(
                "SELECT id, tool, args_json, cadence, risk, approved_fingerprint, "
                "enabled, next_due, last_due, last_result, missed_runs, created, updated "
                "FROM schedules ORDER BY created DESC LIMIT ?", (n,),
            ).fetchall()
        return [self._to_dict(row) for row in rows]

    def set_enabled(self, schedule_id: str, value: bool,
                    now: float | None = None) -> bool:
        """Enable from a fresh future due time; disabling never deletes history."""
        changed_at = time.time() if now is None else now
        with self._lock:
            row = self._conn.execute(
                "SELECT cadence FROM schedules WHERE id=?", (schedule_id,),
            ).fetchone()
            if not row:
                return False
            if value:
                due = next_run(parse_cadence(row[0]), changed_at)
                cur = self._conn.execute(
                    "UPDATE schedules SET enabled=1, next_due=?, updated=? WHERE id=?",
                    (due, changed_at, schedule_id),
                )
            else:
                cur = self._conn.execute(
                    "UPDATE schedules SET enabled=0, updated=? WHERE id=?",
                    (changed_at, schedule_id),
                )
            self._conn.commit()
            return cur.rowcount > 0

    def delete(self, schedule_id: str) -> bool:
        with self._lock:
            cur = self._conn.execute("DELETE FROM schedules WHERE id=?", (schedule_id,))
            self._conn.commit()
            return cur.rowcount > 0

    def claim_due(self, now: float | None = None, limit: int = 20) -> list[dict]:
        """Atomically claim due occurrences and advance them into the future.

        This is intentionally independent of :func:`enabled`: a runner checks
        the global feature flag before calling. Keeping the store deterministic
        makes it testable without changing process environment mid-transaction.
        """
        claimed_at = time.time() if now is None else now
        n = max(1, min(int(limit), 100))
        claimed: list[dict] = []
        with self._lock:
            try:
                self._conn.execute("BEGIN IMMEDIATE")
                rows = self._conn.execute(
                    "SELECT id, tool, args_json, cadence, risk, approved_fingerprint, "
                    "enabled, next_due, last_due, last_result, missed_runs, created, updated "
                    "FROM schedules WHERE enabled=1 AND next_due<=? "
                    "ORDER BY next_due, created LIMIT ?",
                    (claimed_at, n),
                ).fetchall()
                for row in rows:
                    item = self._to_dict(row)
                    due_at = item["next_due"]
                    try:
                        cadence = parse_cadence(item["cadence"])
                        missed, next_due = catch_up(cadence, due_at, claimed_at)
                    except ScheduleError as exc:
                        # On-disk corruption or a manual edit must stop the task,
                        # not turn into guessed cadence or a tight retry loop.
                        self._conn.execute(
                            "UPDATE schedules SET enabled=0, last_result=?, updated=? "
                            "WHERE id=?",
                            (f"disabled: {exc}"[:_RESULT_LIMIT], claimed_at, item["id"]),
                        )
                        continue
                    self._conn.execute(
                        "UPDATE schedules SET next_due=?, last_due=?, "
                        "missed_runs=missed_runs+?, updated=? WHERE id=?",
                        (next_due, due_at, missed, claimed_at, item["id"]),
                    )
                    item.update({
                        "due_at": due_at,
                        "claimed_at": claimed_at,
                        "next_due": next_due,
                        "last_due": due_at,
                        "missed_this_claim": missed,
                        "missed_runs": item["missed_runs"] + missed,
                    })
                    claimed.append(item)
                self._conn.commit()
            except Exception:
                self._conn.rollback()
                raise
        return claimed

    def complete(self, schedule_id: str, result: str,
                 now: float | None = None) -> bool:
        """Persist the latest bounded result without changing cadence state."""
        completed_at = time.time() if now is None else now
        text = (result or "")[:_RESULT_LIMIT]
        with self._lock:
            cur = self._conn.execute(
                "UPDATE schedules SET last_result=?, updated=? WHERE id=?",
                (text, completed_at, schedule_id),
            )
            self._conn.commit()
            return cur.rowcount > 0

    @staticmethod
    def _to_dict(row) -> dict:
        return {
            "id": row[0],
            "tool": row[1],
            "args": json.loads(row[2]),
            "cadence": row[3],
            "risk": row[4],
            "approved_fingerprint": row[5],
            "enabled": bool(row[6]),
            "next_due": row[7],
            "last_due": row[8],
            "last_result": row[9],
            "missed_runs": row[10],
            "created": row[11],
            "updated": row[12],
        }
