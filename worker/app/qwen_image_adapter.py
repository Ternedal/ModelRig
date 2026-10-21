"""Optional Diffusers adapter for Qwen-Image.

No model loading at import time. Call load() only in a dedicated GPU worker.
Model identifiers and revision should be pinned by deployment after qualification.
"""
from __future__ import annotations

from .image_job_runner import RenderedImage


class QwenImageAdapter:
    def __init__(self, model_id: str, *, device: str = "cuda:0", revision: str | None = None):
        if not model_id or not model_id.strip():
            raise ValueError("model_id required")
        if device not in {"cuda:0", "cuda:1", "cpu"}:
            raise ValueError("unsupported device")
        self.model_id = model_id
        self.device = device
        self.revision = revision
        self._pipeline = None

    def load(self) -> None:
        # Lazy import prevents runtime dependencies from affecting normal chat.
        import torch
        from diffusers import QwenImagePipeline
        kwargs = {"torch_dtype": torch.bfloat16}
        if self.revision is not None:
            kwargs["revision"] = self.revision
        pipeline = QwenImagePipeline.from_pretrained(self.model_id, **kwargs)
        self._pipeline = pipeline.to(self.device)

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
