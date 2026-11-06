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
- A failed load is only survivable if close() then proves the release (True);
  otherwise the adapter is retained and the executor exits 70 (#2318 6623359226).
  A GpuResourcesRetained from load() is always fatal.
- Publication is job-keyed whenever the sink offers it (JobKeyedArtifactSink,
  JobKeyedStagedSink), so an artifact can be correlated with its job after a crash.
  If the completion write then fails, the job stays "publishing" (never
  "generation_failed") and the executor exits 76; recovery turns it into
  "interrupted during publication" for the sink owner's reconciliation.
- An adapter that reports needs_restart (a ComfyUI whose interrupt did not drain) is
  unloaded after the job, with the same proof rule, before anything else is claimed.
- The executor lock is released on every terminal path of run(). The GPU lease of
  a retained adapter is not: it stays held until the process exits.
- Bookkeeping writes on the fatal paths are best-effort: a failing database never
  replaces the fatal exit (#2318 6516453287).

Exit codes: 0 done, 70 GPU memory not proven free, 73 another executor holds
this GPU, 75 media volume unavailable, 76 publication not recorded (reconcile),
78 configuration. A process supervisor (next slice) maps them to restart policy:
restart after 70 and 76, never loop on 73, wait for the volume after 75, stop on 78.
"""
from __future__ import annotations

import contextlib
import json
import secrets
import time
from typing import Callable, Mapping

from .comfy_supervisor import ComfyVramShortage
from .diffusers_image_adapter import GpuResourcesRetained
from .gpu_lease import ExecutorAlreadyRunning, GpuBusy, acquire_executor_lock, normalize_gpu_uuid
from .image_gpu_admission import GpuMemoryShortage
from .image_job_store import ImageJobStore
from .media_generation_contract import (ArtifactSink, ArtifactSinkUnavailable, GenerationCancelled, GenerationError,
                                        GenerationRequest, JobKeyedArtifactSink, JobKeyedStagedSink,
                                        RenderedArtifact, SourceImageUnavailable, StagedFileArtifactSink)
from .media_generation_profiles import ModelProfile, validate_request

EXIT_DONE, EXIT_GPU_RETAINED, EXIT_DUPLICATE, EXIT_SINK_UNAVAILABLE, EXIT_UNRECORDED, EXIT_CONFIG = 0, 70, 73, 75, 76, 78
FAILED = "generation_failed"
PUBLICATION_FAILED = "publication_failed"
REJECTED = "generation_request_rejected"
GPU_RETAINED = "gpu_memory_retained"
GPU_BUSY = "gpu_busy"
GPU_UNAVAILABLE = "gpu_unavailable"  # VRAM stayed taken (by Ollama, typically) for VRAM_MAX_WAIT_S
# G4, Anders 5 Nov 2026: chat first, media waits. Too little free VRAM puts the job back in the
# queue; the executor claims again after VRAM_RETRY_S; after VRAM_MAX_WAIT_S of waiting it fails.
# Ollama is never touched.
VRAM_RETRY_S = 30.0
VRAM_MAX_WAIT_S = 600.0
_VRAM_SHORTAGE = (GpuMemoryShortage, ComfyVramShortage)
SOURCE_UNAVAILABLE = "source_image_unavailable"  # the job's source image: absent, invalid or not the owner's
_REQUEST_PARAMS = ("width", "height", "steps", "seed", "input_asset_id", "frames")
PURGE_INTERVAL_S = 3600.0  # prompt retention runs at start, then at most hourly while idle


class ExecutorConfigError(RuntimeError):
    pass


class PublicationUnrecorded(RuntimeError):
    """The artifact is durable but its completion could not be recorded; the job stays publishing."""


class MediaExecutor:
    def __init__(self, store: ImageJobStore, *, gpu_uuid: str, lease_dir: str,
                 profiles: Mapping[str, ModelProfile], adapter_factory: Callable[[ModelProfile], object],
                 image_sink: ArtifactSink | None = None, video_sink: StagedFileArtifactSink | None = None,
                 idle_unload_s: float = 300.0, cancel_poll_s: float = 1.0,
                 source_reader: Callable[[str, str], bytes] | None = None,
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
            if "image_to_video" in profile.tasks and source_reader is None:
                raise ExecutorConfigError(f"{profile.profile_id}: image_to_video needs the owner-gated source reader")
        if type(idle_unload_s) not in (int, float) or not 1 <= idle_unload_s <= 86400:
            raise ExecutorConfigError("idle_unload_s must be 1..86400")
        if type(cancel_poll_s) not in (int, float) or not 0.05 <= cancel_poll_s <= 60:
            raise ExecutorConfigError("cancel_poll_s must be 0.05..60")
        self.store = store
        self.gpu_uuid = normalize_gpu_uuid(gpu_uuid)
        self.lease_dir = lease_dir
        self.profiles = dict(profiles)
        self.adapter_factory, self.image_sink, self.video_sink = adapter_factory, image_sink, video_sink
        # source_reader(owner, asset_id) -> PNG bytes. In production ChatGPT's read_owned_source_png:
        # it authorizes the owner before any gallery I/O (#2296 6651187815).
        self.source_reader = source_reader
        self.idle_unload_s, self.cancel_poll_s, self.clock = float(idle_unload_s), float(cancel_poll_s), clock
        self.instance = f"{self.gpu_uuid}:{secrets.token_hex(8)}"
        self.adapter = None
        self.last_used = clock()
        self._claim_not_before = float("-inf")  # after a VRAM shortage: no claims until then
        self._next_purge = clock()
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
        self.purge_prompts()
        return recovered

    def purge_prompts(self) -> None:
        """Prompt retention (PROMPT_RETENTION_S), at start and then at most once an hour while
        idle. Best effort: a failure is recorded and retried later, never fatal to the GPU work."""
        self._next_purge = self.clock() + PURGE_INTERVAL_S
        try:
            self.events.append(f"purged:{self.store.purge_prompts()}")
        except Exception as exc:
            self.events.append(f"purge_failed:{type(exc).__name__}")

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
            try:
                adapter.load()
            except GpuResourcesRetained:
                self._retained.append(adapter)  # the adapter says its memory is not free: always fatal
                raise
            except BaseException as exc:
                # A partial load may hold the GPU (memory, a started ComfyUI). Continue only if
                # close() proves the release; otherwise keep it referenced and exit 70.
                try:
                    released = adapter.close() is True
                except Exception:
                    released = False
                self.events.append(f"failed_load:{profile.profile_id}:{released}")
                if not released:
                    self._retained.append(adapter)
                    raise GpuResourcesRetained("a failed load did not prove its release; the executor must exit") from exc
                raise  # released: GpuBusy -> "gpu_busy", anything else -> "generation_failed"
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
        """Claim and run at most one job. Returns idle, completed, failed, rejected, cancelled or
        deferred (put back in the queue: too little free VRAM right now, G4)."""
        if self._lock is None:
            raise ExecutorConfigError("start() first: no claims without the executor lock")
        if self._retained:
            raise GpuResourcesRetained("an earlier unload failed; this executor must exit")
        if self.clock() < self._claim_not_before:  # waiting for VRAM: claim nothing yet
            self.maybe_unload_idle()
            return "idle"
        job = self.store.claim_for(self.profiles, self.instance)
        if job is None:
            self.maybe_unload_idle()
            return "idle"
        outcome = self._run_job(job)
        if self.adapter is not None and getattr(self.adapter, "needs_restart", False):
            # e.g. a cancelled ComfyUI whose queue did not drain: never give it another job.
            self.events.append(f"restart:{self.adapter.profile_id}")
            self._unload()  # close() must prove the release, otherwise this is fatal (exit 70)
        return outcome

    def _run_job(self, job: dict) -> str:
        job_id, profile = job["id"], self.profiles[job["profile_id"]]
        try:
            request = self._request(job, profile)
        except (GenerationError, ValueError, TypeError, KeyError):
            self.store.fail(job_id, self.instance, REJECTED)
            return "rejected"
        source_png = None
        if request.task == "image_to_video":
            # Before any GPU work. The owner is the claimed row's, which the routes took from the
            # authenticated pairing -- never from request parameters. An asset-level refusal fails
            # this job only; ArtifactSinkUnavailable (the volume) propagates: exit 75, job recovered.
            try:
                source_png = self.source_reader(job["owner"], request.input_asset_id)
            except SourceImageUnavailable:
                # Recording it is a store access, and the production store checks the media volume
                # first (G2b): a volume lost mid-read (EIO) becomes exit 75 here, never a blamed
                # asset -- deliberately store.fail, not the swallowing _record_failure (#2339 P3).
                self.store.fail(job_id, self.instance, SOURCE_UNAVAILABLE)
                return "failed"
            except ValueError:
                self.store.fail(job_id, self.instance, REJECTED)
                return "rejected"
            if type(source_png) is not bytes or not source_png:
                self.store.fail(job_id, self.instance, SOURCE_UNAVAILABLE)
                return "failed"
        publishing = False
        try:
            adapter = self._adapter_for(profile)
            should_cancel = self._cancel_check(job_id)
            if profile.modality == "video":
                # Anders, 6 Nov 2026: publish on the volume, THEN remove the adapter's copy in the work
                # area. The hold ends after the staged context: on success the file is published
                # first; if publication fails, the copy is kept for recovery (C6 lists it).
                hold = getattr(adapter, "holding_outputs", None)
                with hold() if callable(hold) else contextlib.nullcontext():
                    with self.video_sink.staged(".mp4") as out:
                        if source_png is not None:
                            mime = adapter.render_to(request, out, should_cancel=should_cancel, source_png=source_png)
                        else:
                            mime = adapter.render_to(request, out, should_cancel=should_cancel)
                        if not self.store.begin_publish(job_id, self.instance):
                            raise GenerationCancelled("cancelled before publication")  # staged file is removed
                        publishing = True
                        if isinstance(self.video_sink, JobKeyedStagedSink):
                            asset_id = self.video_sink.adopt_for_job(out, mime, job_id)
                        else:
                            asset_id = self.video_sink.adopt(out, mime)
            else:
                rendered = adapter.render(request, should_cancel=should_cancel)
                if not isinstance(rendered, RenderedArtifact) or rendered.mime_type not in profile.outputs:
                    raise GenerationError("adapter output does not match the profile")
                if not self.store.begin_publish(job_id, self.instance):
                    raise GenerationCancelled("cancelled before publication")
                publishing = True
                if isinstance(self.image_sink, JobKeyedArtifactSink):
                    asset_id = self.image_sink.publish_and_register_for_job(job_id, rendered.data, rendered.extension)
                else:
                    asset_id = self.image_sink.publish(rendered.data, rendered.extension)
            if not isinstance(asset_id, str) or not asset_id:
                raise ArtifactSinkUnavailable("sink returned no asset id")
            self.last_used = self.clock()
        except ArtifactSinkUnavailable:
            raise  # left running/publishing; recover_gpu() fails it at the next start; no other disk
        except GpuResourcesRetained:
            self._record_failure(job_id, GPU_RETAINED)  # best-effort: never replaces the fatal exit
            raise
        except GenerationCancelled:
            self.last_used = self.clock()
            self.store.finish_cancelled(job_id, self.instance)
            return "cancelled"
        except GpuBusy:
            self.store.fail(job_id, self.instance, GPU_BUSY)
            return "failed"
        except _VRAM_SHORTAGE:  # before anything was submitted; a failed load proved its release
            outcome = self.store.defer(job_id, self.instance, max_wait_s=VRAM_MAX_WAIT_S, error=GPU_UNAVAILABLE)
            self.events.append(f"vram_short:{outcome}")
            if self.adapter is not None:
                # The shortage came from a resident model's pre-job check: chat first means media
                # gives the GPU back while it waits, not only when idle_unload_s expires (which
                # the retries would keep postponing). The job is requeued first, so a failed
                # unload (exit 70) never strands it (#2341 review 4477938515).
                self._unload()
            if outcome == "requeued":
                self._claim_not_before = self.clock() + VRAM_RETRY_S
                return "deferred"
            return "failed" if outcome == "expired" else outcome
        except Exception:
            self.last_used = self.clock()
            # Never persist exception text. After the commit point it is a publication failure.
            self.store.fail(job_id, self.instance, PUBLICATION_FAILED if publishing else FAILED)
            return "failed"
        # The artifact is durable. If its completion cannot be recorded, the job stays publishing
        # (never "generation_failed") and this executor stops: recovery and reconciliation follow.
        try:
            recorded = self.store.complete(job_id, self.instance, asset_id)
        except Exception:
            recorded = False
        if not recorded:
            self.events.append("publication_unrecorded")
            raise PublicationUnrecorded("artifact published but completion not recorded")
        return "completed"

    def _record_failure(self, job_id: str, code: str) -> None:
        try:
            self.store.fail(job_id, self.instance, code)
        except Exception:
            self.events.append(f"record_failed:{code}")

    def run(self, *, max_steps: int | None = None, idle_sleep: Callable[[], None] = lambda: time.sleep(1.0)) -> int:
        """The executor's main loop; returns the process exit code. The executor lock is released
        on every terminal path; a retained adapter's GPU lease is not (it ends with the process)."""
        try:
            self.start()
            steps = 0
            while max_steps is None or steps < max_steps:
                steps += 1
                if self.step() == "idle":
                    if self.clock() >= self._next_purge:
                        self.purge_prompts()
                    idle_sleep()
            self.shutdown()
            return EXIT_DONE
        except ExecutorAlreadyRunning:
            return EXIT_DUPLICATE
        except GpuResourcesRetained:
            return EXIT_GPU_RETAINED
        except ArtifactSinkUnavailable:
            return EXIT_SINK_UNAVAILABLE
        except PublicationUnrecorded:
            return EXIT_UNRECORDED
        except ExecutorConfigError:
            return EXIT_CONFIG
        finally:
            self.release_lock()

    def release_lock(self) -> None:
        lock, self._lock = self._lock, None
        if lock is not None:
            lock.release()
