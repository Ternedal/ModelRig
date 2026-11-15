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
    queued --(24 h without a claim)--> expired   (error 'expired_unclaimed'; Anders, 6 Nov 2026)

A queued job expires once time.time() - created >= QUEUED_MAX_AGE_S (24 h). expire_queued()
runs it; claim_for() and submit() run it in their own transaction (so a stale job is never
claimed and never holds one of the 16 queue places), and get() does when it reads a stale job
(so the owner sees it even while media is off). Running and publishing jobs never expire.

begin_publish() is the commit point between cancellation and publication: one
transaction moves running -> publishing only if no cancel was requested, and
nothing may be published before it succeeds. request_cancel() answers
"cancelled" (queued), "requested" (running) or "too_late" (publishing).
recover_gpu() runs only while the executor holds its GPU's executor lock
(gpu_lease.acquire_executor_lock), so every other claim for that GPU belongs to
a dead process. Transitions require the caller's own instance id, so a stale
process cannot complete, fail or cancel a recovered job. A job that was
publishing when its executor died is failed as `interrupted_during_publication`:
an asset may exist and must be reconciled by the sink owner.
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

from .media_generation_contract import is_plain_file_name


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


# Prompt retention (Anders, 5 Nov 2026, #2296 risk 8.1): the prompt of a finished job is
# blanked 30 days after it finished. The row stays (id, owner, state, asset, error), so the
# gallery and the audit trail still resolve; only the user's text goes.
PROMPT_RETENTION_S = 30 * 24 * 3600

HANDOFF_STAGES = ("copying", "copied")
_HANDOFF_ASSET = re.compile(r"[A-Za-z0-9_-]{1,128}")
_SHA256 = re.compile(r"[0-9a-f]{64}")


def _nonnegative_int(value: object) -> bool:
    return type(value) is int and 0 <= value < 2 ** 64


def _file_id(value: object) -> bool:
    # st_dev/st_ino: ReFS file ids are 128-bit (FILE_ID_128), and the receipt is JSON text, so
    # wide ids are kept exactly. #2357 review P3-1 and Codex 4522272230: a 64-bit bound refused
    # every receipt on a ReFS work area or publication volume, and the render was deleted.
    return type(value) is int and 0 <= value < 2 ** 128


def _file_identity(value: object, *, named: bool) -> bool:
    keys = {"name", "dev", "ino", "size"} if named else {"dev", "ino"}
    return (isinstance(value, dict) and set(value) == keys
            and all(_file_id(value[k]) for k in ("dev", "ino"))
            and (not named or _nonnegative_int(value["size"]))
            # The adapter's own rule for its output name, so a render it accepted is never refused
            # here and then deleted as an explicit refusal (Codex #2357 4504060850).
            and (not named or is_plain_file_name(value["name"])))


def check_handoff_record(record: object) -> dict:
    """A hand-off receipt, or ImageJobError. Allowed keys only:
    - stage: "copying" (before the copy) or "copied" (after copy and sync);
    - output: {name, dev, ino, size} of the finished file in the work area (a plain file name);
    - sha256 and size: of the copy, once "copied";
    - volume: {dev, ino} of the publication volume's root at hand-off;
    - source_asset_id and source_sha256: the source of an image-to-video job."""
    if not isinstance(record, dict) or not set(record) <= {"stage", "output", "sha256", "size", "volume",
                                                           "source_asset_id", "source_sha256"}:
        raise ImageJobError("hand-off record has unknown fields")
    if record.get("stage") not in HANDOFF_STAGES or not _file_identity(record.get("output"), named=True):
        raise ImageJobError("hand-off record needs a stage and the output's identity")
    if record["stage"] == "copied" and not (type(record.get("sha256")) is str and _SHA256.fullmatch(record["sha256"])
                                            and _nonnegative_int(record.get("size"))):
        raise ImageJobError("a copied hand-off needs sha256 and size")
    if record["stage"] == "copying" and ("sha256" in record or "size" in record):
        raise ImageJobError("sha256 and size are known only once copied")
    if "volume" in record and not _file_identity(record["volume"], named=False):
        raise ImageJobError("hand-off volume identity is malformed")
    if "source_asset_id" in record and not (type(record["source_asset_id"]) is str
                                            and _HANDOFF_ASSET.fullmatch(record["source_asset_id"])):
        raise ImageJobError("hand-off source asset id is malformed")
    if "source_sha256" in record and not (type(record["source_sha256"]) is str
                                          and _SHA256.fullmatch(record["source_sha256"])):
        raise ImageJobError("hand-off source hash is malformed")
    return dict(record)


