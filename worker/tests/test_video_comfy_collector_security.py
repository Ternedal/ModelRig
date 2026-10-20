"""Offline collector path-boundary regressions; no ComfyUI or GPU required."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from app.video_comfy_collector import VideoResultCollector


class CollectorPathSecurityTests(unittest.TestCase):
    def test_symlinked_output_subdirectory_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "output"
            output.mkdir()
            elsewhere = root / "elsewhere"
            elsewhere.mkdir()
            (elsewhere / "clip.mp4").write_bytes(
                b"\x00\x00\x00\x18ftypisom" + b"\x00" * 24
            )
            try:
                (output / "alias").symlink_to(elsewhere, target_is_directory=True)
            except (OSError, NotImplementedError):
                self.skipTest("Filesystem does not support symlinks")
            store = Mock()
            store.awaiting_result.return_value = [
                {"job_id": "job1", "prompt_id": "prompt1"}
            ]
            store.transition.return_value = True
            client = Mock()
            client.completed_outputs.return_value = {
                "node1": {"videos": [{"type": "output",
                                      "subfolder": "alias",
                                      "filename": "clip.mp4"}]}
            }
            catalog = Mock()
            with patch("app.video_comfy_collector.configured_video_storage") as storage:
                collector = VideoResultCollector(store, client, catalog, output)
                self.assertIsNone(collector.collect_one())
            storage.return_value.assert_ready.assert_called_once_with()
            catalog.register.assert_not_called()
            store.transition.assert_called_once_with(
                "job1", "running", "failed", error_code="invalid_backend_output"
            )

    def test_symlinked_output_root_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            actual = root / "actual"
            actual.mkdir()
            alias = root / "alias"
            try:
                alias.symlink_to(actual, target_is_directory=True)
            except (OSError, NotImplementedError):
                self.skipTest("Filesystem does not support symlinks")
            with self.assertRaises(ValueError):
                VideoResultCollector(Mock(), Mock(), Mock(), alias)


if __name__ == "__main__":
    unittest.main()
