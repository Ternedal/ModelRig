"""Durable image-generation job state machine; no inference or HTTP exposure.

SQLite is the authority for job state. A worker must explicitly claim jobs.
After a process restart, previously running jobs are failed, not silently rerun.

Ported from feat/image-generation-contract-20261021 with ChatGPT's hardening
(fix/image-job-quota-type-20261029 @ 5aab552d). ModelRig #2296: every job
names the model profile it is for (media_generation_profiles), plus bounded
scalar parameters; the profile's limits are checked by the generation layer.

Executor protocol (G2, #2296 6510332634, reviews 6511335742 / 6512440682). One
executor per GPU claims and transitions jobs as `<GPU UUID>:<instance>`:

    queued --claim_for--> running --begin_publish--> publishing --complete--> completed
                          running/publishing --fail--> failed
                          running --finish_cancelled--> cancelled   (after request_cancel)

begin_publish() is the commit point between cancellation and publication: one
transaction moves running -> publishing only if no cancel was requested, and
nothing may be published before it succeeds. request_cancel() answers
"cancelled" (queued), "requested" (running) or "too_late" (publishing).
recover_gpu() runs only while the executor holds its GPU's executor lock
(gpu_lease.acquire_executor_lock), so every other claim for that GPU belongs to
a dead process. Transitions require the caller's own instance id, so a stale
process cannot complete, fail or cancel a recovered job. A job that was
publishing when its executor died is failed as "interrupted during
publication": an asset may exist and must be reconciled by the sink owner.
The migration is additive (two columns), and the legacy single-process API
(claim/finish/cancel/recover_interrupted) still works for GenerationJobRunner.
"""
from __future__ import annotations

import json
import re
import sqlite3
from contextlib import contextmanager
import time
import uuid
from pathlib import Path
from typing import Callable


class ImageJobError(ValueError):
    pass


_PROFILE_ID = re.compile(r"[a-z0-9][a-z0-9-]{0,47}")
_INSTANCE = re.compile(r"GPU-[0-9a-f-]{36}:[0-9a-f]{16}")
ACTIVE_STATES = ("queued", "running", "publishing")  # all count toward the owner's limit
_PARAM_KEY = re.compile(r"[a-z][a-z0-9_]{0,31}")
MAX_PARAMS_BYTES = 4096


def _encode_params(params: object) -> str:
    if params is None:
        params = {}
    if not isinstance(params, dict) or len(params) > 16:
        raise ImageJobError("invalid job parameters")
    for key, value in params.items():
        if not isinstance(key, str) or not _PARAM_KEY.fullmatch(key):
            raise ImageJobError("invalid job parameters")
        if value is not None and type(value) not in (int, str):
            raise ImageJobError("invalid job parameters")
        if type(value) is str and len(value) > 256:
            raise ImageJobError("invalid job parameters")
    encoded = json.dumps(params, sort_keys=True, separators=(",", ":"))
    if len(encoded.encode("utf-8")) > MAX_PARAMS_BYTES:
        raise ImageJobError("invalid job parameters")
    return encoded


