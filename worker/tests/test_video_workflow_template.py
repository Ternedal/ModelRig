"""Offline tests for trusted ComfyUI text-to-video parameter binding."""
import json
import tempfile
import unittest
from pathlib import Path

from app.video_contract import VideoRequest
from app.video_workflow_template import trusted_text_to_video_factory


def graph():
    return {
        "1": {"class_type": "CLIPTextEncode",
              "inputs": {"text": "__KALIV_VIDEO_PROMPT__", "clip": ["2", 0]}},
        "2": {"class_type": "WanVideoLatent",
              "inputs": {"width": "__KALIV_VIDEO_WIDTH__",
                         "height": "__KALIV_VIDEO_HEIGHT__",
                         "length": "__KALIV_VIDEO_FRAMES__"}},
        "3": {"class_type": "VideoCombine",
              "inputs": {"fps": "__KALIV_VIDEO_FPS__"}},
    }


class WorkflowTemplateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "wan.json"

    def write(self, value):
        self.path.write_text(json.dumps(value), encoding="utf-8")

    def test_all_parameters_are_bound_and_graph_is_copied(self):
        self.write(graph())
        build = trusted_text_to_video_factory(self.path)
        request = VideoRequest(kind="text_to_video", prompt="Clouds",
                               width=640, height=384, fps=16, duration_seconds=3)
        first = build(request)
        self.assertEqual(first["1"]["inputs"]["text"], "Clouds")
        self.assertEqual(first["2"]["inputs"]["width"], 640)
        self.assertEqual(first["2"]["inputs"]["height"], 384)
        self.assertEqual(first["2"]["inputs"]["length"], 49)
        self.assertEqual(first["3"]["inputs"]["fps"], 16)
        self.assertEqual(first["1"]["inputs"]["clip"], ["2", 0])
        first["1"]["inputs"]["text"] = "mutated"
        self.assertEqual(build(request)["1"]["inputs"]["text"], "Clouds")

    def test_image_to_video_is_not_supported(self):
        self.write(graph())
        build = trusted_text_to_video_factory(self.path)
        with self.assertRaises(ValueError):
            build(VideoRequest(kind="image_to_video", prompt="Clouds", input_image_id="image_1"))

    def test_missing_duplicate_or_nested_slots_rejected(self):
        for mutate in (
            lambda g: g["2"]["inputs"].pop("width"),
            lambda g: g["3"]["inputs"].update({"extra": "__KALIV_VIDEO_PROMPT__"}),
            lambda g: g["1"]["inputs"].update({"text": ["__KALIV_VIDEO_PROMPT__"]}),
            lambda g: g["2"]["inputs"].update({"width": "__KALIV_VIDEO_HEIGHT__"}),
        ):
            with self.subTest(mutate=mutate):
                value = graph()
                mutate(value)
                self.write(value)
                with self.assertRaises(ValueError):
                    trusted_text_to_video_factory(self.path)


if __name__ == "__main__":
    unittest.main()
