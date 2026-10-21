"""Durable image-generation job state machine; no inference or HTTP exposure.

SQLite is the authority for job state. A worker must explicitly claim jobs.
After a process restart, previously running jobs are failed, not silently rerun.
"""
from __future__ import annotations

import json
import sqlite3
import time
import uuid
from pathlib import Path

_STATES = {"queued", "running", "completed", "failed", "cancelled"}
_TERMINAL = {"completed", "failed", "cancelled"}


class ImageJobError(ValueError):
    pass


class ImageJobStore:
    def __init__(self, db_path: str):
        self.path = Path(db_path)
        if not self.path.parent.is_dir():
            raise ImageJobError("job database parent directory does not exist")
        with self._db() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS image_jobs (
                id TEXT PRIMARY KEY, owner TEXT NOT NULL, prompt TEXT NOT NULL,
                state TEXT NOT NULL, created REAL NOT NULL, updated REAL NOT NULL,
                asset_id TEXT, error TEXT)""")
            db.execute("CREATE INDEX IF NOT EXISTS image_jobs_state ON image_jobs(state, created)")

    def _db(self):
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout=10000")
        return connection

    def submit(self, owner: str, prompt: str, *, max_queued: int = 16, max_owner_active: int = 3) -> dict:
        if not owner or not isinstance(prompt, str) or not prompt.strip() or len(prompt) > 4000:
            raise ImageJobError("invalid owner or prompt")
        if max_queued < 1 or max_owner_active < 1:
            raise ImageJobError("invalid queue limits")
        job_id, now = uuid.uuid4().hex, time.time()
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            queued = db.execute("SELECT count(*) FROM image_jobs WHERE state='queued'").fetchone()[0]
            if queued >= max_queued:
                raise ImageJobError("image job queue full")
            owner_active = db.execute(
                "SELECT count(*) FROM image_jobs WHERE owner=? AND state IN ('queued','running')",
                (owner,)).fetchone()[0]
            if owner_active >= max_owner_active:
                raise ImageJobError("owner image job limit reached")
            db.execute("INSERT INTO image_jobs (id,owner,prompt,state,created,updated) VALUES (?,?,?,?,?,?)",
                       (job_id, owner, prompt, "queued", now, now))
        return {"job_id": job_id, "state": "queued"}

    def get(self, job_id: str, owner: str) -> dict | None:
        with self._db() as db:
            row = db.execute("SELECT * FROM image_jobs WHERE id=? AND owner=?", (job_id, owner)).fetchone()
            return dict(row) if row else None

    def claim(self) -> dict | None:
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM image_jobs WHERE state='queued' ORDER BY created,id LIMIT 1").fetchone()
            if row is None:
                return None
            now = time.time()
            db.execute("UPDATE image_jobs SET state='running',updated=? WHERE id=? AND state='queued'",
                       (now, row["id"]))
            return dict(row) | {"state": "running", "updated": now}

    def finish(self, job_id: str, *, asset_id: str | None = None, error: str | None = None) -> bool:
        if bool(asset_id) == bool(error):
            raise ImageJobError("exactly one of asset_id or error required")
        state = "completed" if asset_id else "failed"
        with self._db() as db:
            result = db.execute(
                "UPDATE image_jobs SET state=?,asset_id=?,error=?,updated=? WHERE id=? AND state='running'",
                (state, asset_id, error, time.time(), job_id))
            return result.rowcount == 1

    def cancel(self, job_id: str, owner: str) -> bool:
        # Running cancellation requires cooperation from the inference engine.
        # Only queued jobs can be safely cancelled by this store alone.
        with self._db() as db:
            result = db.execute(
                "UPDATE image_jobs SET state='cancelled',updated=? WHERE id=? AND owner=? AND state='queued'",
                (time.time(), job_id, owner))
            return result.rowcount == 1

    def recover_interrupted(self) -> int:
        # Call only at startup, before any job workers begin claiming jobs.
        with self._db() as db:
            result = db.execute(
                "UPDATE image_jobs SET state='failed',error='interrupted by restart',updated=? WHERE state='running'",
                (time.time(),))
            return result.rowcount