class ImageJobStore:
    def __init__(self, db_path: str, *, volume_guard: Callable[[], None] | None = None):
        self._volume_guard = volume_guard
        if self._volume_guard is not None:
            self._volume_guard()
        self.path = Path(db_path)
        if not self.path.parent.is_dir():
            raise ImageJobError("job database parent directory does not exist")
        with self._db() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS image_jobs (
                id TEXT PRIMARY KEY, owner TEXT NOT NULL, prompt TEXT NOT NULL,
                profile_id TEXT NOT NULL, params TEXT NOT NULL,
                state TEXT NOT NULL, created REAL NOT NULL, updated REAL NOT NULL,
                asset_id TEXT, error TEXT)""")
            db.execute("CREATE INDEX IF NOT EXISTS image_jobs_state ON image_jobs(state, created)")
            columns = {row[1] for row in db.execute("PRAGMA table_info(image_jobs)")}
            if "claimed_by" not in columns:  # additive migration, no data rewritten
                db.execute("ALTER TABLE image_jobs ADD COLUMN claimed_by TEXT")
            if "cancel_requested" not in columns:
                db.execute("ALTER TABLE image_jobs ADD COLUMN cancel_requested INTEGER NOT NULL DEFAULT 0")

    @contextmanager
    def _db(self):
        if self._volume_guard is not None:
            self._volume_guard()
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout=10000")
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def submit(self, owner: str, prompt: str, *, profile_id: str, params: dict | None = None,
               max_queued: int = 16, max_owner_active: int = 3) -> dict:
        if not isinstance(owner, str) or not owner.strip() or len(owner) > 256 or (
            not isinstance(prompt, str) or not prompt.strip() or len(prompt) > 4000
        ):
            raise ImageJobError("invalid owner or prompt")
        if not isinstance(profile_id, str) or not _PROFILE_ID.fullmatch(profile_id):
            raise ImageJobError("invalid profile id")
        encoded_params = _encode_params(params)
        if (type(max_queued) is not int or type(max_owner_active) is not int
                or max_queued < 1 or max_owner_active < 1):
            raise ImageJobError("invalid queue limits")
        job_id, now = uuid.uuid4().hex, time.time()
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            queued = db.execute("SELECT count(*) FROM image_jobs WHERE state='queued'").fetchone()[0]
            if queued >= max_queued:
                raise ImageJobError("image job queue full")
            owner_active = db.execute(
                "SELECT count(*) FROM image_jobs WHERE owner=? AND state IN ('queued','running','publishing')",
                (owner,)).fetchone()[0]
            if owner_active >= max_owner_active:
                raise ImageJobError("owner image job limit reached")
            db.execute("INSERT INTO image_jobs (id,owner,prompt,profile_id,params,state,created,updated) "
                       "VALUES (?,?,?,?,?,?,?,?)",
                       (job_id, owner, prompt, profile_id, encoded_params, "queued", now, now))
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
        # Legacy single-process API. Call only at startup, before any job workers begin claiming
        # jobs. With several executors use recover_gpu(), which leaves other executors' jobs alone.
        with self._db() as db:
            result = db.execute(
                "UPDATE image_jobs SET state='failed',error='interrupted by restart',updated=? WHERE state='running'",
                (time.time(),))
            return result.rowcount

    # --- executor protocol (G2) ----------------------------------------------------------------
    @staticmethod
    def _instance(instance: object) -> str:
        if not isinstance(instance, str) or not _INSTANCE.fullmatch(instance):
            raise ImageJobError("invalid executor instance")
        return instance

    def claim_for(self, profile_ids, instance: str) -> dict | None:
        """The oldest queued job for one of these profiles, claimed by this executor instance."""
        instance = self._instance(instance)
        ids = sorted(set(profile_ids))
        if not ids or any(not isinstance(p, str) or not _PROFILE_ID.fullmatch(p) for p in ids):
            raise ImageJobError("invalid profile ids")
        marks = ",".join("?" * len(ids))
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(f"SELECT * FROM image_jobs WHERE state='queued' AND profile_id IN ({marks}) "
                             "ORDER BY created,id LIMIT 1", ids).fetchone()
            if row is None:
                return None
            now = time.time()
            db.execute("UPDATE image_jobs SET state='running',claimed_by=?,updated=? WHERE id=? AND state='queued'",
                       (instance, now, row["id"]))
            return dict(row) | {"state": "running", "claimed_by": instance, "updated": now}

    def recover_gpu(self, gpu_uuid: str, instance: str) -> int:
        """Startup only, while holding this GPU's executor lock: fail every claim for this GPU
        by another (provably dead) instance. Other GPUs' jobs are untouched."""
        instance = self._instance(instance)
        if not instance.startswith(f"{gpu_uuid}:"):
            raise ImageJobError("instance does not belong to this GPU")
        now, prefix = time.time(), f"{gpu_uuid}:"
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            running = db.execute(
                "UPDATE image_jobs SET state='failed',error='interrupted by restart',updated=? "
                "WHERE state='running' AND substr(claimed_by,1,?)=? AND claimed_by<>?",
                (now, len(prefix), prefix, instance)).rowcount
            publishing = db.execute(
                "UPDATE image_jobs SET state='failed',error='interrupted during publication',updated=? "
                "WHERE state='publishing' AND substr(claimed_by,1,?)=? AND claimed_by<>?",
                (now, len(prefix), prefix, instance)).rowcount
            return running + publishing

    def request_cancel(self, job_id: str, owner: str) -> str | None:
        """'cancelled' (was queued), 'requested' (running: the executor stops it), 'too_late'
        (publishing: it will complete), or None (not this owner's, or already finished)."""
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            now = time.time()
            if db.execute("UPDATE image_jobs SET state='cancelled',updated=? WHERE id=? AND owner=? AND state='queued'",
                          (now, job_id, owner)).rowcount:
                return "cancelled"
            if db.execute("UPDATE image_jobs SET cancel_requested=1,updated=? WHERE id=? AND owner=? "
                          "AND state='running'", (now, job_id, owner)).rowcount:
                return "requested"
            if db.execute("SELECT 1 FROM image_jobs WHERE id=? AND owner=? AND state='publishing'",
                          (job_id, owner)).fetchone():
                return "too_late"
            return None

    def cancel_requested(self, job_id: str, instance: str) -> bool:
        with self._db() as db:
            row = db.execute("SELECT cancel_requested FROM image_jobs WHERE id=? AND state='running' AND claimed_by=?",
                             (job_id, self._instance(instance))).fetchone()
            return bool(row and row[0])

    def begin_publish(self, job_id: str, instance: str) -> bool:
        """The commit point: running -> publishing only if no cancel was requested. Publish only after True."""
        with self._db() as db:
            return db.execute(
                "UPDATE image_jobs SET state='publishing',updated=? WHERE id=? AND state='running' "
                "AND claimed_by=? AND cancel_requested=0", (time.time(), job_id, self._instance(instance))).rowcount == 1

    def complete(self, job_id: str, instance: str, asset_id: str) -> bool:
        if not isinstance(asset_id, str) or not asset_id:
            raise ImageJobError("asset_id required")
        with self._db() as db:
            return db.execute(
                "UPDATE image_jobs SET state='completed',asset_id=?,updated=? WHERE id=? AND state='publishing' "
                "AND claimed_by=?", (asset_id, time.time(), job_id, self._instance(instance))).rowcount == 1

    def fail(self, job_id: str, instance: str, error: str) -> bool:
        if not isinstance(error, str) or not error:
            raise ImageJobError("error code required")
        with self._db() as db:
            return db.execute(
                "UPDATE image_jobs SET state='failed',error=?,updated=? WHERE id=? "
                "AND state IN ('running','publishing') AND claimed_by=?",
                (error, time.time(), job_id, self._instance(instance))).rowcount == 1

    def finish_cancelled(self, job_id: str, instance: str) -> bool:
        with self._db() as db:
            return db.execute(
                "UPDATE image_jobs SET state='cancelled',updated=? WHERE id=? AND state='running' AND claimed_by=?",
                (time.time(), job_id, self._instance(instance))).rowcount == 1
