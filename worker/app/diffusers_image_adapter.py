"""Profile-driven diffusers image adapter (ModelRig #2296).

Generalised from qwen_image_adapter.py on feat/image-generation-contract-20261021:
the pipeline class, model, revision, limits and GPU requirements come from a
ModelProfile instead of being hard-coded to Qwen-Image. The same adapter serves
any profile whose pipeline is on DIFFUSERS_PIPELINES (Qwen-Image, SDXL, FLUX
are candidates, not qualified models).

load() order, each step fail-closed before the next:
  1. offline mode (HF_HUB_OFFLINE=1, TRANSFORMERS_OFFLINE=1): never a download
  2. the exclusive GPU lease for the profile's device
  3. the VRAM budget, checked while holding the lease
  4. only then import torch/diffusers and load the pinned revision locally
The lease is held until close(), i.e. for as long as the model is resident.

Nothing is imported or loaded at import time.
"""
from __future__ import annotations

import io
import os
from typing import Mapping

from .gpu_lease import acquire_gpu_lease, parse_cuda_device
from .image_gpu_admission import inspect_cuda_budget
from .media_generation_contract import GenerationError, GenerationRequest, RenderedArtifact
from .media_generation_profiles import DIFFUSERS_PIPELINES, ModelProfile, validate_request


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

    @property
    def loaded(self) -> bool:
        return self._pipeline is not None

    def load(self) -> None:
        if self._pipeline is not None:
            return
        if self._env.get("HF_HUB_OFFLINE") != "1" or self._env.get("TRANSFORMERS_OFFLINE") != "1":
            raise GenerationError("offline mode required: HF_HUB_OFFLINE=1 and TRANSFORMERS_OFFLINE=1")
        lease = acquire_gpu_lease(self.index, lease_dir=self.lease_dir, timeout_s=self.lease_timeout_s)
        try:
            # Advisory: weights may still exceed what was free, but nothing else
            # can load onto this GPU while we hold the lease.
            inspect_cuda_budget(self.index, reserve_gib=self.profile.resources.reserve_gib,
                                min_usable_gib=self.profile.resources.min_usable_gib)
            import torch
            import diffusers
            pipeline_class = getattr(diffusers, self.profile.pipeline)
            pipeline = pipeline_class.from_pretrained(
                self.profile.model_id, revision=self.profile.revision,
                torch_dtype=torch.bfloat16, local_files_only=True)
            if self.profile.resources.cpu_offload:
                if not hasattr(pipeline, "enable_model_cpu_offload"):
                    raise RuntimeError("installed diffusers does not support model CPU offload")
                pipeline.enable_model_cpu_offload(gpu_id=self.index)
            else:
                pipeline = pipeline.to(self.device)
        except BaseException:
            lease.release()
            raise
        self._lease = lease
        self._pipeline = pipeline

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
