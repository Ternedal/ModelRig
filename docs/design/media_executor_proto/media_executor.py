"""PROTOTYPE (G2 design evidence, #2296): the media-generation executor process.

Not part of any PR. Proves the lifecycle rules of the design against fakes:
one executor per GPU, one resident adapter at a time, claims scoped to this
executor's profiles and recorded as its own, restart recovery of only its own
jobs, image -> ArtifactSink.publish, video -> StagedFileArtifactSink
staged/adopt (no bytes fallback), cancellation of queued and running jobs,
idle unload, and the two fatal exits (GPU memory not provably free: exit 70;
media volume missing: exit 75), which a process supervisor turns into
restart policy.
"""
from __future__ import annotations

import os
import secrets
import time
from typing import Callable, Mapping

from app.diffusers_image_adapter import GpuResourcesRetained
from app.image_job_store import ImageJobStore
from app.media_generation_contract import (ArtifactSink, ArtifactSinkUnavailable, GenerationError,
                                           GenerationRequest, RenderedArtifact, StagedFileArtifactSink)
from app.media_generation_profiles import ModelProfile, validate_request
import json

EXIT_IDLE, EXIT_GPU_RETAINED, EXIT_DUPLICATE, EXIT_SINK_UNAVAILABLE, EXIT_CONFIG = 0, 70, 73, 75, 78
EXECUTOR_SUFFIX = ".executor.lock"
FAILED, REJECTED, GPU_RETAINED = "generation_failed", "generation_request_rejected", "gpu_memory_retained"
_REQUEST_PARAMS = ("width", "height", "steps", "seed", "input_asset_id", "frames")


class ExecutorConfigError(RuntimeError):
    pass


class Cancelled(GenerationError):
    pass


class ExecutorAlreadyRunning(RuntimeError):
    """Another live executor holds this GPU's executor lock: a duplicate must not recover or claim."""


def acquire_executor_lock(gpu_uuid: str, lease_dir: str) -> int:
    """Process-lifetime lock <lease dir>/<UUID>.executor.lock, taken BEFORE recovery (#2296 6511335742).

    The OS releases it when the process exits or is killed, so holding it proves that
    no other executor for this GPU is alive. Returns the fd; it is never closed.
    """
    from app.gpu_lease import _check_lease_dir, _open_lock_file, _try_lock, normalize_gpu_uuid
    path = _check_lease_dir(lease_dir) / f"{normalize_gpu_uuid(gpu_uuid)}{EXECUTOR_SUFFIX}"
    fd = _open_lock_file(path)
    try:
        _try_lock(fd)
    except OSError:
        os.close(fd)
        raise ExecutorAlreadyRunning(f"an executor for {gpu_uuid} is already running") from None
    return fd


