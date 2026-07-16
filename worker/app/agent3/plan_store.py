from __future__ import annotations

import sqlite3
import threading
import time
import uuid
from pathlib import Path


class PlanStoreError(RuntimeError):
    pass


class PlanStore:
    """Short-lived, single-use storage for reviewed Agent 3.0 plans."""

    def __init__(self, path: str, ttl_seconds: int = 600):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self.ttl_seconds = max(30, min(ttl_seconds, 3600))
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS agent_plans ("
            "id TEXT PRIMARY KEY, payload TEXT NOT NULL, created_at REAL NOT NULL, "
            "expires_at REAL NOT NULL, consumed_at REAL)"
        )
        self._conn.commit()

    def save(self, payload: str) -> tuple[str, int]:
        plan_id = str(uuid.uuid4())
        now = time.time()
        with self._lock:
            self._conn.execute(
                "INSERT INTO agent_plans(id,payload,created_at,expires_at,consumed_at) "
                "VALUES(?,?,?,?,NULL)",
                (plan_id, payload, now, now + self.ttl_seconds),
            )
            self._conn.commit()
        return plan_id, self.ttl_seconds

    def consume(self, plan_id: str) -> str:
        """Atomically claim a plan. Reuse and expiry are refusals."""
        now = time.time()
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                row = self._conn.execute(
                    "SELECT payload,expires_at,consumed_at FROM agent_plans WHERE id=?",
                    (plan_id,),
                ).fetchone()
                if row is None:
                    raise PlanStoreError("plan not found")
                payload, expires_at, consumed_at = row
                if consumed_at is not None:
                    raise PlanStoreError("plan already used")
                if now > expires_at:
                    self._conn.execute(
                        "UPDATE agent_plans SET consumed_at=? WHERE id=? AND consumed_at IS NULL",
                        (now, plan_id),
                    )
                    raise PlanStoreError("plan expired")
                changed = self._conn.execute(
                    "UPDATE agent_plans SET consumed_at=? WHERE id=? AND consumed_at IS NULL",
                    (now, plan_id),
                ).rowcount
                if changed != 1:
                    raise PlanStoreError("plan already used")
                self._conn.commit()
                return str(payload)
            except Exception:
                self._conn.rollback()
                raise

    def purge(self) -> int:
        now = time.time()
        with self._lock:
            cur = self._conn.execute(
                "DELETE FROM agent_plans WHERE expires_at < ? OR consumed_at IS NOT NULL",
                (now,),
            )
            self._conn.commit()
            return cur.rowcount
