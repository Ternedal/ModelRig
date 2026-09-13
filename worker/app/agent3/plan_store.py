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
            if "start_run" not in columns:
                connection.execute("ALTER TABLE agent_plans ADD COLUMN start_run TEXT")
            if "start_terminal_at" not in columns:
                connection.execute(
                    "ALTER TABLE agent_plans ADD COLUMN start_terminal_at REAL"
                )
            connection.execute(
                "CREATE TABLE IF NOT EXISTS agent_reviewed_starts ("
                "plan_id TEXT PRIMARY KEY, state TEXT NOT NULL, run_id TEXT, "
                "owner TEXT, created_at REAL NOT NULL, updated_at REAL NOT NULL, "
                "expires_at REAL NOT NULL)"
            )
            connection.commit()

        # Safe opportunistic cleanup: active Start recovery rows are excluded by
        # purge() until their exact run has been observed terminal.
        self.purge()

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
        # Bound file growth without a timer/background worker. A cleanup failure
        # fails the same SQLite write path rather than silently corrupting state.
        self.purge()
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

    def inspect_unconsumed(self, plan_id: str) -> str:
        """Read an unconsumed plan for validation without granting Start authority."""
        now = time.time()
        with self._lock:
            with self._connection() as connection:
                row = connection.execute(
                    "SELECT payload,expires_at,consumed_at FROM agent_plans WHERE id=?",
                    (plan_id,),
                ).fetchone()
        if row is None:
            raise PlanStoreError("plan not found")
        payload, expires_at, consumed_at = row
        if consumed_at is not None:
            raise PlanStoreError("plan already used")
        if now > float(expires_at):
            raise PlanStoreError("plan expired")
        return str(payload)

    def refuse_unconsumed(self, plan_id: str) -> bool:
        """Consume an unclaimed reviewed plan into a definitive refusal."""
        now = time.time()
        with self._lock:
            with self._connection() as connection:
                try:
                    connection.execute("BEGIN IMMEDIATE")
                    row = connection.execute(
                        "SELECT consumed_at,start_result FROM agent_plans WHERE id=?",
                        (plan_id,),
                    ).fetchone()
                    if row is None:
                        raise PlanStoreError("plan not found")
                    consumed_at, state = row
                    if state == "refused":
                        connection.commit()
                        return True
                    if consumed_at is not None or state is not None:
                        connection.commit()
                        return False
                    changed = connection.execute(
                        "UPDATE agent_plans SET consumed_at=?,start_result='refused',"
                        "result_run_id=NULL,start_owner=NULL,start_run=NULL,"
                        "start_terminal_at=NULL WHERE id=? "
                        "AND consumed_at IS NULL AND start_result IS NULL",
                        (now, plan_id),
                    ).rowcount
                    connection.commit()
                    return changed == 1
                except Exception:
                    connection.rollback()
                    raise


    def reviewed_start_recovery(
        self,
        plan_id: str,
    ) -> tuple[str, str | None, str | None] | None:
        """Return durable reviewed-Start state without granting new execution authority."""
        with self._lock:
            with self._connection() as connection:
                row = connection.execute(
                    "SELECT state,run_id,owner,expires_at FROM agent_reviewed_starts WHERE plan_id=?",
                    (plan_id,),
                ).fetchone()
        if row is None:
            return None
        state, run_id, owner_raw, _expires_at = row
        # Once Start has been claimed, wall-clock expiry must never turn ambiguous
        # execution authority into a definitive refusal. The exact plan/run binding
        # remains recoverable until code explicitly records a refusal.
        if state == "refused":
            return "refused", None, None
        if state not in {"pending", "accepted"}:
            raise PlanStoreError("reviewed Start has invalid state")
        if not isinstance(run_id, str) or not run_id:
            raise PlanStoreError("reviewed Start is missing its reserved run id")
        return str(state), run_id, self._owner_value(owner_raw)

    def claim_reviewed_start(self, plan_id: str, run_id: str) -> str:
        """Atomically consume one plan and bind a reserved reviewed-run id before execution."""
        if not run_id:
            raise PlanStoreError("reviewed Start run id is missing")
        now = time.time()
        recovery_expires = now + max(self.ttl_seconds, 86_400)
        with self._lock:
            with self._connection() as connection:
                try:
                    connection.execute("BEGIN IMMEDIATE")
                    existing = connection.execute(
                        "SELECT state FROM agent_reviewed_starts WHERE plan_id=?",
                        (plan_id,),
                    ).fetchone()
                    if existing is not None:
                        raise PlanStoreError("reviewed Start is already claimed")
                    row = connection.execute(
                        "SELECT payload,expires_at,consumed_at,start_result FROM agent_plans WHERE id=?",
                        (plan_id,),
                    ).fetchone()
                    if row is None:
                        raise PlanStoreError("plan not found")
                    payload, expires_at, consumed_at, task_start_result = row
                    if consumed_at is not None or task_start_result is not None:
                        raise PlanStoreError("plan already used")
                    if now > float(expires_at):
                        connection.execute(
                            "UPDATE agent_plans SET consumed_at=? WHERE id=? AND consumed_at IS NULL",
                            (now, plan_id),
                        )
                        connection.commit()
                        raise PlanStoreError("plan expired")
                    changed = connection.execute(
                        "UPDATE agent_plans SET consumed_at=?,expires_at=? "
                        "WHERE id=? AND consumed_at IS NULL AND start_result IS NULL",
                        (now, max(float(expires_at), recovery_expires), plan_id),
                    ).rowcount
                    if changed != 1:
                        raise PlanStoreError("plan already used")
                    connection.execute(
                        "INSERT INTO agent_reviewed_starts("
                        "plan_id,state,run_id,owner,created_at,updated_at,expires_at) "
                        "VALUES(?,'pending',?,?,?,?,?)",
                        (
                            plan_id,
                            run_id,
                            self._start_owner,
                            now,
                            now,
                            recovery_expires,
                        ),
                    )
                    connection.commit()
                    return str(payload)
                except Exception:
                    connection.rollback()
                    raise

    def reviewed_start_materialization(self, plan_id: str, run_id: str) -> str:
        """Return immutable reviewed-plan authority bound to one reserved run."""
        with self._lock:
            with self._connection() as connection:
                row = connection.execute(
                    "SELECT p.payload,r.state,r.run_id FROM agent_plans p "
                    "JOIN agent_reviewed_starts r ON r.plan_id=p.id WHERE p.id=?",
                    (plan_id,),
                ).fetchone()
        if row is None:
            raise PlanStoreError("reviewed Start plan not found")
        payload, state, existing_run_id = row
        if state not in {"pending", "accepted"} or existing_run_id != run_id:
            raise PlanStoreError("plan is not materializable for this reviewed run")
        return str(payload)

    def claim_reviewed_start_recovery(
        self,
        plan_id: str,
        run_id: str,
        previous_owner: str | None,
    ) -> bool:
        """Transfer a pending reviewed Start only from a dead worker generation."""
        now = time.time()
        recovery_expires = now + max(self.ttl_seconds, 86_400)
        with self._lock:
            with self._connection() as connection:
                try:
                    connection.execute("BEGIN IMMEDIATE")
                    row = connection.execute(
                        "SELECT state,run_id,owner,expires_at FROM agent_reviewed_starts WHERE plan_id=?",
                        (plan_id,),
                    ).fetchone()
                    if row is None:
                        raise PlanStoreError("reviewed Start recovery not found")
                    state, existing_run_id, owner_raw, expires_at = row
                    if state != "pending" or existing_run_id != run_id:
                        raise PlanStoreError("reviewed Start is not pending for this run")
                    owner = self._owner_value(owner_raw)
                    if owner == self._start_owner or owner != previous_owner:
                        connection.commit()
                        return False
                    connection.execute(
                        "UPDATE agent_reviewed_starts SET owner=?,updated_at=?,expires_at=? "
                        "WHERE plan_id=? AND state='pending' AND run_id=?",
                        (
                            self._start_owner,
                            now,
                            max(float(expires_at), recovery_expires),
                            plan_id,
                            run_id,
                        ),
                    )
                    connection.execute(
                        "UPDATE agent_plans SET expires_at=MAX(expires_at,?) WHERE id=?",
                        (recovery_expires, plan_id),
                    )
                    connection.commit()
                    return True
                except Exception:
                    connection.rollback()
                    raise

    def release_reviewed_start_recovery(self, plan_id: str, run_id: str) -> bool:
        """Release this worker's pending recovery claim after materialized recovery exits."""
        now = time.time()
        with self._lock:
            with self._connection() as connection:
                try:
                    connection.execute("BEGIN IMMEDIATE")
                    row = connection.execute(
                        "SELECT state,run_id,owner FROM agent_reviewed_starts WHERE plan_id=?",
                        (plan_id,),
                    ).fetchone()
                    if row is None:
                        raise PlanStoreError("reviewed Start recovery not found")
                    state, existing_run_id, owner_raw = row
                    if state != "pending" or existing_run_id != run_id:
                        connection.commit()
                        return False
                    owner = self._owner_value(owner_raw)
                    if owner != self._start_owner:
                        connection.commit()
                        return False
                    changed = connection.execute(
                        "UPDATE agent_reviewed_starts SET owner=NULL,updated_at=? "
                        "WHERE plan_id=? AND state='pending' AND run_id=? AND owner=?",
                        (now, plan_id, run_id, self._start_owner),
                    ).rowcount
                    connection.commit()
                    return changed == 1
                except Exception:
                    connection.rollback()
                    raise

    def mark_reviewed_start_accepted(self, plan_id: str, run_id: str) -> None:
        """Publish same-plan recovery only for the exact reserved run id."""
        now = time.time()
        recovery_expires = now + max(self.ttl_seconds, 86_400)
        with self._lock:
            with self._connection() as connection:
                try:
                    connection.execute("BEGIN IMMEDIATE")
                    row = connection.execute(
                        "SELECT state,run_id,expires_at FROM agent_reviewed_starts WHERE plan_id=?",
                        (plan_id,),
                    ).fetchone()
                    if row is None:
                        raise PlanStoreError("reviewed Start recovery not found")
                    state, existing_run_id, expires_at = row
                    if existing_run_id != run_id:
                        raise PlanStoreError("reviewed Start is bound to another run")
                    if state == "accepted":
                        connection.commit()
                        return
                    if state != "pending":
                        raise PlanStoreError("reviewed Start is not pending")
                    connection.execute(
                        "UPDATE agent_reviewed_starts SET state='accepted',owner=?,updated_at=?,expires_at=? "
                        "WHERE plan_id=? AND run_id=?",
                        (
                            self._start_owner,
                            now,
                            max(float(expires_at), recovery_expires),
                            plan_id,
                            run_id,
                        ),
                    )
                    connection.execute(
                        "UPDATE agent_plans SET expires_at=MAX(expires_at,?) WHERE id=?",
                        (recovery_expires, plan_id),
                    )
                    connection.commit()
                except Exception:
                    connection.rollback()
                    raise

    def mark_reviewed_start_refused(self, plan_id: str, run_id: str) -> None:
        """Finalize a claimed reviewed Start only if its reserved run never existed."""
        now = time.time()
        with self._lock:
            with self._connection() as connection:
                try:
                    connection.execute("BEGIN IMMEDIATE")
                    row = connection.execute(
                        "SELECT state,run_id FROM agent_reviewed_starts WHERE plan_id=?",
                        (plan_id,),
                    ).fetchone()
                    if row is None:
                        connection.commit()
                        return
                    state, existing_run_id = row
                    if state == "accepted":
                        raise PlanStoreError("accepted reviewed Start cannot be refused")
                    if existing_run_id != run_id:
                        raise PlanStoreError("reviewed Start refusal targets another run")
                    connection.execute(
                        "UPDATE agent_reviewed_starts SET state='refused',run_id=NULL,owner=NULL,updated_at=? "
                        "WHERE plan_id=? AND state='pending'",
                        (now, plan_id),
                    )
                    connection.commit()
                except Exception:
                    connection.rollback()
                    raise

    def claim_task_start(self, plan_id: str, run_id: str, prepared_run: str) -> None:
        """Atomically consume a validated task plan and bind its exact prepared run."""
        if not run_id:
            raise PlanStoreError("pending task run id is missing")
        if not prepared_run:
            raise PlanStoreError("prepared task run is missing")
        now = time.time()
        with self._lock:
            with self._connection() as connection:
                try:
                    connection.execute("BEGIN IMMEDIATE")
                    row = connection.execute(
                        "SELECT expires_at,consumed_at,start_result FROM agent_plans WHERE id=?",
                        (plan_id,),
                    ).fetchone()
                    if row is None:
                        raise PlanStoreError("plan not found")
                    expires_at, consumed_at, state = row
                    if consumed_at is not None or state is not None:
                        raise PlanStoreError("plan already used")
                    if now > float(expires_at):
                        connection.execute(
                            "UPDATE agent_plans SET consumed_at=?,start_result='refused',"
                            "result_run_id=NULL,start_owner=NULL,start_run=NULL,"
                            "start_terminal_at=NULL "
                            "WHERE id=? AND consumed_at IS NULL AND start_result IS NULL",
                            (now, plan_id),
                        )
                        connection.commit()
                        raise PlanStoreError("plan expired")
                    changed = connection.execute(
                        "UPDATE agent_plans SET consumed_at=?,start_result='pending',"
                        "result_run_id=?,start_owner=?,start_run=?,start_terminal_at=NULL,"
                        "expires_at=? "
                        "WHERE id=? AND consumed_at IS NULL AND start_result IS NULL",
                        (
                            now,
                            run_id,
                            self._start_owner,
                            prepared_run,
                            max(float(expires_at), now + self.ttl_seconds),
                            plan_id,
                        ),
                    ).rowcount
                    if changed != 1:
                        raise PlanStoreError("plan already used")
                    connection.commit()
                except Exception:
                    connection.rollback()
                    raise

    def start_materialization(self, plan_id: str, run_id: str) -> tuple[str, str]:
        """Return immutable plan + prepared-run authority for one claimed task Start."""
        with self._lock:
            with self._connection() as connection:
                row = connection.execute(
                    "SELECT payload,start_result,result_run_id,start_run FROM agent_plans WHERE id=?",
                    (plan_id,),
                ).fetchone()
        if row is None:
            raise PlanStoreError("plan not found")
        payload, state, existing_run_id, prepared_run = row
        if state not in {"pending", "accepted"} or existing_run_id != run_id:
            raise PlanStoreError("plan is not materializable for this task run")
        if not isinstance(prepared_run, str) or not prepared_run:
            raise PlanStoreError("task Start is missing its prepared run")
        return str(payload), prepared_run

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
                    "SELECT consumed_at,start_result,result_run_id,start_owner,"
                    "expires_at,start_terminal_at FROM agent_plans WHERE id=?",
                    (plan_id,),
                ).fetchone()
        if row is None:
            return None
        consumed_at, result, run_id, owner_raw, expires_at, terminal_at = row
        if (
            result in {"pending", "accepted"}
            and terminal_at is not None
            and time.time() > float(expires_at)
        ):
            # The post-terminal same-plan recovery grace is authority, not only
            # storage cleanup. Enforce it even when opportunistic purge() has
            # not run since the task became terminal.
            return "refused", None, None
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
                    "SELECT id,start_result,start_owner,expires_at,start_terminal_at "
                    "FROM agent_plans WHERE result_run_id=? "
                    "AND start_result IN ('pending','accepted')",
                    (run_id,),
                ).fetchall()
        if not rows:
            return None
        if len(rows) != 1:
            raise PlanStoreError("task run is bound to multiple start records")
        plan_id, state, owner_raw, expires_at, terminal_at = rows[0]
        if state not in {"pending", "accepted"}:
            raise PlanStoreError("task run has invalid start state")
        if terminal_at is not None and time.time() > float(expires_at):
            # A known run id still has status authority through task_response();
            # only the expired plan-to-run recovery binding stops being active.
            return None
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
                        "start_owner=?,start_terminal_at=NULL,expires_at=? WHERE id=?",
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
                        "UPDATE agent_plans SET start_result='refused',result_run_id=NULL,"
                        "start_owner=NULL,start_run=NULL,start_terminal_at=NULL WHERE id=?",
                        (plan_id,),
                    )
                    connection.commit()
                except Exception:
                    connection.rollback()
                    raise

    def unmarked_start_recovery_run_ids(self) -> tuple[str, ...]:
        """Return only exact bound Start recoveries lacking terminal retention.

        This is an internal startup-reconciliation view, not run discovery: rows
        without a server-bound run id, refusals and already-terminal-marked rows
        are deliberately excluded.
        """
        with self._lock:
            with self._connection() as connection:
                rows = connection.execute(
                    "SELECT result_run_id FROM agent_plans "
                    "WHERE result_run_id IS NOT NULL "
                    "AND start_result IN ('pending','accepted') "
                    "AND start_terminal_at IS NULL "
                    "ORDER BY created_at,id"
                ).fetchall()
        return tuple(str(row[0]) for row in rows if row[0])

    def mark_start_terminal_for_run(self, run_id: str) -> bool:
        """Start a bounded post-terminal recovery grace for one exact task run."""
        if not run_id:
            raise PlanStoreError("terminal task run id is missing")
        now = time.time()
        with self._lock:
            with self._connection() as connection:
                try:
                    connection.execute("BEGIN IMMEDIATE")
                    rows = connection.execute(
                        "SELECT id,start_terminal_at,expires_at FROM agent_plans "
                        "WHERE result_run_id=? AND start_result IN ('pending','accepted')",
                        (run_id,),
                    ).fetchall()
                    if not rows:
                        connection.commit()
                        return False
                    if len(rows) != 1:
                        raise PlanStoreError(
                            "task run is bound to multiple terminal recovery records"
                        )
                    plan_id, terminal_at, expires_at = rows[0]
                    if terminal_at is not None:
                        connection.commit()
                        return True
                    changed = connection.execute(
                        "UPDATE agent_plans SET start_terminal_at=?,expires_at=? "
                        "WHERE id=? AND result_run_id=? AND start_terminal_at IS NULL "
                        "AND start_result IN ('pending','accepted')",
                        (
                            now,
                            max(float(expires_at), now + self.ttl_seconds),
                            plan_id,
                            run_id,
                        ),
                    ).rowcount
                    if changed != 1:
                        raise PlanStoreError(
                            "task Start terminal retention changed concurrently"
                        )
                    connection.commit()
                    return True
                except Exception:
                    connection.rollback()
                    raise

    def purge(self) -> int:
        """Delete only records whose expiry can no longer carry live Start authority."""
        now = time.time()
        with self._lock:
            with self._connection() as connection:
                connection.execute(
                    "DELETE FROM agent_reviewed_starts "
                    "WHERE expires_at < ? AND state='refused'",
                    (now,),
                )
                cursor = connection.execute(
                    "DELETE FROM agent_plans WHERE expires_at < ? AND ("
                    "start_result IS NULL OR start_result='refused' OR "
                    "(start_result IN ('pending','accepted') "
                    "AND start_terminal_at IS NOT NULL)) "
                    "AND id NOT IN (SELECT plan_id FROM agent_reviewed_starts "
                    "WHERE state IN ('pending','accepted'))",
                    (now,),
                )
                connection.commit()
                return cursor.rowcount
