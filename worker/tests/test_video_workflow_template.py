"""Offline tests for trusted ComfyUI text-to-video workflow binding."""
import json
import tempfile
import unittest
from pathlib import Path

from app.video_contract import VideoRequest
from app.video_workflow_template import trusted_text_to_video_factory


class WorkflowTemplateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "wan.json"

    def write(self, graph):
        self.path.write_text(json.dumps(graph), encoding="utf-8")

    def test_only_prompt_text_is_substituted(self):
        self.write({"1": {"class_type": "CLIPTextEncode",
                          "inputs": {"text": "__KALIV_VIDEO_PROMPT__", "clip": ["2", 0]}},
                    "2": {"class_type": "CheckpointLoaderSimple",
                          "inputs": {"ckpt_name": "operator.safetensors"}}})
        build = trusted_text_to_video_factory(self.path)
        request = VideoRequest(kind="text_to_video", prompt="Clouds")
        first = build(request)
        self.assertEqual(first["1"]["inputs"]["text"], "Clouds")
        self.assertEqual(first["2"]["inputs"]["ckpt_name"], "operator.safetensors")
        first["1"]["inputs"]["text"] = "mutated"
        self.assertEqual(build(request)["1"]["inputs"]["text"], "Clouds")

    def test_image_to_video_is_not_supported(self):
        self.write({"1": {"class_type": "CLIPTextEncode",
                          "inputs": {"text": "__KALIV_VIDEO_PROMPT__"}}})
        build = trusted_text_to_video_factory(self.path)
        with self.assertRaises(ValueError):
            build(VideoRequest(kind="image_to_video", prompt="Clouds", input_image_id="image_1"))

    def test_missing_or_duplicate_prompt_slot_rejected(self):
        for graph in (
            {"1": {"class_type": "A", "inputs": {"text": "fixed"}}},
            {"1": {"class_type": "A", "inputs": {"text": "__KALIV_VIDEO_PROMPT__"}},
             "2": {"class_type": "B", "inputs": {"text": "__KALIV_VIDEO_PROMPT__"}}},
            {"1": {"class_type": "A", "inputs": {"model": "__KALIV_VIDEO_PROMPT__"}}},
        ):
            with self.subTest(graph=graph):
                self.write(graph)
                with self.assertRaises(ValueError):
                    trusted_text_to_video_factory(self.path)


if __name__ == "__main__":
    unittest.main()
