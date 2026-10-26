"""Image job state machine tests, without GPU or HTTP dependencies."""
import tempfile
import sqlite3
from unittest.mock import patch
import unittest
from pathlib import Path

from app.image_job_store import ImageJobError, ImageJobStore


class ImageJobTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.db = str(Path(self.temp.name) / "jobs.sqlite3")
        self.store = ImageJobStore(self.db)

    def test_volume_guard_blocks_database_access_after_unmount(self):
        from app.image_media_store import MediaStorageError
        mounted = [True]

        def guard():
            if not mounted[0]:
                raise MediaStorageError("external volume disappeared")

        guarded = ImageJobStore(self.db, volume_guard=guard)
        guarded.submit("device-a", "before unmount")
        mounted[0] = False
        for operation in (
            lambda: guarded.submit("device-a", "after unmount"),
            lambda: guarded.claim(),
            lambda: guarded.get("a" * 32, "device-a"),
            lambda: guarded.recover_interrupted(),
        ):
            with self.assertRaises(MediaStorageError):
                operation()

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

    def test_owner_quota_isolated(self):
        self.store.submit("a", "first", max_owner_active=1)
        with self.assertRaises(ImageJobError):
            self.store.submit("a", "second", max_owner_active=1)
        other = self.store.submit("b", "other", max_owner_active=1)
        self.assertEqual(self.store.get(other["job_id"], "b")["state"], "queued")

    def test_running_job_counts_toward_owner_limit(self):
        self.store.submit("a", "first", max_owner_active=1)
        self.store.claim()
        with self.assertRaises(ImageJobError):
            self.store.submit("a", "second", max_owner_active=1)

    def test_sqlite_connections_close_on_success_and_error(self):
        real_connect = sqlite3.connect
        connections = []

        class TrackedConnection(sqlite3.Connection):
            def close(self):
                connections.append("closed")
                super().close()

        with patch("app.image_job_store.sqlite3.connect",
                   side_effect=lambda *args, **kwargs: real_connect(
                       *args, **kwargs, factory=TrackedConnection)):
            job = self.store.submit("a", "first", max_queued=1)
            self.assertEqual(self.store.get(job["job_id"], "a")["state"], "queued")
            with self.assertRaises(ImageJobError):
                self.store.submit("a", "second", max_queued=1)
        self.assertEqual(len(connections), 3)

    def test_invalid_owner(self):
        for owner in (None, 42, "", " ", "x" * 257):
            with self.subTest(owner=owner):
                with self.assertRaises(ImageJobError):
                    self.store.submit(owner, "prompt")

    def test_invalid_prompt(self):
        with self.assertRaises(ImageJobError):
            self.store.submit("a", " ")
        with self.assertRaises(ImageJobError):
            self.store.submit("a", "x" * 4001)


if __name__ == "__main__":
    unittest.main()
