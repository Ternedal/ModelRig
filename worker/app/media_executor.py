"""The media-generation executor: one process per GPU (G2, ModelRig #2296).

Default-off and not wired anywhere: nothing imports this module, there is no
route, and no process is started for it. Design 6510332634; reviews
6511335742, 6512440682 and 6513576382 (ChatGPT) are covered by
tests/worker_media_executor.py.

Why a separate process: GpuResourcesRetained means "exit, so the OS frees the
VRAM and the GPU lease". The FastAPI worker must never be that process.

Rules
- One executor per GPU. start() takes <lease dir>/<UUID>.executor.lock
  (gpu_lease.acquire_executor_lock) BEFORE it recovers interrupted jobs; a
  duplicate exits 73 without touching any claim. Claims carry a per-process
  instance id ("<UUID>:<16 hex>"); every transition requires it.
- It claims only jobs for its own profiles (claim_for), one at a time.
- One resident adapter at a time. Switching profiles is a proven unload, then
  a load. Any unload failure (close() not True, or an exception) is fatal: the
  adapter stays referenced so its lease cannot be released before exit, the
  executor exits 70, and every later step() refuses to claim or load.
- Idle unload after idle_unload_s frees the GPU for processes outside the
  lease (Ollama, G4).
- Image: adapter.render() -> begin_publish() -> ArtifactSink.publish().
  Video: StagedFileArtifactSink.staged() -> adapter.render_to() ->
  begin_publish() -> adopt(); never a bytes fallback. begin_publish() is the
  commit point: a cancel committed before it wins and nothing is published;
  after it, request_cancel() answers "too_late" and the job completes.
- Cancellation of a running job is cooperative: should_cancel is polled by the
  adapters (ComfyUI poll loop; diffusers callback_on_step_end).
- ArtifactSinkUnavailable is fatal (exit 75): the job is left for recovery,
  no other disk is tried. Job errors are stored as fixed codes, never as
  exception text (it can contain prompts or paths).

Exit codes: 0 done, 70 GPU memory not proven free, 73 another executor holds
this GPU, 75 media volume unavailable, 78 configuration. A process supervisor
(next slice) maps them to restart policy: restart after 70, never loop on 73,
wait for the volume after 75, stop on 78.
"""
from __future__ import annotations

import json
import secrets
import time
from typing import Callable, Mapping

from .diffusers_image_adapter import GpuResourcesRetained
from .gpu_lease import ExecutorAlreadyRunning, GpuBusy, acquire_executor_lock, normalize_gpu_uuid
from .image_job_store import ImageJobStore
from .media_generation_contract import (ArtifactSink, ArtifactSinkUnavailable, GenerationCancelled, GenerationError,
                                        GenerationRequest, RenderedArtifact, StagedFileArtifactSink)
from .media_generation_profiles import ModelProfile, validate_request

EXIT_DONE, EXIT_GPU_RETAINED, EXIT_DUPLICATE, EXIT_SINK_UNAVAILABLE, EXIT_CONFIG = 0, 70, 73, 75, 78
FAILED = "generation_failed"
REJECTED = "generation_request_rejected"
GPU_RETAINED = "gpu_memory_retained"
GPU_BUSY = "gpu_busy"
_REQUEST_PARAMS = ("width", "height", "steps", "seed", "input_asset_id", "frames")


class ExecutorConfigError(RuntimeError):
    pass