_FINISHED = ("completed", "failed", "cancelled", "expired")

# Anders, 6 Nov 2026 (#2275 6691069504): a queued job that no executor claims within 24 hours of
# being submitted expires. Measured from the persisted `created` (time.time(): seconds since the
# epoch, UTC by definition, so time zones and DST never move it).
QUEUED_MAX_AGE_S = 24 * 3600
EXPIRED_ERROR = "expired_unclaimed"
COMPLETED_ASSETS_MAX = 10_000  # the gallery index holds at most this many items (_MAX_INDEX_ITEMS)
_ASSET_ID_RE = re.compile(r"[A-Za-z0-9_-]{1,128}")

# Restart recovery's errors, as machine codes (#2275 6693665083). Rows written before the codes
# keep their sentences: nothing rewrites stored errors. public_error() maps both forms, so a route
# can expose codes only, and an older build that still writes sentences is mapped too.
INTERRUPTED_BY_RESTART = "interrupted_by_restart"
INTERRUPTED_DURING_PUBLICATION = "interrupted_during_publication"
LEGACY_ERRORS = {
    "interrupted by restart": INTERRUPTED_BY_RESTART,
    "interrupted during publication": INTERRUPTED_DURING_PUBLICATION,
}


def public_error(error: str | None) -> str | None:
    """The owner-visible code for a stored error: legacy sentences become their codes; None stays None."""
    return LEGACY_ERRORS.get(error, error) if error is not None else None
_EXPIRE_SQL = "UPDATE image_jobs SET state='expired',error=?,updated=? WHERE state='queued' AND created <= ?"


