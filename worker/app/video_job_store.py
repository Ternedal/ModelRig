"""Persistent video job lifecycle. No runtime mounts or external effects."""
from __future__ import annotations

import json
import sqlite3
import time
import uuid
from dataclasses import asdict
from pathlib import Path

from .video_contract import VideoRequest
from .video_storage_config import configured_video_storage

TRANSITIONS = {
    "queued": {"running", "failed", "cancelled"},
    "running": {"completed", "failed", "cancelled"},
    "completed": set(),
    "failed": set(),
    "cancelled": set(),
}


class VideoJobStore:
    @classmethod
    def on_external_volume(cls) -> "VideoJobStore":
        """Production factory: fail closed rather than using a local SQLite DB."""
        storage = configured_video_storage()
        paths = storage.initialize_directories()
        return cls(paths["jobs"] / "video_jobs.sqlite")

    def __init__(self, db_path: str | Path):
        self.db_path = str(db_path)
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS video_jobs ("
                "job_id TEXT PRIMARY KEY, state TEXT NOT NULL, "
                "request_json TEXT NOT NULL, created_at REAL NOT NULL, "
                "updated_at REAL NOT NULL, artifact_id TEXT, error_code TEXT)"
            )
            columns = {row[1] for row in db.execute("PRAGMA table_info(video_jobs)")}
            if "prompt_id" not in columns:
                db.execute("ALTER TABLE video_jobs ADD COLUMN prompt_id TEXT")

    def _connect(self):
        connection = sqlite3.connect(self.db_path, timeout=5)
        connection.row_factory = sqlite3.Row
        return connection

    def create(self, request: VideoRequest) -> str:
        if not isinstance(request, VideoRequest):
            raise TypeError("Validated VideoRequest required")
        job_id = uuid.uuid4().hex
        now = time.time()
        with self._connect() as db:
            db.execute(
                "INSERT INTO video_jobs (job_id, state, request_json, created_at, updated_at, artifact_id, error_code) "
                "VALUES (?,?,?,?,?,?,?)",
                (job_id, "queued", json.dumps(asdict(request)), now, now, None, None),
            )
        return job_id

    def get(self, job_id: str) -> dict | None:
        with self._connect() as db:
            row = db.execute("SELECT * FROM video_jobs WHERE job_id=?", (job_id,)).fetchone()
            return dict(row) if row is not None else None

    def transition(self, job_id: str, expected: str, new_state: str,
                   *, artifact_id: str | None = None, error_code: str | None = None) -> bool:
        if expected not in TRANSITIONS or new_state not in TRANSITIONS[expected]:
            raise ValueError("Invalid state transition")
        if new_state == "completed":
            if not artifact_id or len(artifact_id) > 128 or not artifact_id.isascii() or not all(c.isalnum() or c in "-_" for c in artifact_id):
                raise ValueError("Safe artifact ID required")
        elif artifact_id is not None:
            raise ValueError("Artifact only permitted for completed jobs")
        if new_state == "failed":
            if not error_code or len(error_code) > 64 or not error_code.isascii() or not all(c.isalnum() or c in "-_" for c in error_code):
                raise ValueError("Safe error code required")
        elif error_code is not None:
            raise ValueError("Error code only permitted for failed jobs")
        with self._connect() as db:
            result = db.execute(
                "UPDATE video_jobs SET state=?, updated_at=?, artifact_id=?, error_code=? "
                "WHERE job_id=? AND state=?",
                (new_state, time.time(), artifact_id, error_code, job_id, expected),
            )
            return result.rowcount == 1

    def record_prompt(self, job_id: str, prompt_id: str) -> bool:
        """Persist ComfyUI correlation before a later collector checks history."""
        if not isinstance(prompt_id, str) or not (1 <= len(prompt_id) <= 128) or not prompt_id.isascii() or not all(c.isalnum() or c in "-_" for c in prompt_id):
            raise ValueError("Invalid backend prompt ID")
        with self._connect() as db:
            result = db.execute(
                "UPDATE video_jobs SET prompt_id=?, updated_at=? WHERE job_id=? AND state='running' AND prompt_id IS NULL",
                (prompt_id, time.time(), job_id),
            )
            return result.rowcount == 1

    def awaiting_result(self, limit: int = 10) -> list[dict]:
        if type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError("Invalid result limit")
        with self._connect() as db:
            rows = db.execute(
                "SELECT * FROM video_jobs WHERE state='running' AND prompt_id IS NOT NULL ORDER BY updated_at, job_id LIMIT ?",
                (limit,),
            ).fetchall()
            return [dict(row) for row in rows]

    def queued(self, limit: int = 10) -> list[dict]:
        if type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError("Invalid queue limit")
        with self._connect() as db:
            rows = db.execute(
                "SELECT * FROM video_jobs WHERE state='queued' ORDER BY created_at, job_id LIMIT ?",
                (limit,),
            ).fetchall()
            return [dict(row) for row in rows]
