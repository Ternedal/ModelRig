"""Offline tests for the one-shot ComfyUI video result collector."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from app.video_comfy_collector import VideoResultCollector
from app.video_contract import VideoRequest
from app.video_job_store import VideoJobStore
from app.video_media_catalog import MediaCatalog


class FakeClient:
    def __init__(self, outputs):
        self.outputs = outputs

    def completed_outputs(self, prompt_id):
        return self.outputs


class CollectorTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        self.media = root / "external"
        self.output = self.media / "ComfyUI" / "output"
        self.output.mkdir(parents=True)
        (self.media / "Media" / "Videos").mkdir(parents=True)
        (self.media / "Jobs").mkdir()
        self.store = VideoJobStore(self.media / "Jobs" / "video_jobs.sqlite")
        self.catalog = MediaCatalog(self.media)
        self.job_id = self.store.create(VideoRequest(kind="text_to_video", prompt="Clouds"))
        self.assertTrue(self.store.transition(self.job_id, "queued", "running"))
        self.assertTrue(self.store.record_prompt(self.job_id, "prompt_1"))

    def collector(self, outputs):
        return VideoResultCollector(self.store, FakeClient(outputs), self.catalog, self.output)

    def test_rejects_symlinked_job_database_outside_approved_root(self):
        outside = self.media.parent / "redirected_jobs.sqlite"
        outside.write_bytes(b"")
        linked = self.media / "Jobs" / "redirected_jobs.sqlite"
        try:
            linked.symlink_to(outside)
        except (OSError, NotImplementedError) as exc:
            self.skipTest(f"File symlinks unavailable: {exc}")
        store = Mock(db_path=str(linked))
        with patch("app.video_comfy_collector.configured_video_storage",
                   return_value=Mock(root=self.media, unsafe=True)):
            collector = VideoResultCollector(store, FakeClient(None), self.catalog, self.output)
            with self.assertRaisesRegex(ValueError, "Video job database"):
                collector.collect_one()
        store.awaiting_result.assert_not_called()

    def test_rejects_symlinked_catalog_database_outside_approved_root(self):
        outside = self.media.parent / "redirected_catalog.sqlite"
        outside.write_bytes(b"")
        linked = self.media / "Jobs" / "redirected_catalog.sqlite"
        try:
            linked.symlink_to(outside)
        except (OSError, NotImplementedError) as exc:
            self.skipTest(f"File symlinks unavailable: {exc}")
        catalog = Mock(media_root=self.catalog.media_root, db_path=linked)
        with patch("app.video_comfy_collector.configured_video_storage",
                   return_value=Mock(root=self.media, unsafe=True)):
            collector = VideoResultCollector(self.store, FakeClient(None), catalog, self.output)
            with self.assertRaisesRegex(ValueError, "Media catalog database"):
                collector.collect_one()
        self.assertEqual(self.store.get(self.job_id)["state"], "running")
        catalog.register.assert_not_called()

    def test_rejects_job_database_outside_approved_root(self):
        outside = self.media.parent / "outside_jobs.sqlite"
        store = Mock(db_path=str(outside))
        with patch("app.video_comfy_collector.configured_video_storage",
                   return_value=Mock(root=self.media, unsafe=True)):
            collector = VideoResultCollector(store, FakeClient(None), self.catalog, self.output)
            with self.assertRaisesRegex(ValueError, "Video job database"):
                collector.collect_one()
        store.awaiting_result.assert_not_called()

    def test_rejects_catalog_database_outside_approved_root(self):
        outside = self.media.parent / "outside_catalog.sqlite"
        catalog = Mock(media_root=self.catalog.media_root, db_path=outside)
        with patch("app.video_comfy_collector.configured_video_storage",
                   return_value=Mock(root=self.media, unsafe=True)):
            collector = VideoResultCollector(self.store, FakeClient(None), catalog, self.output)
            with self.assertRaisesRegex(ValueError, "Media catalog database"):
                collector.collect_one()
        catalog.register.assert_not_called()
        self.assertEqual(self.store.get(self.job_id)["state"], "running")

    def test_rejects_output_directory_outside_approved_root(self):
        outputs = {"1": {"videos": [{"type": "output", "filename": "result.mp4", "subfolder": ""}]}}
        outside = self.media.parent / "unapproved"
        outside.mkdir()
        (outside / "result.mp4").write_bytes(bytes.fromhex("000000186674797069736f6d") + b"test video")
        with patch("app.video_comfy_collector.configured_video_storage",
                   return_value=Mock(root=self.media, unsafe=True)):
            collector = VideoResultCollector(self.store, FakeClient(outputs), self.catalog, outside)
            with self.assertRaisesRegex(ValueError, "approved external storage"):
                collector.collect_one()
        self.assertEqual(self.store.get(self.job_id)["state"], "running")
        self.assertEqual(list((self.media / "Media" / "Videos").glob("*.mp4")), [])

    def test_rejects_catalog_directory_outside_approved_root(self):
        outside = self.media.parent / "unapproved_catalog"
        (outside / "Media").mkdir(parents=True)
        catalog = Mock(media_root=outside / "Media")
        with patch("app.video_comfy_collector.configured_video_storage",
                   return_value=Mock(root=self.media, unsafe=True)):
            collector = VideoResultCollector(self.store, FakeClient(None), catalog, self.output)
            with self.assertRaisesRegex(ValueError, "Media catalog must be inside approved external storage"):
                collector.collect_one()
        self.assertEqual(self.store.get(self.job_id)["state"], "running")
        catalog.register.assert_not_called()

    def test_rejects_symlinked_catalog_root_outside_approved_volume(self):
        outside = self.media.parent / "redirected_media"
        outside.mkdir()
        redirected = self.media / "MediaRedirect"
        try:
            redirected.symlink_to(outside, target_is_directory=True)
        except (OSError, NotImplementedError) as exc:
            self.skipTest(f"Directory symlinks unavailable: {exc}")
        catalog = Mock(media_root=redirected)
        with patch("app.video_comfy_collector.configured_video_storage",
                   return_value=Mock(root=self.media, unsafe=True)):
            collector = VideoResultCollector(self.store, FakeClient(None), catalog, self.output)
            with self.assertRaisesRegex(ValueError, "Media catalog must be inside approved external storage"):
                collector.collect_one()
        self.assertEqual(self.store.get(self.job_id)["state"], "running")
        catalog.register.assert_not_called()
        self.assertEqual(list(outside.iterdir()), [])

    def test_rejects_symlinked_video_destination_before_copy(self):
        outside = self.media.parent / "redirected_videos"
        outside.mkdir()
        destination = self.media / "Media" / "Videos"
        destination.rmdir()
        try:
            destination.symlink_to(outside, target_is_directory=True)
        except (OSError, NotImplementedError) as exc:
            self.skipTest(f"Directory symlinks unavailable: {exc}")
        (self.output / "result.mp4").write_bytes(bytes.fromhex("000000186674797069736f6d") + b"test video")
        outputs = {"1": {"videos": [{"type": "output", "filename": "result.mp4", "subfolder": ""}]}}
        with patch("app.video_comfy_collector.configured_video_storage",
                   return_value=Mock(root=self.media, unsafe=True)):
            self.assertIsNone(self.collector(outputs).collect_one())
        self.assertEqual(self.store.get(self.job_id)["state"], "failed")
        self.assertEqual(list(outside.iterdir()), [])

    def test_completed_mp4_is_registered(self):
        (self.output / "result.mp4").write_bytes(b"\x00\x00\x00\x18ftypisomtest video")
        outputs = {"1": {"gifs": [{"type": "output", "filename": "result.mp4", "subfolder": ""}]}}
        with patch("app.video_comfy_collector.configured_video_storage", new_callable=lambda: Mock(return_value=Mock(root=self.media, unsafe=True))) as storage:
            storage.return_value.assert_ready.return_value = None
            media_id = self.collector(outputs).collect_one()
        self.assertIsNotNone(media_id)
        self.assertEqual(self.store.get(self.job_id)["state"], "completed")
        self.assertEqual(self.catalog.resolve(media_id)[0].read_bytes(), b"\x00\x00\x00\x18ftypisomtest video")

    def test_malformed_output_collection_fails_closed(self):
        outputs = {"1": {"gifs": {"filename": "result.mp4"}}}
        with patch("app.video_comfy_collector.configured_video_storage", new_callable=lambda: Mock(return_value=Mock(root=self.media, unsafe=True))):
            self.assertIsNone(self.collector(outputs).collect_one())
        self.assertEqual(self.store.get(self.job_id)["state"], "failed")

    def test_mp4_extension_with_invalid_header_is_rejected(self):
        (self.output / "result.mp4").write_bytes(b"not a video")
        outputs = {"1": {"videos": [{"type": "output", "filename": "result.mp4", "subfolder": ""}]}}
        with patch("app.video_comfy_collector.configured_video_storage", new_callable=lambda: Mock(return_value=Mock(root=self.media, unsafe=True))):
            self.assertIsNone(self.collector(outputs).collect_one())
        self.assertEqual(self.store.get(self.job_id)["state"], "failed")
        self.assertEqual(list((self.media / "Media" / "Videos").glob("*.mp4")), [])

    def test_same_size_output_rewrite_is_rejected(self):
        source = self.output / "result.mp4"
        source.write_bytes(b"\x00\x00\x00\x18ftypisomtest video")
        outputs = {"1": {"videos": [{"type": "output", "filename": "result.mp4", "subfolder": ""}]}}
        import shutil
        import os
        original_copy = shutil.copyfileobj
        def rewriting_copy(src, dst, length):
            original_copy(src, dst, length)
            before = source.stat()
            source.write_bytes(b"\x00\x00\x00\x18ftypisomother data")
            os.utime(source, ns=(before.st_atime_ns, before.st_mtime_ns + 1_000_000_000))
        with patch("app.video_comfy_collector.configured_video_storage", new_callable=lambda: Mock(return_value=Mock(root=self.media, unsafe=True))), patch(
            "app.video_comfy_collector.shutil.copyfileobj", side_effect=rewriting_copy
        ):
            self.assertIsNone(self.collector(outputs).collect_one())
        self.assertEqual(self.store.get(self.job_id)["state"], "failed")
        self.assertEqual(list((self.media / "Media" / "Videos").glob("*.mp4")), [])

    def test_output_growth_during_copy_is_rejected(self):
        source = self.output / "result.mp4"
        source.write_bytes(b"\x00\x00\x00\x18ftypisomtest video")
        outputs = {"1": {"videos": [{"type": "output", "filename": "result.mp4", "subfolder": ""}]}}
        import shutil
        original_copy = shutil.copyfileobj
        def growing_copy(src, dst, length):
            original_copy(src, dst, length)
            with source.open("ab") as handle:
                handle.write(b"new bytes")
        with patch("app.video_comfy_collector.configured_video_storage", new_callable=lambda: Mock(return_value=Mock(root=self.media, unsafe=True))), patch(
            "app.video_comfy_collector.shutil.copyfileobj", side_effect=growing_copy
        ):
            self.assertIsNone(self.collector(outputs).collect_one())
        self.assertEqual(self.store.get(self.job_id)["state"], "failed")
        self.assertEqual(list((self.media / "Media" / "Videos").glob("*.mp4")), [])

    def test_mixed_valid_and_malformed_outputs_fail_closed(self):
        (self.output / "result.mp4").write_bytes(b"\x00\x00\x00\x18ftypisomtest video")
        outputs = {
            "valid": {"videos": [{"type": "output", "filename": "result.mp4", "subfolder": ""}]},
            "malformed": {"gifs": {"filename": "ignored.mp4"}},
        }
        with patch("app.video_comfy_collector.configured_video_storage", new_callable=lambda: Mock(return_value=Mock(root=self.media, unsafe=True))):
            self.assertIsNone(self.collector(outputs).collect_one())
        self.assertEqual(self.store.get(self.job_id)["state"], "failed")
        self.assertEqual(list((self.media / "Media" / "Videos").glob("*.mp4")), [])

    def test_catalog_failure_removes_unregistered_copy(self):
        (self.output / "result.mp4").write_bytes(b"\x00\x00\x00\x18ftypisomtest video")
        outputs = {"1": {"gifs": [{"type": "output", "filename": "result.mp4", "subfolder": ""}]}}
        with patch("app.video_comfy_collector.configured_video_storage", new_callable=lambda: Mock(return_value=Mock(root=self.media, unsafe=True))), patch.object(
            self.catalog, "register", side_effect=ValueError("catalog unavailable")
        ):
            self.assertIsNone(self.collector(outputs).collect_one())
        self.assertEqual(self.store.get(self.job_id)["state"], "failed")
        self.assertEqual(list((self.media / "Media" / "Videos").glob("*.mp4")), [])

    def test_in_place_source_mutation_during_copy_is_rejected(self):
        source = self.output / "result.mp4"
        source.write_bytes(b"\\x00\\x00\\x00\\x18ftypisomtest video")
        outputs = {"1": {"videos": [{"type": "output", "filename": "result.mp4", "subfolder": ""}]}}
        import shutil
        original_copy = shutil.copyfileobj

        def mutate_source(opened_source, destination, length):
            original_copy(opened_source, destination, length)
            with source.open("r+b") as writer:
                writer.seek(12)
                writer.write(b"altered!!!")
                writer.flush()
                import os
                os.fsync(writer.fileno())
            import os
            stat = source.stat()
            os.utime(source, ns=(stat.st_atime_ns, stat.st_mtime_ns + 2_000_000_000))

        with patch("app.video_comfy_collector.configured_video_storage",
                   return_value=Mock(root=self.media, unsafe=True)), patch(
            "app.video_comfy_collector.shutil.copyfileobj", side_effect=mutate_source
        ), patch.object(self.catalog, "register", wraps=self.catalog.register) as register:
            self.assertIsNone(self.collector(outputs).collect_one())
            register.assert_not_called()
        self.assertEqual(self.store.get(self.job_id)["state"], "failed")
        self.assertEqual(list((self.media / "Media" / "Videos").glob("*.mp4")), [])

    def test_in_place_source_mutation_during_copy_is_rejected(self):
        source = self.output / "result.mp4"
        source.write_bytes(b"\\x00\\x00\\x00\\x18ftypisomtest video")
        outputs = {"1": {"videos": [{"type": "output", "filename": "result.mp4", "subfolder": ""}]}}
        import shutil
        original_copy = shutil.copyfileobj

        def mutate_source(src, dst, length):
            original_copy(src, dst, length)
            with source.open("r+b") as handle:
                handle.seek(12)
                handle.write(b"changed!!!")
                handle.flush()
            import os
            stat = source.stat()
            os.utime(source, ns=(stat.st_atime_ns, stat.st_mtime_ns + 2_000_000_000))

        with patch("app.video_comfy_collector.configured_video_storage",
                   return_value=Mock(root=self.media, unsafe=True)), patch(
            "app.video_comfy_collector.shutil.copyfileobj", side_effect=mutate_source
        ), patch.object(self.catalog, "register", wraps=self.catalog.register) as register:
            self.assertIsNone(self.collector(outputs).collect_one())
        register.assert_not_called()
        self.assertEqual(self.store.get(self.job_id)["state"], "failed")
        self.assertEqual(list((self.media / "Media" / "Videos").glob("*.mp4")), [])

    def test_copy_failure_removes_partial_file(self):
        (self.output / "result.mp4").write_bytes(b"\x00\x00\x00\x18ftypisomtest video")
        outputs = {"1": {"gifs": [{"type": "output", "filename": "result.mp4", "subfolder": ""}]}}
        from unittest.mock import patch as mock_patch
        def interrupted_copy(source, destination, length):
            destination.write(b"partial")
            raise OSError("disk full")
        with mock_patch("app.video_comfy_collector.configured_video_storage", new_callable=lambda: Mock(return_value=Mock(root=self.media, unsafe=True))), mock_patch(
            "app.video_comfy_collector.shutil.copyfileobj", side_effect=interrupted_copy
        ):
            self.assertIsNone(self.collector(outputs).collect_one())
        self.assertEqual(self.store.get(self.job_id)["state"], "failed")
        self.assertEqual(list((self.media / "Media" / "Videos").glob("*.mp4")), [])

    def test_pending_output_remains_running(self):
        with patch("app.video_comfy_collector.configured_video_storage", new_callable=lambda: Mock(return_value=Mock(root=self.media, unsafe=True))):
            self.assertIsNone(self.collector(None).collect_one())
        self.assertEqual(self.store.get(self.job_id)["state"], "running")

    def test_windows_separator_in_filename_is_rejected(self):
        # A backslash is a path separator on Windows, even when Linux accepts it in a name.
        outputs = {"1": {"videos": [{"type": "output", "filename": "nested\\\\result.mp4", "subfolder": ""}]}}
        with patch("app.video_comfy_collector.configured_video_storage", new_callable=lambda: Mock(return_value=Mock(root=self.media, unsafe=True))):
            self.assertIsNone(self.collector(outputs).collect_one())
        self.assertEqual(self.store.get(self.job_id)["state"], "failed")

    def test_path_traversal_is_rejected(self):
        outputs = {"1": {"gifs": [{"type": "output", "filename": "bad.mp4", "subfolder": "../"}]}}
        with patch("app.video_comfy_collector.configured_video_storage", new_callable=lambda: Mock(return_value=Mock(root=self.media, unsafe=True))):
            self.assertIsNone(self.collector(outputs).collect_one())
        self.assertEqual(self.store.get(self.job_id)["state"], "failed")


if __name__ == "__main__":
    unittest.main()
