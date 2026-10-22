"""Tests for the image executor using a deterministic fake renderer."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.image_job_store import ImageJobStore
from app.image_media_store import ExternalMediaStore, MediaStorageError
from app.image_job_runner import ImageJobRunner, RenderedImage


class ImageRunnerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.jobs = ImageJobStore(str(root / "jobs.sqlite3"))
        mount_patch = patch("app.image_media_store.os.path.ismount", return_value=True)
        mount_patch.start()
        self.addCleanup(mount_patch.stop)
        self.media = ExternalMediaStore(str(root), [str(root)], min_free_bytes=0)

    def test_successful_render(self):
        job = self.jobs.submit("client-a", "blue elephant")
        runner = ImageJobRunner(self.jobs, self.media,
                                lambda prompt: RenderedImage(b"fixture" + prompt.encode()))
        result = runner.run_one()
        self.assertEqual(result["state"], "completed")
        self.assertEqual(self.jobs.get(job["job_id"], "client-a")["state"], "completed")
        self.assertEqual(self.media.resolve(result["asset_id"], ".png").read_bytes(),
                         b"fixtureblue elephant")
        self.assertIsNone(runner.run_one())

    def test_renderer_failure(self):
        job = self.jobs.submit("client-a", "prompt")
        def broken(_prompt):
            raise RuntimeError("sensitive renderer failure")
        result = ImageJobRunner(self.jobs, self.media, broken).run_one()
        self.assertEqual(result["state"], "failed")
        stored = self.jobs.get(job["job_id"], "client-a")
        self.assertEqual(stored["error"], "image_generation_failed")
        self.assertNotIn("sensitive", stored["error"])

    def test_storage_loss_stops_executor_without_fallback(self):
        job = self.jobs.submit("client-a", "prompt")
        def missing_disk(_prompt):
            raise MediaStorageError("external drive disappeared")
        with self.assertRaises(MediaStorageError):
            ImageJobRunner(self.jobs, self.media, missing_disk).run_one()
        self.assertEqual(self.jobs.get(job["job_id"], "client-a")["state"], "running")
        self.assertEqual(self.jobs.recover_interrupted(), 1)
        self.assertEqual(self.jobs.get(job["job_id"], "client-a")["state"], "failed")

    def test_invalid_renderer_output(self):
        self.jobs.submit("client-a", "prompt")
        result = ImageJobRunner(self.jobs, self.media, lambda _: None).run_one()
        self.assertEqual(result["state"], "failed")


if __name__ == "__main__":
    unittest.main()
