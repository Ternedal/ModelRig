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
            store.db_path = Path(directory) / "Jobs" / "video_jobs.sqlite"
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
            catalog.db_path = Path(directory) / "Jobs" / "media_catalog.sqlite"
            catalog.media_root = root / "Media"
            with patch("app.video_comfy_collector.configured_video_storage", new_callable=lambda: Mock(return_value=Mock(root=root, unsafe=True))) as storage:
                collector = VideoResultCollector(store, client, catalog, output)
                self.assertIsNone(collector.collect_one())
            storage.return_value.assert_ready.assert_called_once_with()
            catalog.register.assert_not_called()
            store.transition.assert_called_once_with(
                "job1", "running", "failed", error_code="invalid_backend_output"
            )

    def test_regular_mp4_is_registered_and_job_completed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "output"
            output.mkdir()
            media = root / "Media"
            (media / "Videos").mkdir(parents=True)
            source = output / "clip.mp4"
            payload = b"\x00\x00\x00\x18ftypisom" + b"\x00" * 24
            source.write_bytes(payload)
            store = Mock()
            store.db_path = Path(directory) / "Jobs" / "video_jobs.sqlite"
            store.awaiting_result.return_value = [
                {"job_id": "job1", "prompt_id": "prompt1"}
            ]
            store.transition.return_value = True
            client = Mock()
            client.completed_outputs.return_value = {
                "node1": {"videos": [{"type": "output", "subfolder": "",
                                      "filename": "clip.mp4"}]}
            }
            catalog = Mock()
            catalog.db_path = Path(directory) / "Jobs" / "media_catalog.sqlite"
            catalog.media_root = root / "Media"
            catalog.media_root = media
            with patch("app.video_comfy_collector.configured_video_storage", new_callable=lambda: Mock(return_value=Mock(root=root, unsafe=True))):
                collector = VideoResultCollector(store, client, catalog, output)
                media_id = collector.collect_one()
            self.assertIsInstance(media_id, str)
            destination = media / "Videos" / (media_id + ".mp4")
            self.assertEqual(destination.read_bytes(), payload)
            self.assertEqual(catalog.register.call_count, 1)
            self.assertEqual(catalog.register.call_args.args[0].media_id, media_id)
            self.assertEqual(catalog.register.call_args.args[1], destination)
            store.transition.assert_called_once_with(
                "job1", "running", "completed", artifact_id=media_id
            )

    def test_multiple_outputs_are_rejected_without_catalog_write(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "output"
            output.mkdir()
            for name in ("first.mp4", "second.mp4"):
                (output / name).write_bytes(
                    b"\x00\x00\x00\x18ftypisom" + b"\x00" * 24
                )
            store = Mock()
            store.db_path = Path(directory) / "Jobs" / "video_jobs.sqlite"
            store.awaiting_result.return_value = [
                {"job_id": "job1", "prompt_id": "prompt1"}
            ]
            store.transition.return_value = True
            client = Mock()
            client.completed_outputs.return_value = {
                "node1": {"videos": [
                    {"type": "output", "subfolder": "", "filename": "first.mp4"},
                    {"type": "output", "subfolder": "", "filename": "second.mp4"},
                ]}
            }
            catalog = Mock()
            catalog.db_path = Path(directory) / "Jobs" / "media_catalog.sqlite"
            catalog.media_root = root / "Media"
            with patch("app.video_comfy_collector.configured_video_storage", new_callable=lambda: Mock(return_value=Mock(root=root, unsafe=True))):
                collector = VideoResultCollector(store, client, catalog, output)
                self.assertIsNone(collector.collect_one())
            catalog.register.assert_not_called()
            store.transition.assert_called_once_with(
                "job1", "running", "failed", error_code="invalid_backend_output"
            )

    def test_valid_file_plus_traversal_entry_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "output"
            output.mkdir()
            (output / "clip.mp4").write_bytes(
                b"\x00\x00\x00\x18ftypisom" + b"\x00" * 24
            )
            store = Mock()
            store.db_path = Path(directory) / "Jobs" / "video_jobs.sqlite"
            store.awaiting_result.return_value = [
                {"job_id": "job1", "prompt_id": "prompt1"}
            ]
            store.transition.return_value = True
            client = Mock()
            client.completed_outputs.return_value = {
                "node1": {"videos": [
                    {"type": "output", "subfolder": "", "filename": "clip.mp4"},
                    {"type": "output", "subfolder": "../outside",
                     "filename": "escape.mp4"},
                ]}
            }
            catalog = Mock()
            catalog.db_path = Path(directory) / "Jobs" / "media_catalog.sqlite"
            catalog.media_root = root / "Media"
            with patch("app.video_comfy_collector.configured_video_storage", new_callable=lambda: Mock(return_value=Mock(root=root, unsafe=True))):
                collector = VideoResultCollector(store, client, catalog, output)
                self.assertIsNone(collector.collect_one())
            catalog.register.assert_not_called()
            store.transition.assert_called_once_with(
                "job1", "running", "failed", error_code="invalid_backend_output"
            )

    def test_malformed_output_containers_fail_without_crash(self):
        for outputs in ([], "not a mapping", {"node1": None},
                        {"node1": {"videos": "not a list"}}):
            with self.subTest(outputs=outputs), tempfile.TemporaryDirectory() as directory:
                output = Path(directory)
                store = Mock()
                store.db_path = Path(directory) / "Jobs" / "video_jobs.sqlite"
                store.awaiting_result.return_value = [
                    {"job_id": "job1", "prompt_id": "prompt1"}
                ]
                store.transition.return_value = True
                client = Mock()
                client.completed_outputs.return_value = outputs
                catalog = Mock()
                catalog.db_path = Path(directory) / "Jobs" / "media_catalog.sqlite"
                catalog.media_root = output / "Media"
                root = output
                with patch("app.video_comfy_collector.configured_video_storage", new_callable=lambda: Mock(return_value=Mock(root=root, unsafe=True))):
                    collector = VideoResultCollector(store, client, catalog, output)
                    self.assertIsNone(collector.collect_one())
                catalog.register.assert_not_called()
                store.transition.assert_called_once_with(
                    "job1", "running", "failed", error_code="invalid_backend_output"
                )

    def test_pending_history_keeps_job_running(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            store = Mock()
            store.db_path = Path(directory) / "Jobs" / "video_jobs.sqlite"
            store.awaiting_result.return_value = [
                {"job_id": "job1", "prompt_id": "prompt1"}
            ]
            client = Mock()
            client.completed_outputs.return_value = None
            catalog = Mock()
            catalog.db_path = Path(directory) / "Jobs" / "media_catalog.sqlite"
            root = output
            catalog.media_root = root / "Media"
            with patch("app.video_comfy_collector.configured_video_storage", new_callable=lambda: Mock(return_value=Mock(root=root, unsafe=True))):
                collector = VideoResultCollector(store, client, catalog, output)
                self.assertIsNone(collector.collect_one())
            store.transition.assert_not_called()
            catalog.register.assert_not_called()

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
