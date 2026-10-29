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
memory and the lease. Stated limit: memory_allocated() counts PyTorch's
caching allocator only, not allocations made outside it.

Nothing is imported or loaded at import time.
"""
from __future__ import annotations

import gc
import io
import os
import traceback
from typing import Mapping

from .gpu_lease import acquire_gpu_lease, device_uuid_map, parse_cuda_device
from .image_gpu_admission import inspect_cuda_budget
from .media_generation_contract import GenerationError, GenerationRequest, RenderedArtifact
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
        self._retained_baseline: int | None = None

    @property
    def loaded(self) -> bool:
        return self._pipeline is not None

    @property
    def retains_gpu(self) -> bool:
        """True after a failed load that could not prove its GPU memory free."""
        return self._retained_baseline is not None

    def _memory_back_to(self, torch, baseline: int) -> bool:
        try:
            gc.collect()
            torch.cuda.synchronize(self.index)
            torch.cuda.empty_cache()
            return int(torch.cuda.memory_allocated(self.index)) <= baseline
        except Exception:
            return False  # a broken CUDA context proves nothing

    def load(self) -> None:
        if self._pipeline is not None:
            return
        if self._retained_baseline is not None:
            raise GpuResourcesRetained("an earlier failed load still holds this GPU; restart the executor")
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
            self._lease, self._retained_baseline = lease, baseline
            raise
        if failure is None:
            self._lease = lease
            self._pipeline = pipeline
            return
        # Outside the except block: the exception object is gone, and so is
        # every frame it pinned. Now measure instead of assuming.
        if self._memory_back_to(torch, baseline):
            lease.release()
            raise GenerationError(f"model load failed ({failure}); GPU memory verified released")
        self._lease, self._retained_baseline = lease, baseline
        raise GpuResourcesRetained(
            f"model load failed ({failure}) and GPU memory could not be proven free; "
            "the GPU lease is kept until this process exits")

    def render(self, request: GenerationRequest) -> RenderedArtifact:
        if self._pipeline is None:
            raise RuntimeError("adapter is not loaded")
        request = validate_request(self.profile, request)
        if request.task != "text_to_image":
            raise GenerationError("this adapter renders text_to_image only")
        kwargs = {
            "prompt": request.prompt,
            "num_inference_steps": request.steps,
            "width": request.width,
            "height": request.height,
        }
        if request.seed is not None:
            import torch
            kwargs["generator"] = torch.Generator(device="cpu").manual_seed(request.seed)
        image = self._pipeline(**kwargs).images[0]
        output = io.BytesIO()
        image.save(output, format="PNG")
        return RenderedArtifact(output.getvalue(), "image/png")

    def close(self) -> None:
        if self._retained_baseline is not None:
            # Release only once the failed load's memory is measurably gone.
            import torch
            if self._memory_back_to(torch, self._retained_baseline):
                lease, self._lease, self._retained_baseline = self._lease, None, None
                if lease is not None:
                    lease.release()
            return
        pipeline, self._pipeline = self._pipeline, None
        lease, self._lease = self._lease, None
        try:
            if pipeline is not None:
                del pipeline
                try:
                    import torch
                    torch.cuda.empty_cache()
                except Exception:
                    pass
        finally:
            if lease is not None:
                lease.release()