class GenerationJobStore(ImageJobStore):
    """ImageJobStore plus what more than one executor needs (additive migration, no data loss)."""

    def __init__(self, db_path: str, **kwargs):
        super().__init__(db_path, **kwargs)
        with self._db() as db:
            columns = {row[1] for row in db.execute("PRAGMA table_info(image_jobs)")}
            if "claimed_by" not in columns:
                db.execute("ALTER TABLE image_jobs ADD COLUMN claimed_by TEXT")
            if "cancel_requested" not in columns:
                db.execute("ALTER TABLE image_jobs ADD COLUMN cancel_requested INTEGER NOT NULL DEFAULT 0")

    def claim_for(self, profile_ids, claimed_by: str) -> dict | None:
        ids = sorted(profile_ids)
        if not ids:
            return None
        marks = ",".join("?" * len(ids))
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(f"SELECT * FROM image_jobs WHERE state='queued' AND profile_id IN ({marks}) "
                             "ORDER BY created,id LIMIT 1", ids).fetchone()
            if row is None:
                return None
            now = time.time()
            db.execute("UPDATE image_jobs SET state='running',claimed_by=?,updated=? WHERE id=? AND state='queued'",
                       (claimed_by, now, row["id"]))
            return dict(row) | {"state": "running", "claimed_by": claimed_by, "updated": now}

    def recover_gpu(self, gpu_uuid: str, current_instance: str) -> int:
        """Startup only, and only while holding this GPU's executor lock: every claim for this GPU
        by another (now provably dead) instance is failed. Other GPUs' jobs are untouched."""
        now, pattern = time.time(), f"{gpu_uuid}:%"
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            running = db.execute("UPDATE image_jobs SET state='failed',error='interrupted by restart',updated=? "
                                 "WHERE state='running' AND claimed_by LIKE ? AND claimed_by<>?",
                                 (now, pattern, current_instance)).rowcount
            publishing = db.execute("UPDATE image_jobs SET state='failed',error='interrupted during publication',"
                                    "updated=? WHERE state='publishing' AND claimed_by LIKE ? AND claimed_by<>?",
                                    (now, pattern, current_instance)).rowcount
            return running + publishing

    def begin_publish(self, job_id: str, instance: str) -> bool:
        """The commit point between cancellation and publication: one transaction decides.

        running -> publishing only if no cancel was requested. Afterwards request_cancel()
        answers "too_late" and the job completes. Nothing is published before this succeeds.
        """
        with self._db() as db:
            return db.execute("UPDATE image_jobs SET state='publishing',updated=? WHERE id=? AND state='running' "
                              "AND claimed_by=? AND cancel_requested=0", (time.time(), job_id, instance)).rowcount == 1

    def complete(self, job_id: str, instance: str, asset_id: str) -> bool:
        with self._db() as db:
            return db.execute("UPDATE image_jobs SET state='completed',asset_id=?,updated=? WHERE id=? "
                              "AND state='publishing' AND claimed_by=?", (asset_id, time.time(), job_id, instance)).rowcount == 1

    def fail(self, job_id: str, instance: str, error: str) -> bool:
        with self._db() as db:
            return db.execute("UPDATE image_jobs SET state='failed',error=?,updated=? WHERE id=? "
                              "AND state IN ('running','publishing') AND claimed_by=?",
                              (error, time.time(), job_id, instance)).rowcount == 1

    def request_cancel(self, job_id: str, owner: str) -> str | None:
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            if db.execute("UPDATE image_jobs SET state='cancelled',updated=? WHERE id=? AND owner=? AND state='queued'",
                          (time.time(), job_id, owner)).rowcount:
                return "cancelled"
            if db.execute("UPDATE image_jobs SET cancel_requested=1,updated=? WHERE id=? AND owner=? AND state='running'",
                          (time.time(), job_id, owner)).rowcount:
                return "requested"
            if db.execute("SELECT 1 FROM image_jobs WHERE id=? AND owner=? AND state='publishing'",
                          (job_id, owner)).fetchone():
                return "too_late"  # past the commit point: it will complete
            return None

    def cancel_requested(self, job_id: str) -> bool:
        with self._db() as db:
            row = db.execute("SELECT cancel_requested FROM image_jobs WHERE id=? AND state='running'", (job_id,)).fetchone()
            return bool(row and row[0])

    def finish_cancelled(self, job_id: str, instance: str) -> bool:
        with self._db() as db:
            return db.execute("UPDATE image_jobs SET state='cancelled',updated=? WHERE id=? AND state='running' "
                              "AND claimed_by=?", (time.time(), job_id, instance)).rowcount == 1


