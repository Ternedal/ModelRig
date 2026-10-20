"""Offline compatibility checks against mocked ComfyUI object_info."""
import io
import json
import tempfile
import unittest
from pathlib import Path

from app.video_comfy_compatibility import probe_nodes


class Response:
    status = 200

    def __init__(self, data):
        self.buffer = io.BytesIO(json.dumps(data).encode())

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def read(self, size):
        return self.buffer.read(size)


class CompatibilityTests(unittest.TestCase):
    def test_detects_unknown_input(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "workflow.json"
            path.write_text(json.dumps({"1": {"class_type": "WanNode", "inputs": {"obsolete": 1}}}))
            report = probe_nodes(path, opener=lambda *a, **kw: Response({
                "WanNode": {"input": {"required": {"model": ["STRING", {}]}, "optional": {}}}
            }))
            self.assertEqual(report["status"], "invalid_inputs")
            self.assertEqual(report["invalid_inputs"][0]["input"], "obsolete")

    def test_missing_model_choice_is_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "workflow.json"
            path.write_text(json.dumps({"1": {"class_type": "CheckpointLoaderSimple",
                                             "inputs": {"ckpt_name": "missing.safetensors"}}}))
            report = probe_nodes(path, opener=lambda *a, **kw: Response({
                "CheckpointLoaderSimple": {"input": {"required": {
                    "ckpt_name": [["installed.safetensors"], {}]}}}
            }))
            self.assertEqual(report["status"], "invalid_choices")
            self.assertEqual(report["invalid_choices"][0]["input"], "ckpt_name")

    def test_compatible_input_names(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "workflow.json"
            path.write_text(json.dumps({"1": {"class_type": "WanNode", "inputs": {"model": "foo"}}}))
            report = probe_nodes(path, opener=lambda *a, **kw: Response({
                "WanNode": {"input": {"required": {"model": ["STRING", {}]}}}
            }))
            self.assertEqual(report["status"], "compatible")


if __name__ == "__main__":
    unittest.main()
