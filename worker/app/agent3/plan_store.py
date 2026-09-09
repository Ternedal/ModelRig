from __future__ import annotations

import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


class PlanStoreError(RuntimeError):
    pass


class PlanStore:
    """Short-lived, single-use storage for reviewed Agent 3.0 plans.

    File-backed connections are operation-scoped so an idle mounted surface does
    not pin SQLite files on Windows. A literal ``:memory:`` store necessarily
    retains one connection because each new SQLite connection would otherwise
    address a different empty database. The in-process lock serializes token
    consumption; ``BEGIN IMMEDIATE`` remains the cross-process claim for files.
    """

    def __init__(self, path: str, ttl_seconds: int = 600):
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self.ttl_seconds = max(30, min(ttl_seconds, 3600))
        # Opaque per-store/process generation used only to decide whether an
        # in-process task executor from a previous worker can still be live.
        self._start_owner = uuid.uuid4().hex
        self._lock = threading.RLock()
        self._closed = False
        self._memory_connection = self._connect() if path == ":memory:" else None
        with self._connection() as connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS agent_plans ("
                "id TEXT PRIMARY KEY, payload TEXT NOT NULL, created_at REAL NOT NULL, "
                "expires_at REAL NOT NULL, consumed_at REAL)"
            )
            columns = {
                str(row[1])
                for row in connection.execute("PRAGMA table_info(agent_plans)").fetchall()
            }
            if "start_result" not in columns:
                connection.execute("ALTER TABLE agent_plans ADD COLUMN start_result TEXT")
            if "result_run_id" not in columns:
                connection.execute("ALTER TABLE agent_plans ADD COLUMN result_run_id TEXT")
            if "start_owner" not in columns:
                connection.execute("ALTER TABLE agent_plans ADD COLUMN start_owner TEXT")
            connection.commit()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path, check_same_thread=False)

    def _require_open(self) -> None:
        if self._closed:
            raise PlanStoreError("plan store is closed")

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        self._require_open()
        if self._memory_connection is not None:
            yield self._memory_connection
            return
        connection = self._connect()
        try:
            yield connection
        finally:
            connection.close()

    def close(self) -> None:
        """Prevent future operations and release the optional in-memory handle."""
        with self._lock:
            if self._closed:
                return
            connection = self._memory_connection
            self._memory_connection = None
            self._closed = True
            if connection is not None:
                connection.close()

    def save(self, payload: str) -> tuple[str, int]:
        plan_id = str(uuid.uuid4())
        now = time.time()
        with self._lock:
            with self._connection() as connection:
                connection.execute(
                    "INSERT INTO agent_plans(id,payload,created_at,expires_at,consumed_at) "
                    "VALUES(?,?,?,?,NULL)",
                    (plan_id, payload, now, now + self.ttl_seconds),
                )
                connection.commit()
        return plan_id, self.ttl_seconds

    def consume(self, plan_id: str) -> str:
        """Atomically claim a plan. Reuse and expiry are refusals."""
        now = time.time()
        with self._lock:
            with self._connection() as connection:
                try:
                    connection.execute("BEGIN IMMEDIATE")
                    row = connection.execute(
                        "SELECT payload,expires_at,consumed_at FROM agent_plans WHERE id=?",
                        (plan_id,),
                    ).fetchone()
                    if row is None:
                        raise PlanStoreError("plan not found")
                    payload, expires_at, consumed_at = row
                    if consumed_at is not None:
                        raise PlanStoreError("plan already used")
                    if now > expires_at:
                        connection.execute(
                            "UPDATE agent_plans SET consumed_at=? "
                            "WHERE id=? AND consumed_at IS NULL",
                            (now, plan_id),
                        )
                        raise PlanStoreError("plan expired")
                    changed = connection.execute(
                        "UPDATE agent_plans SET consumed_at=? "
                        "WHERE id=? AND consumed_at IS NULL",
                        (now, plan_id),
                    ).rowcount
                    if changed != 1:
                        raise PlanStoreError("plan already used")
                    connection.commit()
                    return str(payload)
                except Exception:
                    connection.rollback()
                    raise

    @property
    def start_owner(self) -> str:
        """Opaque owner for executor work created by this PlanStore generation."""
        return self._start_owner

    @staticmethod
    def _owner_value(value: object) -> str | None:
        if value is None:
            return None
        if not isinstance(value, str) or not value:
            raise PlanStoreError("plan has invalid start owner")
        return value

    def start_recovery(self, plan_id: str) -> tuple[str, str | None, str | None] | None:
        """Return task-Start state plus the opaque executor-generation owner."""
        with self._lock:
            with self._connection() as connection:
                row = connection.execute(
                    "SELECT consumed_at,start_result,result_run_id,start_owner "
                    "FROM agent_plans WHERE id=?",
                    (plan_id,),
                ).fetchone()
        if row is None:
            return None
        consumed_at, result, run_id, owner_raw = row
        owner = self._owner_value(owner_raw)
        if result == "accepted":
            if not isinstance(run_id, str) or not run_id:
                raise PlanStoreError("accepted plan is missing its task run")
            return "accepted", run_id, owner
        if result == "pending":
            return "pending", run_id if isinstance(run_id, str) and run_id else None, owner
        if result == "refused":
            return "refused", None, None
        if result is not None:
            raise PlanStoreError("plan has invalid start result")
        if consumed_at is not None:
            return "pending", None, owner
        return None

    def start_result(self, plan_id: str) -> tuple[str, str | None] | None:
        """Compatibility view of task-Start recovery without owner metadata."""
        recovery = self.start_recovery(plan_id)
        if recovery is None:
            return None
        state, run_id, _owner = recovery
        return state, run_id

    def start_recovery_for_run(self, run_id: str) -> tuple[str, str, str | None] | None:
        """Resolve the one task plan that owns a pending/accepted task run."""
        with self._lock:
            with self._connection() as connection:
                rows = connection.execute(
                    "SELECT id,start_result,start_owner FROM agent_plans "
                    "WHERE result_run_id=? AND start_result IN ('pending','accepted')",
                    (run_id,),
                ).fetchall()
        if not rows:
            return None
        if len(rows) != 1:
            raise PlanStoreError("task run is bound to multiple start records")
        plan_id, state, owner_raw = rows[0]
        if state not in {"pending", "accepted"}:
            raise PlanStoreError("task run has invalid start state")
        return str(plan_id), str(state), self._owner_value(owner_raw)

    def claim_start_recovery(
        self,
        plan_id: str,
        run_id: str,
        previous_owner: str | None,
    ) -> str | None:
        """CAS a dead-owner pending/accepted run to this process generation."""
        now = time.time()
        with self._lock:
            with self._connection() as connection:
                try:
                    connection.execute("BEGIN IMMEDIATE")
                    row = connection.execute(
                        "SELECT start_result,result_run_id,start_owner,expires_at "
                        "FROM agent_plans WHERE id=?",
                        (plan_id,),
                    ).fetchone()
                    if row is None:
                        raise PlanStoreError("plan not found")
                    state, existing_run_id, owner_raw, expires_at = row
                    if state not in {"pending", "accepted"} or existing_run_id != run_id:
                        raise PlanStoreError("plan is not recoverable for this task run")
                    owner = self._owner_value(owner_raw)
                    if owner == self._start_owner or owner != previous_owner:
                        connection.commit()
                        return None
                    connection.execute(
                        "UPDATE agent_plans SET start_owner=?,expires_at=? WHERE id=?",
                        (self._start_owner, max(float(expires_at), now + self.ttl_seconds), plan_id),
                    )
                    connection.commit()
                    return str(state)
                except Exception:
                    connection.rollback()
                    raise

    def release_start_recovery_claim(self, plan_id: str, run_id: str) -> bool:
        """Release a current-generation claim when executor submission failed."""
        with self._lock:
            with self._connection() as connection:
                try:
                    connection.execute("BEGIN IMMEDIATE")
                    changed = connection.execute(
                        "UPDATE agent_plans SET start_owner=NULL "
                        "WHERE id=? AND result_run_id=? AND start_owner=? "
                        "AND start_result IN ('pending','accepted')",
                        (plan_id, run_id, self._start_owner),
                    ).rowcount
                    connection.commit()
                    return changed == 1
                except Exception:
                    connection.rollback()
                    raise

    def bind_pending_run(self, plan_id: str, run_id: str) -> None:
        """Bind a consumed task plan to one run before executor submission."""
        if not run_id:
            raise PlanStoreError("pending task run id is missing")
        now = time.time()
        with self._lock:
            with self._connection() as connection:
                try:
                    connection.execute("BEGIN IMMEDIATE")
                    row = connection.execute(
                        "SELECT consumed_at,start_result,result_run_id,expires_at "
                        "FROM agent_plans WHERE id=?",
                        (plan_id,),
                    ).fetchone()
                    if row is None or row[0] is None:
                        raise PlanStoreError("plan was not consumed before run binding")
                    _consumed_at, result, existing_run_id, expires_at = row
                    if result == "refused":
                        raise PlanStoreError("refused plan cannot bind a task run")
                    if result in {"pending", "accepted"}:
                        if existing_run_id != run_id:
                            raise PlanStoreError("plan is already bound to another task run")
                        connection.commit()
                        return
                    connection.execute(
                        "UPDATE agent_plans SET start_result='pending',result_run_id=?,"
                        "start_owner=?,expires_at=? WHERE id=?",
                        (
                            run_id,
                            self._start_owner,
                            max(float(expires_at), now + self.ttl_seconds),
                            plan_id,
                        ),
                    )
                    connection.commit()
                except Exception:
                    connection.rollback()
                    raise

    def mark_start_accepted(self, plan_id: str, run_id: str) -> None:
        """Publish accepted authority only after executor submission succeeds."""
        with self._lock:
            with self._connection() as connection:
                try:
                    connection.execute("BEGIN IMMEDIATE")
                    row = connection.execute(
                        "SELECT consumed_at,start_result,result_run_id FROM agent_plans WHERE id=?",
                        (plan_id,),
                    ).fetchone()
                    if row is None or row[0] is None:
                        raise PlanStoreError("unconsumed plan cannot become accepted")
                    _consumed_at, result, existing_run_id = row
                    if result == "accepted":
                        if existing_run_id != run_id:
                            raise PlanStoreError("plan is already accepted for another task run")
                        connection.commit()
                        return
                    if result != "pending" or existing_run_id != run_id:
                        raise PlanStoreError("plan is not pending for this task run")
                    connection.execute(
                        "UPDATE agent_plans SET start_result='accepted' WHERE id=?",
                        (plan_id,),
                    )
                    connection.commit()
                except Exception:
                    connection.rollback()
                    raise

    def mark_start_refused(self, plan_id: str) -> None:
        """Finalize a consumed task plan that cannot create a run."""
        with self._lock:
            with self._connection() as connection:
                try:
                    connection.execute("BEGIN IMMEDIATE")
                    row = connection.execute(
                        "SELECT consumed_at,start_result FROM agent_plans WHERE id=?",
                        (plan_id,),
                    ).fetchone()
                    if row is None or row[0] is None:
                        raise PlanStoreError("unconsumed plan cannot be marked refused")
                    if row[1] == "accepted":
                        raise PlanStoreError("accepted plan cannot be marked refused")
                    if row[1] not in (None, "pending", "refused"):
                        raise PlanStoreError("plan has invalid start result")
                    connection.execute(
                        "UPDATE agent_plans SET start_result='refused',result_run_id=NULL,start_owner=NULL WHERE id=?",
                        (plan_id,),
                    )
                    connection.commit()
                except Exception:
                    connection.rollback()
                    raise

    def purge(self) -> int:
        now = time.time()
        with self._lock:
            with self._connection() as connection:
                cursor = connection.execute(
                    "DELETE FROM agent_plans WHERE expires_at < ?",
                    (now,),
                )
                connection.commit()
                return cursor.rowcount