class MediaExecutor:
    def __init__(self, store: GenerationJobStore, *, executor_id: str, profiles: Mapping[str, ModelProfile],
                 adapter_factory: Callable[[ModelProfile], object], lease_dir: str,
                 image_sink: ArtifactSink | None = None,
                 video_sink: StagedFileArtifactSink | None = None, idle_unload_s: float = 300.0,
                 cancel_poll_s: float = 1.0, clock: Callable[[], float] = time.monotonic):
        if not profiles:
            raise ExecutorConfigError("no enabled profiles for this executor")
        for profile in profiles.values():
            if profile.modality == "video" and not isinstance(video_sink, StagedFileArtifactSink):
                raise ExecutorConfigError(f"{profile.profile_id}: video needs a StagedFileArtifactSink (no bytes fallback)")
            if profile.modality == "image" and not isinstance(image_sink, ArtifactSink):
                raise ExecutorConfigError(f"{profile.profile_id}: image needs an ArtifactSink")
        self.store, self.executor_id, self.profiles = store, executor_id, dict(profiles)
        self.lease_dir = lease_dir
        self.instance = f"{executor_id}:{secrets.token_hex(8)}"  # claim generation: this process only
        self._lifetime_fd: int | None = None
        self.adapter_factory, self.image_sink, self.video_sink = adapter_factory, image_sink, video_sink
        self.idle_unload_s, self.cancel_poll_s, self.clock = idle_unload_s, cancel_poll_s, clock
        self.adapter = None
        self.last_used = clock()
        self.events: list[str] = []  # observable lifecycle for tests and logs (never prompt text)

    # --- lifecycle --------------------------------------------------------------------------------
    def start(self) -> int:
        # Prove that no other executor for this GPU is alive BEFORE touching any claim.
        self._lifetime_fd = acquire_executor_lock(self.executor_id, self.lease_dir)
        recovered = self.store.recover_gpu(self.executor_id, self.instance)
        self.events.append(f"recovered:{recovered}")
        return recovered

    def _unload(self) -> None:
        adapter, self.adapter = self.adapter, None
        ok = adapter.close()
        self.events.append(f"closed:{adapter.profile_id}:{ok}")
        if not ok:
            raise GpuResourcesRetained("GPU memory not proven free after unload; the executor must exit")

    def _adapter_for(self, profile: ModelProfile):
        if self.adapter is not None and self.adapter.profile_id != profile.profile_id:
            self._unload()  # one resident model per GPU: switch = proven unload, then load
        if self.adapter is None:
            adapter = self.adapter_factory(profile)
            adapter.load()  # GpuResourcesRetained propagates: exit 70
            self.adapter = adapter
            self.events.append(f"loaded:{profile.profile_id}")
        return self.adapter

    def maybe_unload_idle(self) -> None:
        if self.adapter is not None and self.clock() - self.last_used >= self.idle_unload_s:
            self._unload()  # frees VRAM for Ollama and others outside the lease

    # --- one job ------------------------------------------------------------------------------------
    def _request(self, job: dict, profile: ModelProfile) -> GenerationRequest:
        params = json.loads(job["params"])
        if not isinstance(params, dict) or set(params) - set(_REQUEST_PARAMS) - {"task"}:
            raise GenerationError("unknown job parameters")
        task = params.get("task", sorted(profile.tasks)[0])
        return validate_request(profile, GenerationRequest(profile_id=profile.profile_id, task=task, prompt=job["prompt"],
                                                           **{k: params[k] for k in _REQUEST_PARAMS if k in params}))

    def _cancel_check(self, job_id: str) -> Callable[[], bool]:
        state = {"next": 0.0, "hit": False}

        def should_cancel() -> bool:
            now = self.clock()
            if not state["hit"] and now >= state["next"]:
                state["next"] = now + self.cancel_poll_s
                state["hit"] = self.store.cancel_requested(job_id)
            return state["hit"]
        return should_cancel

    def step(self) -> str:
        if self._lifetime_fd is None:
            raise ExecutorConfigError("start() first: no claims without the executor lock")
        job = self.store.claim_for(self.profiles, self.instance)
        if job is None:
            self.maybe_unload_idle()
            return "idle"
        job_id, profile = job["id"], self.profiles[job["profile_id"]]
        try:
            request = self._request(job, profile)
        except (GenerationError, ValueError, TypeError):
            self.store.fail(job_id, self.instance, REJECTED)
            return "rejected"
        try:
            adapter = self._adapter_for(profile)
            should_cancel = self._cancel_check(job_id)
            if profile.modality == "video":
                with self.video_sink.staged(".mp4") as out:
                    mime = adapter.render_to(request, out, should_cancel=should_cancel)
                    if not self.store.begin_publish(job_id, self.instance):
                        raise Cancelled("cancelled before publication")  # staged file removed, nothing adopted
                    asset_id = self.video_sink.adopt(out, mime)
            else:
                if should_cancel():
                    raise Cancelled("cancelled before rendering")
                rendered = adapter.render(request)
                if not isinstance(rendered, RenderedArtifact) or rendered.mime_type not in profile.outputs:
                    raise GenerationError("adapter output does not match the profile")
                if not self.store.begin_publish(job_id, self.instance):
                    raise Cancelled("cancelled before publication")
                asset_id = self.image_sink.publish(rendered.data, rendered.extension)
            self.last_used = self.clock()
            if not self.store.complete(job_id, self.instance, asset_id):
                # Only an external writer can cause this while the executor lock is held.
                raise RuntimeError("completion transition rejected; asset kept for reconciliation")
            return "completed"
        except ArtifactSinkUnavailable:
            raise  # job left running/publishing; recover_gpu() fails it at the next start; no other disk
        except GpuResourcesRetained:
            self.store.fail(job_id, self.instance, GPU_RETAINED)
            raise
        except Cancelled:
            self.last_used = self.clock()
            self.store.finish_cancelled(job_id, self.instance)
            return "cancelled"
        except Exception:
            self.last_used = self.clock()
            self.store.fail(job_id, self.instance, FAILED)  # never persist exception text
            return "failed"

    def run(self, *, max_steps: int | None = None, idle_sleep: Callable[[], None] = lambda: time.sleep(1.0)) -> int:
        try:
            self.start()
            steps = 0
            while max_steps is None or steps < max_steps:
                steps += 1
                if self.step() == "idle":
                    idle_sleep()
            if self.adapter is not None:
                self._unload()
            return EXIT_IDLE
        except ExecutorAlreadyRunning:
            return EXIT_DUPLICATE  # supervisor: a duplicate; never restart it in a loop
        except GpuResourcesRetained:
            return EXIT_GPU_RETAINED  # exit now: the OS frees the memory and the lease with the process
        except ArtifactSinkUnavailable:
            return EXIT_SINK_UNAVAILABLE  # supervisor: no restart until the volume verifies again
