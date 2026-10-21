"""Image job state machine tests, without GPU or HTTP dependencies."""
import tempfile
import unittest
from pathlib import Path

from app.image_job_store import ImageJobError, ImageJobStore


class ImageJobTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.db = str(Path(self.temp.name) / "jobs.sqlite3")
        self.store = ImageJobStore(self.db)

    def test_submit_claim_complete(self):
        job = self.store.submit("device-a", "blue elephant")
        self.assertEqual(self.store.claim()["id"], job["job_id"])
        self.assertTrue(self.store.finish(job["job_id"], asset_id="a" * 32))
        self.assertEqual(self.store.get(job["job_id"], "device-a")["state"], "completed")
        self.assertIsNone(self.store.get(job["job_id"], "device-b"))
        self.assertFalse(self.store.finish(job["job_id"], asset_id="b" * 32))

    def test_cancel_queued_only(self):
        job = self.store.submit("a", "test")
        self.assertFalse(self.store.cancel(job["job_id"], "b"))
        self.assertTrue(self.store.cancel(job["job_id"], "a"))
        self.assertIsNone(self.store.claim())

    def test_restart_recovery(self):
        job = self.store.submit("a", "test")
        self.store.claim()
        reopened = ImageJobStore(self.db)
        self.assertEqual(reopened.recover_interrupted(), 1)
        self.assertEqual(reopened.get(job["job_id"], "a")["state"], "failed")
        self.assertEqual(reopened.recover_interrupted(), 0)

    def test_queue_limit(self):
        self.store.submit("a", "first", max_queued=1)
        with self.assertRaises(ImageJobError):
            self.store.submit("a", "second", max_queued=1)

    def test_invalid_prompt(self):
        with self.assertRaises(ImageJobError):
            self.store.submit("a", " ")
        with self.assertRaises(ImageJobError):
            self.store.submit("a", "x" * 4001)


if __name__ == "__main__":
    unittest.main()
