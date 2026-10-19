"""Offline tests for durable video job lifecycle."""
import tempfile
import unittest
from pathlib import Path

from app.video_contract import VideoRequest
from app.video_job_store import VideoJobStore


class VideoJobStoreTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        self.path = Path(self.tempdir.name) / "video.sqlite"
        self.store = VideoJobStore(self.path)
        self.request = VideoRequest(kind="text_to_video", prompt="Rain")

    def test_create_and_reopen(self):
        job_id = self.store.create(self.request)
        self.assertEqual(VideoJobStore(self.path).get(job_id)["state"], "queued")

    def test_successful_lifecycle(self):
        job_id = self.store.create(self.request)
        self.assertTrue(self.store.transition(job_id, "queued", "running"))
        self.assertTrue(self.store.transition(job_id, "running", "completed", artifact_id="asset_1"))
        self.assertEqual(self.store.get(job_id)["artifact_id"], "asset_1")

    def test_stale_transition_does_not_overwrite(self):
        job_id = self.store.create(self.request)
        self.assertTrue(self.store.transition(job_id, "queued", "cancelled"))
        self.assertFalse(self.store.transition(job_id, "queued", "running"))
        self.assertEqual(self.store.get(job_id)["state"], "cancelled")

    def test_invalid_transition_and_artifact(self):
        job_id = self.store.create(self.request)
        with self.assertRaises(ValueError):
            self.store.transition(job_id, "queued", "completed", artifact_id="ok")
        self.assertTrue(self.store.transition(job_id, "queued", "running"))
        with self.assertRaises(ValueError):
            self.store.transition(job_id, "running", "completed", artifact_id="../bad")

    def test_queue_excludes_cancelled(self):
        first = self.store.create(self.request)
        second = self.store.create(self.request)
        self.assertTrue(self.store.transition(first, "queued", "cancelled"))
        self.assertEqual([job["job_id"] for job in self.store.queued()], [second])


if __name__ == "__main__":
    unittest.main()
