"""Profile-driven diffusers image adapter (ModelRig #2296).

Generalised from qwen_image_adapter.py on feat/image-generation-contract-20261021:
the pipeline class, model, revision, limits and GPU requirements come from a
ModelProfile instead of being hard-coded to Qwen-Image. The same adapter serves
any profile whose pipeline is on DIFFUSERS_PIPELINES (Qwen-Image, SDXL, FLUX
are candidates, not qualified models).

load() order, each step fail-closed before the next:
  1. offline mode (HF_HUB_OFFLINE=1, TRANSFORMERS_OFFLINE=1): never a download
  2. the device's physical GPU UUID from KALIV_GPU_DEVICE_UUIDS
     (with CUDA_DEVICE_ORDER=PCI_BUS_ID)
  3. the exclusive GPU lease for that UUID
  4. while holding it: torch's device must have that UUID, and the VRAM
     budget must fit the profile
  5. only then load the allowlisted pipeline at the pinned revision, locally
The lease is held until close(): load, inference and the resident lifetime.
It coordinates only processes that take it (see gpu_lease).

A failed load must not hand the GPU to the next executor while the failed
model is still resident (#2315 review 4411189866). Steps 1-4 allocate no
model memory, so a failure there releases the lease. Once step 5 has started,
a failure is cleaned up (the exception's frames are cleared so no traceback
keeps the pipeline alive, then gc, synchronize, empty_cache) and the lease is
released only if torch's allocator is measurably back at the pre-load
baseline. Otherwise the adapter keeps the lease and raises
GpuResourcesRetained: the executor must exit, and the OS frees both the
memory and the lease.

close() follows the same rule for a successful load (#2315 review
5696815799): it drops the pipeline, clears PyTorch's cuBLAS workspaces when
that API exists, and releases the lease only once memory_allocated() is back
at the baseline. If an offload hook or library cache still holds the model,
close() keeps the lease and returns False.

A retained lease must survive the adapter (#2315 review 5697335934): it goes
into a process-lifetime quarantine (a module-level strong reference) and is
marked hold_until_exit(), so neither dropping the adapter nor garbage
collection can release it. It leaves the quarantine only through a measured
release (close() on a live adapter, or release_proven_free() for adapters
that are gone) or through process exit.
Stated limit: memory_allocated() counts PyTorch's caching allocator only, not
allocations made outside it.

Nothing is imported or loaded at import time.
"""
from __future__ import annotations

import gc
import io
import os
import traceback
from dataclasses import dataclass
from typing import Callable, Mapping

from .gpu_lease import GpuLease, acquire_gpu_lease, device_uuid_map, parse_cuda_device
from .image_gpu_admission import inspect_cuda_budget
from .media_generation_contract import GenerationCancelled, GenerationError, GenerationRequest, RenderedArtifact
from .media_generation_profiles import DIFFUSERS_PIPELINES, ModelProfile, validate_request


class GpuResourcesRetained(GenerationError):
    """A failed load may still hold GPU memory; the lease is kept until this process exits."""


def _drop_tracebacks(exc: BaseException) -> None:
    """Clear the frames of exc and every chained exception, so none of them keeps a model alive."""
    pending, seen = [exc], set()
    while pending:
        current = pending.pop()
        if current is None or id(current) in seen:
            continue
        seen.add(id(current))
        if current.__traceback__ is not None:
            traceback.clear_frames(current.__traceback__)
            current.__traceback__ = None
        pending += [current.__cause__, current.__context__]


def _memory_back_to(torch, index: int, baseline: int) -> bool:
    try:
        gc.collect()
        torch.cuda.synchronize(index)
        clear_workspaces = getattr(getattr(torch, "_C", None), "_cuda_clearCublasWorkspaces", None)
        if callable(clear_workspaces):
            clear_workspaces()  # persistent per-handle cuBLAS workspaces are not the model
        torch.cuda.empty_cache()
        return int(torch.cuda.memory_allocated(index)) <= baseline
    except Exception:
        return False  # a broken CUDA context proves nothing


@dataclass(eq=False)
class _Quarantined:
    lease: GpuLease
    torch: object
    index: int
    baseline: int


# Leases whose GPU memory is not proven free. A strong, process-lifetime
# reference: dropping or garbage-collecting the adapter cannot release them.
_QUARANTINE: list[_Quarantined] = []


def quarantined_gpus() -> list[str]:
    """GPU UUIDs this process keeps leased because their memory is not proven free."""
    return [entry.lease.gpu_uuid for entry in _QUARANTINE]


def release_proven_free() -> int:
    """Measure every quarantined GPU again; release the ones back at baseline. Returns how many."""
    released = 0
    for entry in list(_QUARANTINE):
        if _memory_back_to(entry.torch, entry.index, entry.baseline):
            _QUARANTINE.remove(entry)
            entry.lease.release()
            released += 1
    return released


