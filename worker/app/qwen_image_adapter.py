"""Opt-in Qwen Image adapter. Does not load weights on import."""
from __future__ import annotations

from .image_gpu_admission import inspect_cuda_budget
from .image_job_runner import RenderedImage


class QwenImageAdapter:
    def __init__(self, model_id: str, *, device: str = "cuda:0",
                 revision: str | None = None, cpu_offload: bool = False,
                 reserve_gib: float = 3.0, min_usable_gib: float = 6.0):
        if not model_id or not model_id.strip():
            raise ValueError("model_id required")
        if device not in {"cuda:0", "cuda:1", "cpu"}:
            raise ValueError("unsupported device")
        if cpu_offload and device == "cpu":
            raise ValueError("CPU offload requires a CUDA device")
        self.model_id = model_id
        self.device = device
        self.revision = revision
        self.cpu_offload = cpu_offload
        self.reserve_gib = reserve_gib
        self.min_usable_gib = min_usable_gib
        self._pipeline = None

    def load(self) -> None:
        # A preflight is advisory: weights may still exceed available memory.
        # Run before downloading/loading large model artifacts.
        if self.device.startswith("cuda:"):
            inspect_cuda_budget(int(self.device.split(":")[1]),
                                reserve_gib=self.reserve_gib,
                                min_usable_gib=self.min_usable_gib)
        import torch
        from diffusers import QwenImagePipeline
        kwargs = {"torch_dtype": torch.bfloat16}
        if self.revision is not None:
            kwargs["revision"] = self.revision
        pipeline = QwenImagePipeline.from_pretrained(self.model_id, **kwargs)
        if self.cpu_offload:
            if not hasattr(pipeline, "enable_model_cpu_offload"):
                raise RuntimeError("installed Diffusers does not support model CPU offload")
            # Accelerate offload uses this GPU as execution target.
            pipeline.enable_model_cpu_offload(gpu_id=int(self.device.split(":")[1]))
        else:
            pipeline = pipeline.to(self.device)
        self._pipeline = pipeline

    def __call__(self, prompt: str) -> RenderedImage:
        if self._pipeline is None:
            raise RuntimeError("Qwen Image adapter is not loaded")
        if not isinstance(prompt, str) or not prompt.strip():
            raise ValueError("prompt required")
        import io
        image = self._pipeline(prompt=prompt, num_inference_steps=20).images[0]
        output = io.BytesIO()
        image.save(output, format="PNG")
        return RenderedImage(output.getvalue(), ".png")
