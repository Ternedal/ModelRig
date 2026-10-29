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

import time
from typing import Callable, Mapping

from app.diffusers_image_adapter import GpuResourcesRetained
from app.image_job_store import ImageJobStore
from app.media_generation_contract import (ArtifactSink, ArtifactSinkUnavailable, GenerationError,
                                           GenerationRequest, RenderedArtifact, StagedFileArtifactSink)
from app.media_generation_profiles import ModelProfile, validate_request
import json

EXIT_IDLE, EXIT_GPU_RETAINED, EXIT_SINK_UNAVAILABLE, EXIT_CONFIG = 0, 70, 75, 78
FAILED, REJECTED, GPU_RETAINED = "generation_failed", "generation_request_rejected", "gpu_memory_retained"
_REQUEST_PARAMS = ("width", "height", "steps", "seed", "input_asset_id", "frames")


class ExecutorConfigError(RuntimeError):
    pass


class Cancelled(GenerationError):
    pass


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

    def recover_claimed_by(self, claimed_by: str) -> int:
        """Startup only: fail THIS executor's interrupted jobs; other executors' running jobs are untouched."""
        with self._db() as db:
            return db.execute("UPDATE image_jobs SET state='failed',error='interrupted by restart',updated=? "
                              "WHERE state='running' AND claimed_by=?", (time.time(), claimed_by)).rowcount

    def request_cancel(self, job_id: str, owner: str) -> str | None:
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            if db.execute("UPDATE image_jobs SET state='cancelled',updated=? WHERE id=? AND owner=? AND state='queued'",
                          (time.time(), job_id, owner)).rowcount:
                return "cancelled"
            if db.execute("UPDATE image_jobs SET cancel_requested=1,updated=? WHERE id=? AND owner=? AND state='running'",
                          (time.time(), job_id, owner)).rowcount:
                return "requested"
            return None

    def cancel_requested(self, job_id: str) -> bool:
        with self._db() as db:
            row = db.execute("SELECT cancel_requested FROM image_jobs WHERE id=? AND state='running'", (job_id,)).fetchone()
            return bool(row and row[0])

    def finish_cancelled(self, job_id: str) -> bool:
        with self._db() as db:
            return db.execute("UPDATE image_jobs SET state='cancelled',updated=? WHERE id=? AND state='running'",
                              (time.time(), job_id)).rowcount == 1


class MediaExecutor:
    def __init__(self, store: GenerationJobStore, *, executor_id: str, profiles: Mapping[str, ModelProfile],
                 adapter_factory: Callable[[ModelProfile], object], image_sink: ArtifactSink | None = None,
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
        self.adapter_factory, self.image_sink, self.video_sink = adapter_factory, image_sink, video_sink
        self.idle_unload_s, self.cancel_poll_s, self.clock = idle_unload_s, cancel_poll_s, clock
        self.adapter = None
        self.last_used = clock()
        self.events: list[str] = []  # observable lifecycle for tests and logs (never prompt text)

    # --- lifecycle --------------------------------------------------------------------------------
    def start(self) -> int:
        recovered = self.store.recover_claimed_by(self.executor_id)
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
        job = self.store.claim_for(self.profiles, self.executor_id)
        if job is None:
            self.maybe_unload_idle()
            return "idle"
        job_id, profile = job["id"], self.profiles[job["profile_id"]]
        try:
            request = self._request(job, profile)
        except (GenerationError, ValueError, TypeError):
            self.store.finish(job_id, error=REJECTED)
            return "rejected"
        try:
            adapter = self._adapter_for(profile)
            should_cancel = self._cancel_check(job_id)
            if profile.modality == "video":
                with self.video_sink.staged(".mp4") as out:
                    mime = adapter.render_to(request, out, should_cancel=should_cancel)
                    asset_id = self.video_sink.adopt(out, mime)
            else:
                if should_cancel():
                    raise Cancelled("cancelled before rendering")
                rendered = adapter.render(request)
                if not isinstance(rendered, RenderedArtifact) or rendered.mime_type not in profile.outputs:
                    raise GenerationError("adapter output does not match the profile")
                asset_id = self.image_sink.publish(rendered.data, rendered.extension)
            self.last_used = self.clock()
            if not self.store.finish(job_id, asset_id=asset_id):
                raise RuntimeError("completion transition rejected; asset kept for reconciliation")
            return "completed"
        except ArtifactSinkUnavailable:
            raise  # job left running; recover_claimed_by() fails it at the next start; no other disk
        except GpuResourcesRetained:
            self.store.finish(job_id, error=GPU_RETAINED)
            raise
        except Cancelled:
            self.last_used = self.clock()
            self.store.finish_cancelled(job_id)
            return "cancelled"
        except Exception:
            self.last_used = self.clock()
            self.store.finish(job_id, error=FAILED)  # never persist exception text
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
        except GpuResourcesRetained:
            return EXIT_GPU_RETAINED  # exit now: the OS frees the memory and the lease with the process
        except ArtifactSinkUnavailable:
            return EXIT_SINK_UNAVAILABLE  # supervisor: no restart until the volume verifies again