class MediaExecutor:
    def __init__(self, store: ImageJobStore, *, gpu_uuid: str, lease_dir: str,
                 profiles: Mapping[str, ModelProfile], adapter_factory: Callable[[ModelProfile], object],
                 image_sink: ArtifactSink | None = None, video_sink: StagedFileArtifactSink | None = None,
                 idle_unload_s: float = 300.0, cancel_poll_s: float = 1.0,
                 clock: Callable[[], float] = time.monotonic):
        if not isinstance(store, ImageJobStore):
            raise ExecutorConfigError("store must be an ImageJobStore")
        if not profiles:
            raise ExecutorConfigError("no enabled profiles for this executor")
        for profile in profiles.values():
            if profile.modality == "video" and not isinstance(video_sink, StagedFileArtifactSink):
                raise ExecutorConfigError(f"{profile.profile_id}: video needs a StagedFileArtifactSink (no bytes fallback)")
            if profile.modality == "image" and not isinstance(image_sink, ArtifactSink):
                raise ExecutorConfigError(f"{profile.profile_id}: image needs an ArtifactSink")
        if type(idle_unload_s) not in (int, float) or not 1 <= idle_unload_s <= 86400:
            raise ExecutorConfigError("idle_unload_s must be 1..86400")
        if type(cancel_poll_s) not in (int, float) or not 0.05 <= cancel_poll_s <= 60:
            raise ExecutorConfigError("cancel_poll_s must be 0.05..60")
        self.store = store
        self.gpu_uuid = normalize_gpu_uuid(gpu_uuid)
        self.lease_dir = lease_dir
        self.profiles = dict(profiles)
        self.adapter_factory, self.image_sink, self.video_sink = adapter_factory, image_sink, video_sink
        self.idle_unload_s, self.cancel_poll_s, self.clock = float(idle_unload_s), float(cancel_poll_s), clock
        self.instance = f"{self.gpu_uuid}:{secrets.token_hex(8)}"
        self.adapter = None
        self.last_used = clock()
        self._lock = None
        self._retained: list = []  # adapters whose unload failed: kept alive (lease held) until exit
        self.events: list[str] = []  # lifecycle record for logs and tests; never prompt text

    # --- lifecycle --------------------------------------------------------------------------------
    def start(self) -> int:
        """Prove that no other executor for this GPU is alive, THEN recover its interrupted jobs."""
        if self._lock is not None:
            raise ExecutorConfigError("already started")
        self._lock = acquire_executor_lock(self.gpu_uuid, lease_dir=self.lease_dir)  # ExecutorAlreadyRunning
        recovered = self.store.recover_gpu(self.gpu_uuid, self.instance)
        self.events.append(f"recovered:{recovered}")
        return recovered

    def _unload(self) -> None:
        adapter, self.adapter = self.adapter, None
        try:
            ok = adapter.close() is True
        except Exception:
            ok = False
        self.events.append(f"closed:{adapter.profile_id}:{ok}")
        if not ok:
            self._retained.append(adapter)
            raise GpuResourcesRetained("GPU memory not proven free after unload; the executor must exit")

    def _adapter_for(self, profile: ModelProfile):
        if self.adapter is not None and self.adapter.profile_id != profile.profile_id:
            self._unload()  # one resident model per GPU: a switch is a proven unload, then a load
        if self.adapter is None:
            adapter = self.adapter_factory(profile)
            adapter.load()  # GpuResourcesRetained -> exit 70; GpuBusy -> this job fails "gpu_busy"
            self.adapter = adapter
            self.events.append(f"loaded:{profile.profile_id}")
        return self.adapter

    def maybe_unload_idle(self) -> None:
        if self.adapter is not None and self.clock() - self.last_used >= self.idle_unload_s:
            self._unload()

    def shutdown(self) -> None:
        if self.adapter is not None:
            self._unload()

    # --- one job ------------------------------------------------------------------------------------
    def _request(self, job: dict, profile: ModelProfile) -> GenerationRequest:
        params = json.loads(job["params"])
        if not isinstance(params, dict) or set(params) - set(_REQUEST_PARAMS) - {"task"}:
            raise GenerationError("unknown job parameters")
        task = params.get("task", sorted(profile.tasks)[0])
        return validate_request(profile, GenerationRequest(
            profile_id=profile.profile_id, task=task, prompt=job["prompt"],
            **{key: params[key] for key in _REQUEST_PARAMS if key in params}))

    def _cancel_check(self, job_id: str) -> Callable[[], bool]:
        state = {"next": float("-inf"), "hit": False}

        def should_cancel() -> bool:
            now = self.clock()
            if not state["hit"] and now >= state["next"]:
                state["next"] = now + self.cancel_poll_s
                state["hit"] = self.store.cancel_requested(job_id, self.instance)
            return state["hit"]
        return should_cancel

    def step(self) -> str:
        """Claim and run at most one job. Returns idle, completed, failed, rejected or cancelled."""
        if self._lock is None:
            raise ExecutorConfigError("start() first: no claims without the executor lock")
        if self._retained:
            raise GpuResourcesRetained("an earlier unload failed; this executor must exit")
        job = self.store.claim_for(self.profiles, self.instance)
        if job is None:
            self.maybe_unload_idle()
            return "idle"
        job_id, profile = job["id"], self.profiles[job["profile_id"]]
        try:
            request = self._request(job, profile)
        except (GenerationError, ValueError, TypeError, KeyError):
            self.store.fail(job_id, self.instance, REJECTED)
            return "rejected"
        try:
            adapter = self._adapter_for(profile)
            should_cancel = self._cancel_check(job_id)
            if profile.modality == "video":
                with self.video_sink.staged(".mp4") as out:
                    mime = adapter.render_to(request, out, should_cancel=should_cancel)
                    if not self.store.begin_publish(job_id, self.instance):
                        raise GenerationCancelled("cancelled before publication")  # staged file is removed
                    asset_id = self.video_sink.adopt(out, mime)
            else:
                rendered = adapter.render(request, should_cancel=should_cancel)
                if not isinstance(rendered, RenderedArtifact) or rendered.mime_type not in profile.outputs:
                    raise GenerationError("adapter output does not match the profile")
                if not self.store.begin_publish(job_id, self.instance):
                    raise GenerationCancelled("cancelled before publication")
                asset_id = self.image_sink.publish(rendered.data, rendered.extension)
            self.last_used = self.clock()
            if not self.store.complete(job_id, self.instance, asset_id):
                # Only an external writer can cause this while the executor lock is held.
                raise RuntimeError("completion transition rejected; asset kept for reconciliation")
            return "completed"
        except ArtifactSinkUnavailable:
            raise  # left running/publishing; recover_gpu() fails it at the next start; no other disk
        except GpuResourcesRetained:
            self.store.fail(job_id, self.instance, GPU_RETAINED)
            raise
        except GenerationCancelled:
            self.last_used = self.clock()
            self.store.finish_cancelled(job_id, self.instance)
            return "cancelled"
        except GpuBusy:
            self.store.fail(job_id, self.instance, GPU_BUSY)
            return "failed"
        except Exception:
            self.last_used = self.clock()
            self.store.fail(job_id, self.instance, FAILED)  # never persist exception text
            return "failed"

    def run(self, *, max_steps: int | None = None, idle_sleep: Callable[[], None] = lambda: time.sleep(1.0)) -> int:
        """The executor's main loop; returns the process exit code."""
        try:
            self.start()
            steps = 0
            while max_steps is None or steps < max_steps:
                steps += 1
                if self.step() == "idle":
                    idle_sleep()
            self.shutdown()
            return EXIT_DONE
        except ExecutorAlreadyRunning:
            return EXIT_DUPLICATE
        except GpuResourcesRetained:
            return EXIT_GPU_RETAINED
        except ArtifactSinkUnavailable:
            return EXIT_SINK_UNAVAILABLE
        except ExecutorConfigError:
            return EXIT_CONFIG
