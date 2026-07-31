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
        self._lock = threading.RLock()
        self._closed = False
        self._memory_connection = self._connect() if path == ":memory:" else None
        with self._connection() as connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS agent_plans ("
                "id TEXT PRIMARY KEY, payload TEXT NOT NULL, created_at REAL NOT NULL, "
                "expires_at REAL NOT NULL, consumed_at REAL)"
            )
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

    def purge(self) -> int:
        now = time.time()
        with self._lock:
            with self._connection() as connection:
                cursor = connection.execute(
                    "DELETE FROM agent_plans WHERE expires_at < ? OR consumed_at IS NOT NULL",
                    (now,),
                )
                connection.commit()
                return cursor.rowcount