class DiffusersImageAdapter:
    def __init__(self, profile: ModelProfile, *, device: str, lease_dir: str,
                 lease_timeout_s: float = 0.0, env: Mapping[str, str] | None = None):
        if not isinstance(profile, ModelProfile) or profile.backend != "diffusers":
            raise ValueError("DiffusersImageAdapter needs a diffusers profile")
        if profile.pipeline not in DIFFUSERS_PIPELINES:
            raise ValueError("pipeline is not on the diffusers allowlist")
        if device not in profile.resources.devices:
            raise ValueError("device is not allowed by this profile")
        self.profile = profile
        self.profile_id = profile.profile_id
        self.device = device
        self.index = parse_cuda_device(device)
        self.lease_dir = lease_dir
        self.lease_timeout_s = lease_timeout_s
        self._env = os.environ if env is None else env
        self._lease = None
        self._pipeline = None
        self._quarantine: _Quarantined | None = None
        self._baseline: int | None = None
        self._torch = None

    @property
    def loaded(self) -> bool:
        return self._pipeline is not None

    @property
    def retains_gpu(self) -> bool:
        """True while memory from a failed load or an unloaded model is not proven free."""
        return self._quarantine is not None and self._quarantine in _QUARANTINE

    def _retain(self, lease: GpuLease, torch, baseline: int) -> None:
        lease.hold_until_exit()
        entry = _Quarantined(lease, torch, self.index, baseline)
        _QUARANTINE.append(entry)
        self._lease, self._quarantine = lease, entry

    def load(self) -> None:
        if self._pipeline is not None:
            return
        if self.retains_gpu:
            raise GpuResourcesRetained("memory from an earlier load is still allocated on this GPU; restart the executor")
        if self._quarantine is not None:  # released meanwhile by release_proven_free()
            self._quarantine, self._lease = None, None
        if self._env.get("HF_HUB_OFFLINE") != "1" or self._env.get("TRANSFORMERS_OFFLINE") != "1":
            raise GenerationError("offline mode required: HF_HUB_OFFLINE=1 and TRANSFORMERS_OFFLINE=1")
        gpu_uuid = device_uuid_map(self._env).get(self.index)
        if gpu_uuid is None:
            raise GenerationError(f"no GPU UUID is configured for {self.device}")
        lease = acquire_gpu_lease(gpu_uuid, lease_dir=self.lease_dir, timeout_s=self.lease_timeout_s)
        try:
            # Advisory: weights may still exceed what was free, but no process
            # that takes this lease can load onto this GPU while we hold it.
            inspect_cuda_budget(self.index, reserve_gib=self.profile.resources.reserve_gib,
                                min_usable_gib=self.profile.resources.min_usable_gib,
                                expected_uuid=gpu_uuid)
            import torch
            import diffusers
            pipeline_class = getattr(diffusers, self.profile.pipeline)
            baseline = int(torch.cuda.memory_allocated(self.index))
        except BaseException:
            lease.release()  # no model memory has been allocated yet
            raise
        pipeline = None
        failure = None
        try:
            pipeline = pipeline_class.from_pretrained(
                self.profile.model_id, revision=self.profile.revision,
                torch_dtype=torch.bfloat16, local_files_only=True)
            if self.profile.resources.cpu_offload:
                if not hasattr(pipeline, "enable_model_cpu_offload"):
                    raise RuntimeError("installed diffusers does not support model CPU offload")
                pipeline.enable_model_cpu_offload(gpu_id=self.index)
            else:
                pipeline = pipeline.to(self.device)
        except Exception as exc:
            failure = type(exc).__name__
            _drop_tracebacks(exc)
            pipeline = None
        except BaseException:
            # Interrupted mid-load: cleanup cannot be proven. Keep the lease;
            # the process is ending and the OS releases it with the memory.
            self._retain(lease, torch, baseline)
            raise
        if failure is None:
            self._lease, self._pipeline = lease, pipeline
            self._baseline, self._torch = baseline, torch
            return
        # Outside the except block: the exception object is gone, and so is
        # every frame it pinned. Now measure instead of assuming.
        if _memory_back_to(torch, self.index, baseline):
            lease.release()
            raise GenerationError(f"model load failed ({failure}); GPU memory verified released")
        self._retain(lease, torch, baseline)
        raise GpuResourcesRetained(
            f"model load failed ({failure}) and GPU memory could not be proven free; "
            "the GPU lease is kept until this process exits")

    def render(self, request: GenerationRequest, *,
               should_cancel: Callable[[], bool] | None = None) -> RenderedArtifact:
        """Render one PNG. should_cancel is polled after each denoising step; True sets the
        pipeline's interrupt flag, the partial image is discarded and GenerationCancelled is raised."""
        if self._pipeline is None:
            raise RuntimeError("adapter is not loaded")
        request = validate_request(self.profile, request)
        if request.task != "text_to_image":
            raise GenerationError("this adapter renders text_to_image only")
        if should_cancel is not None and should_cancel():
            raise GenerationCancelled("cancelled before rendering")
        kwargs = {
            "prompt": request.prompt,
            "num_inference_steps": request.steps,
            "width": request.width,
            "height": request.height,
        }
        if request.seed is not None:
            import torch
            kwargs["generator"] = torch.Generator(device="cpu").manual_seed(request.seed)
        cancelled = []
        if should_cancel is not None:
            def on_step_end(pipeline, step, timestep, callback_kwargs):
                if not cancelled and should_cancel():
                    cancelled.append(step)
                    pipeline._interrupt = True  # diffusers skips the remaining steps
                return callback_kwargs
            kwargs["callback_on_step_end"] = on_step_end
        image = self._pipeline(**kwargs).images[0]
        if cancelled:
            raise GenerationCancelled("cancelled while rendering")
        output = io.BytesIO()
        image.save(output, format="PNG")
        return RenderedArtifact(output.getvalue(), "image/png")

    def close(self) -> bool:
        """Unload. True once the lease is released; False while GPU memory is not proven free.

        After False the lease stays held in the process-lifetime quarantine,
        even if this adapter is dropped: call close() again later, call
        release_proven_free(), or let the executor exit.
        """
        if self._pipeline is not None:
            self._pipeline = None  # drop our reference first
            self._retain(self._lease, self._torch, self._baseline)
        entry = self._quarantine
        if entry is None:
            return self._lease is None
        if entry in _QUARANTINE:
            if not _memory_back_to(entry.torch, entry.index, entry.baseline):
                return False
            _QUARANTINE.remove(entry)
            entry.lease.release()
        self._quarantine, self._lease = None, None
        return True
