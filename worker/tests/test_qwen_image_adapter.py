"""Qwen Image adapter contract tests; no model download or GPU required."""
import sys
import types
import unittest
from unittest.mock import patch

from app.qwen_image_adapter import QwenImageAdapter
from app.image_gpu_admission import ImageGpuAdmissionError


class QwenImageAdapterTests(unittest.TestCase):
    def test_requires_explicit_load(self):
        adapter = QwenImageAdapter("local/model")
        with self.assertRaises(RuntimeError):
            adapter("a landscape")

    def test_rejects_bad_device(self):
        with self.assertRaises(ValueError):
            QwenImageAdapter("local/model", device="cuda:9")

    def test_preflight_fails_before_import(self):
        with patch("app.qwen_image_adapter.inspect_cuda_budget",
                   side_effect=ImageGpuAdmissionError("busy")):
            with self.assertRaises(ImageGpuAdmissionError):
                QwenImageAdapter("local/model").load()

    def test_lazy_loading_and_png(self):
        from PIL import Image
        fake_image = Image.new("RGB", (2, 2), "blue")
        calls = []
        class FakePipeline:
            @classmethod
            def from_pretrained(cls, model_id, **kwargs):
                calls.append((model_id, kwargs))
                return cls()
            def to(self, device):
                calls.append(("device", device))
                return self
            def enable_model_cpu_offload(self, **kwargs):
                calls.append(("offload", kwargs))
            def __call__(self, **kwargs):
                return types.SimpleNamespace(images=[fake_image])
        fake_diffusers = types.SimpleNamespace(QwenImagePipeline=FakePipeline)
        fake_torch = types.SimpleNamespace(bfloat16="bf16")
        with patch("app.qwen_image_adapter.inspect_cuda_budget") as probe, patch.dict(
                sys.modules, {"diffusers": fake_diffusers, "torch": fake_torch}):
            adapter = QwenImageAdapter("local/model", device="cuda:1", revision="pinned")
            adapter.load()
            result = adapter("blue sky")
        probe.assert_called_once_with(1, reserve_gib=3.0, min_usable_gib=6.0)
        self.assertTrue(result.data.startswith(b"\x89PNG\r\n\x1a\n"))
        self.assertEqual(result.extension, ".png")
        self.assertEqual(calls[0][0], "local/model")
        self.assertEqual(calls[1], ("device", "cuda:1"))

    def test_cpu_offload_path(self):
        class FakePipeline:
            @classmethod
            def from_pretrained(cls, *_args, **_kwargs):
                return cls()
            def enable_model_cpu_offload(self, **kwargs):
                self.offload_args = kwargs
        with patch("app.qwen_image_adapter.inspect_cuda_budget"), patch.dict(
                sys.modules, {"diffusers": types.SimpleNamespace(QwenImagePipeline=FakePipeline),
                              "torch": types.SimpleNamespace(bfloat16="bf16")}):
            adapter = QwenImageAdapter("local/model", device="cuda:1", cpu_offload=True)
            adapter.load()
        self.assertEqual(adapter._pipeline.offload_args, {"gpu_id": 1})


if __name__ == "__main__":
    unittest.main()
