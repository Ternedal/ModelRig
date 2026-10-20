"""Offline tests for the one-shot ComfyUI video result collector."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

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
        self.output = root / "comfy"
        self.output.mkdir()
        self.media = root / "external"
        (self.media / "Media" / "Videos").mkdir(parents=True)
        (self.media / "Jobs").mkdir()
        self.store = VideoJobStore(self.media / "Jobs" / "video_jobs.sqlite")
        self.catalog = MediaCatalog(self.media)
        self.job_id = self.store.create(VideoRequest(kind="text_to_video", prompt="Clouds"))
        self.assertTrue(self.store.transition(self.job_id, "queued", "running"))
        self.assertTrue(self.store.record_prompt(self.job_id, "prompt_1"))

    def collector(self, outputs):
        return VideoResultCollector(self.store, FakeClient(outputs), self.catalog, self.output)

    def test_completed_mp4_is_registered(self):
        (self.output / "result.mp4").write_bytes(b"test video")
        outputs = {"1": {"gifs": [{"type": "output", "filename": "result.mp4", "subfolder": ""}]}}
        with patch("app.video_comfy_collector.configured_video_storage") as storage:
            storage.return_value.assert_ready.return_value = None
            media_id = self.collector(outputs).collect_one()
        self.assertIsNotNone(media_id)
        self.assertEqual(self.store.get(self.job_id)["state"], "completed")
        self.assertEqual(self.catalog.resolve(media_id)[0].read_bytes(), b"test video")

    def test_malformed_output_collection_fails_closed(self):
        outputs = {"1": {"gifs": {"filename": "result.mp4"}}}
        with patch("app.video_comfy_collector.configured_video_storage"):
            self.assertIsNone(self.collector(outputs).collect_one())
        self.assertEqual(self.store.get(self.job_id)["state"], "failed")

    def test_catalog_failure_removes_unregistered_copy(self):
        (self.output / "result.mp4").write_bytes(b"test video")
        outputs = {"1": {"gifs": [{"type": "output", "filename": "result.mp4", "subfolder": ""}]}}
        with patch("app.video_comfy_collector.configured_video_storage"), patch.object(
            self.catalog, "register", side_effect=ValueError("catalog unavailable")
        ):
            self.assertIsNone(self.collector(outputs).collect_one())
        self.assertEqual(self.store.get(self.job_id)["state"], "failed")
        self.assertEqual(list((self.media / "Media" / "Videos").glob("*.mp4")), [])

    def test_copy_failure_removes_partial_file(self):
        (self.output / "result.mp4").write_bytes(b"test video")
        outputs = {"1": {"gifs": [{"type": "output", "filename": "result.mp4", "subfolder": ""}]}}
        from unittest.mock import patch as mock_patch
        def interrupted_copy(source, destination, length):
            destination.write(b"partial")
            raise OSError("disk full")
        with mock_patch("app.video_comfy_collector.configured_video_storage"), mock_patch(
            "app.video_comfy_collector.shutil.copyfileobj", side_effect=interrupted_copy
        ):
            self.assertIsNone(self.collector(outputs).collect_one())
        self.assertEqual(self.store.get(self.job_id)["state"], "failed")
        self.assertEqual(list((self.media / "Media" / "Videos").glob("*.mp4")), [])

    def test_pending_output_remains_running(self):
        with patch("app.video_comfy_collector.configured_video_storage"):
            self.assertIsNone(self.collector(None).collect_one())
        self.assertEqual(self.store.get(self.job_id)["state"], "running")

    def test_path_traversal_is_rejected(self):
        outputs = {"1": {"gifs": [{"type": "output", "filename": "bad.mp4", "subfolder": "../"}]}}
        with patch("app.video_comfy_collector.configured_video_storage"):
            self.assertIsNone(self.collector(outputs).collect_one())
        self.assertEqual(self.store.get(self.job_id)["state"], "failed")


if __name__ == "__main__":
    unittest.main()