class ImageJobStore:
    def __init__(self, db_path: str, *, volume_guard: Callable[[], None] | None = None):
        self._volume_guard = volume_guard
        if self._volume_guard is not None:
            self._volume_guard()
        self.path = Path(db_path)
        if not self.path.parent.is_dir():
            raise ImageJobError("job database parent directory does not exist")
        with self._db() as db:
            # One write transaction spans creation, inspection and both migrations, so concurrent
            # initialisers (several executors, the worker) serialise instead of racing to ALTER
            # (#2318 review 4420958348).
            db.execute("BEGIN IMMEDIATE")
            db.execute("""CREATE TABLE IF NOT EXISTS image_jobs (
                id TEXT PRIMARY KEY, owner TEXT NOT NULL, prompt TEXT NOT NULL,
                profile_id TEXT NOT NULL, params TEXT NOT NULL,
                state TEXT NOT NULL, created REAL NOT NULL, updated REAL NOT NULL,
                asset_id TEXT, error TEXT)""")
            db.execute("CREATE INDEX IF NOT EXISTS image_jobs_state ON image_jobs(state, created)")
            db.execute("CREATE INDEX IF NOT EXISTS image_jobs_owner_asset_state "
                       "ON image_jobs(owner, asset_id, state)")
            columns = {row[1] for row in db.execute("PRAGMA table_info(image_jobs)")}
            if "claimed_by" not in columns:  # additive migration, no data rewritten
                db.execute("ALTER TABLE image_jobs ADD COLUMN claimed_by TEXT")
            if "cancel_requested" not in columns:
                db.execute("ALTER TABLE image_jobs ADD COLUMN cancel_requested INTEGER NOT NULL DEFAULT 0")
            if "deferred_since" not in columns:  # G4: when a job first had to wait for VRAM
                db.execute("ALTER TABLE image_jobs ADD COLUMN deferred_since REAL")
            # A database written before every connection had secure_delete on may hold old prompt
            # text in free space (a state update can move a row and free its old copy without
            # zeroing it). The first time this version opens it, a scrub is owed; purge_prompts
            # pays it with a VACUUM (#2340 review 4477941179).
            # Hand-off receipts (Anders, 6 Nov: generate on C:, publish on Z:): what a video job handed
            # from the work area to the volume, so C6 can correlate leftovers with jobs. Its own table:
            # SELECT * on image_jobs is unchanged, and a receipt never holds a prompt or parameters.
            db.execute("CREATE TABLE IF NOT EXISTS image_jobs_handoff (job_id TEXT PRIMARY KEY, "
                       "record TEXT NOT NULL, updated REAL NOT NULL)")
            if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='image_jobs_scrub'").fetchone() is None:
                db.execute("CREATE TABLE image_jobs_scrub (id INTEGER PRIMARY KEY CHECK (id = 1), "
                           "owed INTEGER NOT NULL)")
                db.execute("INSERT INTO image_jobs_scrub (id, owed) VALUES (1, 1)")

    @contextmanager
    def _db(self):
        if self._volume_guard is not None:
            self._volume_guard()
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout=10000")
        # On every connection, before any write: a state transition may move a row and free the
        # old copy of its prompt; with secure_delete off that copy stays readable in free space
        # and the later purge cannot reach it (#2340 review 4477941179). Fail closed if the
        # build ignores the pragma.
        row = connection.execute("PRAGMA secure_delete=ON").fetchone()
        if row is None or row[0] != 1:
            connection.close()
            raise ImageJobError("SQLite secure_delete is unavailable")
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def purge_prompts(self, *, older_than_s: float = PROMPT_RETENTION_S, now: float | None = None) -> int:
        """Blank the prompt of every finished job whose last update is older than older_than_s.
        Returns how many prompts were blanked. secure_delete (on for every connection, see _db)
        makes SQLite overwrite the old text in the database file instead of leaving it in freed
        space. Queued, running and publishing jobs keep their prompt: it is still needed.

        A purge that blanked anything also owes a scrub, and an owed scrub is paid here with a
        VACUUM, which rebuilds the file without any free space. With secure_delete on everywhere
        that is a second layer; for a database written before that, it is the only one."""
        if type(older_than_s) not in (int, float) or older_than_s < 0:
            raise ImageJobError("invalid retention")
        cutoff = (time.time() if now is None else now) - older_than_s
        with self._db() as db:
            purged = db.execute(
                f"UPDATE image_jobs SET prompt='' WHERE state IN ({','.join('?' * len(_FINISHED))}) "
                "AND updated < ? AND prompt != ''", (*_FINISHED, cutoff)).rowcount
            if purged:  # same transaction: a blanking is never committed without its scrub owed
                db.execute("UPDATE image_jobs_scrub SET owed = owed + 1 WHERE id = 1")
        self._scrub_if_owed()
        # In WAL mode the old pages live on in the -wal file until a checkpoint copies the
        # overwritten pages back; TRUNCATE also empties it. Run on every call, not only when
        # something was purged, so a checkpoint a reader blocked last time is retried.
        # (No-op in rollback-journal mode.)
        with self._db() as db:
            if str(db.execute("PRAGMA journal_mode").fetchone()[0]).lower() == "wal":
                db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        return purged

    def _scrub_if_owed(self) -> None:
        with self._db() as db:
            owed = db.execute("SELECT owed FROM image_jobs_scrub WHERE id = 1").fetchone()[0]
        if not owed:
            return
        with self._db() as db:
            # VACUUM builds the new file in SQLite's temp database first; keep that in memory so
            # no copy of the prompts is written to the system temp directory (the internal disk).
            db.execute("PRAGMA temp_store=MEMORY")
            db.execute("VACUUM")
        with self._db() as db:
            # Clear only what this scrub covered: a purge that committed meanwhile owes its own.
            db.execute("UPDATE image_jobs_scrub SET owed = 0 WHERE id = 1 AND owed = ?", (owed,))

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
            # Expired jobs never hold queue places, even while media is off and nothing claims.
            db.execute(_EXPIRE_SQL, (EXPIRED_ERROR, now, now - QUEUED_MAX_AGE_S))
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
        if row is not None and row["state"] == "queued" and row["created"] <= time.time() - QUEUED_MAX_AGE_S:
            # Media may be off and no executor running: the owner still sees the job expire.
            self.expire_queued()
            with self._db() as db:
                row = db.execute("SELECT * FROM image_jobs WHERE id=? AND owner=?", (job_id, owner)).fetchone()
        return dict(row) if row else None

    def expire_queued(self, *, max_age_s: float = QUEUED_MAX_AGE_S, now: float | None = None) -> int:
        """Expire every queued job submitted at least max_age_s ago: terminal state 'expired', error
        'expired_unclaimed'. Returns how many. Running and publishing jobs are never touched.

        The age is now - created, both from time.time(). A job whose `created` lies in the future
        (the clock was set back after it was submitted) is not old: it expires only once the clock
        has passed it by max_age_s, never early. A clock set forward makes jobs older at once;
        that is the wall clock's verdict, and only queued jobs are affected."""
        if type(max_age_s) not in (int, float) or not max_age_s > 0:
            raise ImageJobError("invalid queued job age")
        now = time.time() if now is None else now
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            return db.execute(_EXPIRE_SQL, (EXPIRED_ERROR, now, now - max_age_s)).rowcount

    def owns_completed_asset(self, owner: str, asset_id: str) -> bool:
        """Authorize only completed assets of the authenticated principal.

        The caller must supply owner from verified pairing/auth, never a
        client-controlled owner field. Unknown assets and other owners fail closed.
        """
        if (type(owner) is not str or not owner.strip() or len(owner) > 256
                or type(asset_id) is not str
                or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", asset_id)):
            return False
        with self._db() as db:
            return db.execute(
                "SELECT 1 FROM image_jobs WHERE owner=? AND asset_id=? "
                "AND state='completed' LIMIT 1", (owner, asset_id)
            ).fetchone() is not None

    def completed_assets_for(self, owner: str, *, limit: int = COMPLETED_ASSETS_MAX) -> frozenset[str]:
        """Every asset id the authenticated principal owns through a completed job, in one bounded
        read (#2275 6697074518: a gallery projection filters with this instead of one
        owns_completed_asset query per index entry). Same authority as owns_completed_asset: the
        caller supplies the owner from verified pairing/auth; failed, running, publishing, expired
        and other owners' jobs are never in it. More than `limit` assets is a refusal, never a
        partial set; a database error propagates, never reads as "owns nothing"."""
        if type(limit) is not int or not 1 <= limit <= COMPLETED_ASSETS_MAX:
            raise ImageJobError("invalid limit")
        if type(owner) is not str or not owner.strip() or len(owner) > 256:
            return frozenset()
        with self._db() as db:
            rows = db.execute(
                "SELECT DISTINCT asset_id FROM image_jobs WHERE owner=? AND state='completed' "
                "AND asset_id IS NOT NULL LIMIT ?", (owner, limit + 1)).fetchall()
        if len(rows) > limit:
            raise ImageJobError("owner_asset_limit")
        return frozenset(r[0] for r in rows if type(r[0]) is str and _ASSET_ID_RE.fullmatch(r[0]))

    def claim(self) -> dict | None:
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            now = time.time()
            # Like claim_for(): a stale queued job expires in this transaction and is never claimed.
            db.execute(_EXPIRE_SQL, (EXPIRED_ERROR, now, now - QUEUED_MAX_AGE_S))
            row = db.execute("SELECT * FROM image_jobs WHERE state='queued' ORDER BY created,id LIMIT 1").fetchone()
            if row is None:
                return None
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
                "UPDATE image_jobs SET state='failed',error=?,updated=? WHERE state='running'",
                (INTERRUPTED_BY_RESTART, time.time()))
            return result.rowcount

    # --- executor protocol (G2) ----------------------------------------------------------------
    @staticmethod
    def _instance(instance: object) -> str:
        if not isinstance(instance, str) or not _INSTANCE.fullmatch(instance):
            raise ImageJobError("invalid executor instance")
        return instance

    def claim_for(self, profile_ids, instance: str) -> dict | None:
        """The oldest queued job for one of these profiles, claimed by this executor instance. Jobs
        older than QUEUED_MAX_AGE_S are expired in the same transaction and never claimed, so an
        executor that starts after a long pause cannot run a job its owner has given up on."""
        instance = self._instance(instance)
        ids = sorted(set(profile_ids))
        if not ids or any(not isinstance(p, str) or not _PROFILE_ID.fullmatch(p) for p in ids):
            raise ImageJobError("invalid profile ids")
        marks = ",".join("?" * len(ids))
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            now = time.time()
            db.execute(_EXPIRE_SQL, (EXPIRED_ERROR, now, now - QUEUED_MAX_AGE_S))
            row = db.execute(f"SELECT * FROM image_jobs WHERE state='queued' AND profile_id IN ({marks}) "
                             "ORDER BY created,id LIMIT 1", ids).fetchone()
            if row is None:
                return None
            db.execute("UPDATE image_jobs SET state='running',claimed_by=?,updated=? WHERE id=? AND state='queued'",
                       (instance, now, row["id"]))
            return dict(row) | {"state": "running", "claimed_by": instance, "updated": now}

    def defer(self, job_id: str, instance: str, *, max_wait_s: float, error: str, now: float | None = None) -> str:
        """Put a running job back in the queue because the GPU lacks free memory right now (G4).

        Returns "requeued"; "expired" once it has waited max_wait_s since its first deferral (it is
        then failed with `error`); "cancelled" if its owner asked to cancel meanwhile (a requeued job
        would otherwise run despite the request); "gone" if this instance no longer holds it.
        """
        instance = self._instance(instance)
        if not isinstance(error, str) or not error or type(max_wait_s) not in (int, float) or max_wait_s < 0:
            raise ImageJobError("invalid deferral")
        now = time.time() if now is None else now
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT deferred_since, cancel_requested FROM image_jobs "
                             "WHERE id=? AND state='running' AND claimed_by=?", (job_id, instance)).fetchone()
            if row is None:
                return "gone"
            if row["cancel_requested"]:
                db.execute("UPDATE image_jobs SET state='cancelled',updated=? WHERE id=?", (now, job_id))
                return "cancelled"
            since = row["deferred_since"] if row["deferred_since"] is not None else now
            if now - since >= max_wait_s:
                db.execute("UPDATE image_jobs SET state='failed',error=?,updated=? WHERE id=?", (error, now, job_id))
                return "expired"
            db.execute("UPDATE image_jobs SET state='queued',claimed_by=NULL,deferred_since=?,updated=? WHERE id=?",
                       (since, now, job_id))
            return "requeued"

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
                "UPDATE image_jobs SET state='failed',error=?,updated=? "
                "WHERE state='running' AND substr(claimed_by,1,?)=? AND claimed_by<>?",
                (INTERRUPTED_BY_RESTART, now, len(prefix), prefix, instance)).rowcount
            publishing = db.execute(
                "UPDATE image_jobs SET state='failed',error=?,updated=? "
                "WHERE state='publishing' AND substr(claimed_by,1,?)=? AND claimed_by<>?",
                (INTERRUPTED_DURING_PUBLICATION, now, len(prefix), prefix, instance)).rowcount
            return running + publishing

    def request_cancel(self, job_id: str, owner: str) -> str | None:
        """'cancelled' (was queued), 'expired' (was queued for more than 24 hours: it expires now
        instead), 'requested' (running: the executor stops it), 'too_late' (publishing: it will
        complete), or None (not this owner's, or already finished)."""
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            now = time.time()
            # Expiry wins over cancel, as on every other path (#2357 review P3-3).
            if db.execute(_EXPIRE_SQL + " AND id=? AND owner=?",
                          (EXPIRED_ERROR, now, now - QUEUED_MAX_AGE_S, job_id, owner)).rowcount:
                return "expired"
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

    def record_handoff(self, job_id: str, instance: str, record: dict) -> bool:
        """Store the hand-off receipt of the executor's own running or publishing job (replaces the
        previous one). Only names, sizes, file ids, asset ids and hashes: never a prompt, an owner or
        parameters. Raises ImageJobError on anything else; False if the job is not this instance's."""
        checked = check_handoff_record(record)
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            if db.execute("SELECT 1 FROM image_jobs WHERE id=? AND state IN ('running','publishing') AND claimed_by=?",
                          (job_id, self._instance(instance))).fetchone() is None:
                return False
            db.execute("INSERT INTO image_jobs_handoff (job_id, record, updated) VALUES (?,?,?) "
                       "ON CONFLICT(job_id) DO UPDATE SET record=excluded.record, updated=excluded.updated",
                       (job_id, json.dumps(checked, sort_keys=True), time.time()))
            return True

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
