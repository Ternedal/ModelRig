"""Qwen Image adapter contract tests; no model download or GPU required."""
import io
import sys
import types
import unittest
from unittest.mock import patch

from app.qwen_image_adapter import QwenImageAdapter


class QwenImageAdapterTests(unittest.TestCase):
    def test_requires_explicit_load(self):
        adapter = QwenImageAdapter("local/model")
        with self.assertRaises(RuntimeError):
            adapter("a landscape")

    def test_rejects_bad_device(self):
        with self.assertRaises(ValueError):
            QwenImageAdapter("local/model", device="cuda:9")

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
            def __call__(self, **kwargs):
                return types.SimpleNamespace(images=[fake_image])
        fake_diffusers = types.SimpleNamespace(QwenImagePipeline=FakePipeline)
        fake_torch = types.SimpleNamespace(bfloat16="bf16")
        with patch.dict(sys.modules, {"diffusers": fake_diffusers, "torch": fake_torch}):
            adapter = QwenImageAdapter("local/model", device="cuda:1", revision="pinned")
            adapter.load()
            result = adapter("blue sky")
        self.assertTrue(result.data.startswith(b"\x89PNG\r\n\x1a\n"))
        self.assertEqual(result.extension, ".png")
        self.assertEqual(calls[0][0], "local/model")
        self.assertEqual(calls[1], ("device", "cuda:1"))


if __name__ == "__main__":
    unittest.main()
