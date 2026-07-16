"""Persistent job store for long-running work (analysis 2026-07-16 F-004).

Long actions used to be fire-and-forget: pull_model spawned a daemon thread,
swallowed every error, and told the user to "check later" -- a failed download
was indistinguishable from a slow one, and the audit log recorded an action
that may never have happened. This store gives every long action a persistent
job id, live progress, a terminal status with a REASON, and cooperative
cancellation.

Deliberately KIND-AGNOSTIC: the same substrate carries model pulls today and
scheduled/background tasks later -- new job kinds need no schema change.

Restart truth: a thread cannot survive the worker process, so any job still
'queued' or 'running' when the store opens is marked 'interrupted' with an
honest detail. Nothing auto-resumes; re-running the action is the resume
policy (Ollama pulls resume server-side from cached layers anyway).

Statuses: queued -> running -> completed | failed | cancelled, plus
interrupted (set only at startup). Terminal states never change again.
"""
from __future__ import annotations

import sqlite3
import threading
import time
import uuid

from . import paths as _paths

JOBS_DB_PATH = _paths.resolve("./modelrig-jobs.db", env="MODELRIG_JOBS_DB")

_TERMINAL = ("completed", "failed", "cancelled", "interrupted")
_FIELDS = ("status", "detail", "progress_completed", "progress_total")


class JobStore:
    def __init__(self, path: str = JOBS_DB_PATH):
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(path, check_same_thread=False)
        with self._lock:
            self._conn.execute(
                """CREATE TABLE IF NOT EXISTS jobs (
                       id TEXT PRIMARY KEY,
                       kind TEXT NOT NULL,
                       status TEXT NOT NULL,
                       detail TEXT NOT NULL DEFAULT '',
                       progress_completed INTEGER NOT NULL DEFAULT 0,
                       progress_total INTEGER NOT NULL DEFAULT 0,
                       cancel_requested INTEGER NOT NULL DEFAULT 0,
                       created REAL NOT NULL,
                       updated REAL NOT NULL)"""
            )
            # Restart truth: no thread survived into this process.
            self._conn.execute(
                "UPDATE jobs SET status='interrupted', "
                "detail='worker genstartet under kørsel — kør handlingen igen', "
                "updated=? WHERE status IN ('queued','running')",
                (time.time(),),
            )
            self._conn.commit()

    def create(self, kind: str, detail: str = "") -> str:
        job_id = uuid.uuid4().hex[:12]
        now = time.time()
        with self._lock:
            self._conn.execute(
                "INSERT INTO jobs (id, kind, status, detail, created, updated) "
                "VALUES (?, ?, 'queued', ?, ?, ?)",
                (job_id, kind, detail, now, now),
            )
            self._conn.commit()
        return job_id

    def update(self, job_id: str, **fields) -> None:
        """Update whitelisted fields. A terminal job is immutable."""
        cols = {k: v for k, v in fields.items() if k in _FIELDS}
        if not cols:
            return
        sets = ", ".join(f"{k}=?" for k in cols) + ", updated=?"
        with self._lock:
            self._conn.execute(
                f"UPDATE jobs SET {sets} WHERE id=? AND status NOT IN "
                f"({','.join('?' * len(_TERMINAL))})",
                (*cols.values(), time.time(), job_id, *_TERMINAL),
            )
            self._conn.commit()

    def request_cancel(self, job_id: str) -> bool:
        """Flag a job for cooperative cancellation. True if the job exists and
        is not already terminal."""
        with self._lock:
            cur = self._conn.execute(
                f"UPDATE jobs SET cancel_requested=1, updated=? WHERE id=? "
                f"AND status NOT IN ({','.join('?' * len(_TERMINAL))})",
                (time.time(), job_id, *_TERMINAL),
            )
            self._conn.commit()
            return cur.rowcount > 0

    def cancel_requested(self, job_id: str) -> bool:
        with self._lock:
            row = self._conn.execute(
                "SELECT cancel_requested FROM jobs WHERE id=?", (job_id,)
            ).fetchone()
        return bool(row and row[0])

    def get(self, job_id: str) -> dict | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT id, kind, status, detail, progress_completed, "
                "progress_total, created, updated FROM jobs WHERE id=?",
                (job_id,),
            ).fetchone()
        return self._to_dict(row) if row else None

    def recent(self, n: int = 5) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT id, kind, status, detail, progress_completed, "
                "progress_total, created, updated FROM jobs "
                "ORDER BY created DESC LIMIT ?",
                (n,),
            ).fetchall()
        return [self._to_dict(r) for r in rows]

    @staticmethod
    def _to_dict(row) -> dict:
        return {
            "id": row[0], "kind": row[1], "status": row[2], "detail": row[3],
            "progress_completed": row[4], "progress_total": row[5],
            "created": row[6], "updated": row[7],
        }
