"""Offline tests for opt-in, one-shot collection command."""
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.video_comfy_collect_once import collect_once


class CollectOnceTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.output = self.root / "ComfyUI" / "output"
        self.output.mkdir(parents=True)
        self.paths = {"jobs": self.root / "Jobs"}
        self.paths["jobs"].mkdir()

    def test_requires_explicit_output_directory(self):
        with patch("app.video_comfy_collect_once.configured_video_storage") as config, patch.dict(
            os.environ, {"COMFYUI_OUTPUT_DIRECTORY": ""}, clear=False
        ):
            config.return_value.root = self.root
            config.return_value.initialize_directories.return_value = self.paths
            with self.assertRaises(ValueError):
                collect_once()

    def test_rejects_output_outside_media_volume(self):
        with tempfile.TemporaryDirectory() as other:
            with patch("app.video_comfy_collect_once.configured_video_storage") as config, patch.dict(
                os.environ, {"COMFYUI_OUTPUT_DIRECTORY": other}, clear=False
            ):
                config.return_value.root = self.root
                config.return_value.initialize_directories.return_value = self.paths
                with self.assertRaises(ValueError):
                    collect_once()

    def test_delegates_to_collector(self):
        with patch("app.video_comfy_collect_once.configured_video_storage") as config, patch.dict(
            os.environ, {"COMFYUI_OUTPUT_DIRECTORY": str(self.output)}, clear=False
        ), patch("app.video_comfy_collect_once.VideoJobStore"), patch(
            "app.video_comfy_collect_once.MediaCatalog"
        ), patch("app.video_comfy_collect_once.ComfyVideoClient"), patch(
            "app.video_comfy_collect_once.VideoResultCollector"
        ) as collector:
            config.return_value.root = self.root
            config.return_value.initialize_directories.return_value = self.paths
            collector.return_value.collect_one.return_value = "media_123"
            self.assertEqual(collect_once(), "media_123")


if __name__ == "__main__":
    unittest.main()
