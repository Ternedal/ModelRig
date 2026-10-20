"""Offline compatibility checks against mocked ComfyUI object_info."""
import io
import json
import tempfile
import unittest
from pathlib import Path

from app.video_comfy_compatibility import MAX_TEMPLATE_BYTES, probe_nodes


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
    def test_rejects_oversized_template_without_network(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "workflow.json"
            path.write_bytes(b"x" * (MAX_TEMPLATE_BYTES + 1))
            def no_network(*args, **kwargs):
                self.fail("Oversized template must not contact ComfyUI")
            self.assertEqual(probe_nodes(path, opener=no_network)["status"], "invalid_template")

    def test_rejects_non_graph_template_without_network(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "workflow.json"
            path.write_text('["not a graph"]')
            def no_network(*args, **kwargs):
                self.fail("Invalid graph must not contact ComfyUI")
            self.assertEqual(probe_nodes(path, opener=no_network)["status"], "invalid_template")

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

    def test_installed_model_choice_is_compatible(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "workflow.json"
            path.write_text(json.dumps({"1": {"class_type": "CheckpointLoaderSimple",
                                             "inputs": {"ckpt_name": "installed.safetensors"}}}))
            report = probe_nodes(path, opener=lambda *a, **kw: Response({
                "CheckpointLoaderSimple": {"input": {"required": {
                    "ckpt_name": [["installed.safetensors"], {}]}}}
            }))
            self.assertEqual(report["status"], "compatible")

    def test_unbound_request_placeholder_is_not_a_missing_model(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "workflow.json"
            path.write_text(json.dumps({"1": {"class_type": "PromptNode",
                                             "inputs": {"text": "__KALIV_VIDEO_PROMPT__"}}}))
            report = probe_nodes(path, opener=lambda *a, **kw: Response({
                "PromptNode": {"input": {"required": {"text": [["example"], {}]}}}
            }))
            self.assertEqual(report["status"], "compatible")

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
