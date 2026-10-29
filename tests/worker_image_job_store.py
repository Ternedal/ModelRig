"""Image job state machine tests, without GPU or HTTP dependencies.

Ported from worker/tests/test_image_job_store.py on
fix/image-job-quota-type-20261029 (ChatGPT hardening, 87a522d5). Changes for
ModelRig #2296: every job names a profile_id; the volume guard is any callable
(the media store is ChatGPT's slice, so this test uses its own exception).
"""
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
        self.submit = lambda owner, prompt, **kw: self.store.submit(owner, prompt, profile_id="test-profile", **kw)

    def test_volume_guard_blocks_database_access_after_unmount(self):
        class MediaStorageError(RuntimeError):
            pass
        mounted = [True]

        def guard():
            if not mounted[0]:
                raise MediaStorageError("external volume disappeared")

        guarded = ImageJobStore(self.db, volume_guard=guard)
        guarded.submit("device-a", "before unmount", profile_id="test-profile")
        mounted[0] = False
        for operation in (
            lambda: guarded.submit("device-a", "after unmount", profile_id="test-profile"),
            lambda: guarded.claim(),
            lambda: guarded.get("a" * 32, "device-a"),
            lambda: guarded.recover_interrupted(),
        ):
            with self.assertRaises(MediaStorageError):
                operation()

    def test_submit_claim_complete(self):
        job = self.submit("device-a", "blue elephant")
        self.assertEqual(self.store.claim()["id"], job["job_id"])
        self.assertTrue(self.store.finish(job["job_id"], asset_id="a" * 32))
        self.assertEqual(self.store.get(job["job_id"], "device-a")["state"], "completed")
        self.assertIsNone(self.store.get(job["job_id"], "device-b"))
        self.assertFalse(self.store.finish(job["job_id"], asset_id="b" * 32))

    def test_cancel_queued_only(self):
        job = self.submit("a", "test")
        self.assertFalse(self.store.cancel(job["job_id"], "b"))
        self.assertTrue(self.store.cancel(job["job_id"], "a"))
        self.assertIsNone(self.store.claim())

    def test_restart_recovery(self):
        job = self.submit("a", "test")
        self.store.claim()
        reopened = ImageJobStore(self.db)
        self.assertEqual(reopened.recover_interrupted(), 1)
        self.assertEqual(reopened.get(job["job_id"], "a")["state"], "failed")
        self.assertEqual(reopened.recover_interrupted(), 0)

    def test_queue_limit(self):
        self.submit("a", "first", max_queued=1)
        with self.assertRaises(ImageJobError):
            self.submit("a", "second", max_queued=1)

    def test_rejects_non_integer_queue_limits(self):
        for value in (True, False, 1.5, "2", None, [], {}):
            with self.subTest(value=value):
                with self.assertRaises(ImageJobError):
                    self.submit("a", "prompt", max_queued=value)
                with self.assertRaises(ImageJobError):
                    self.submit("a", "prompt", max_owner_active=value)
        self.assertIsNone(self.store.claim())

    def test_owner_quota_isolated(self):
        self.submit("a", "first", max_owner_active=1)
        with self.assertRaises(ImageJobError):
            self.submit("a", "second", max_owner_active=1)
        other = self.submit("b", "other", max_owner_active=1)
        self.assertEqual(self.store.get(other["job_id"], "b")["state"], "queued")

    def test_running_job_counts_toward_owner_limit(self):
        self.submit("a", "first", max_owner_active=1)
        self.store.claim()
        with self.assertRaises(ImageJobError):
            self.submit("a", "second", max_owner_active=1)

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
            job = self.submit("a", "first", max_queued=1)
            self.assertEqual(self.store.get(job["job_id"], "a")["state"], "queued")
            with self.assertRaises(ImageJobError):
                self.submit("a", "second", max_queued=1)
        self.assertEqual(len(connections), 3)

    def test_invalid_owner(self):
        for owner in (None, 42, "", " ", "x" * 257):
            with self.subTest(owner=owner):
                with self.assertRaises(ImageJobError):
                    self.submit(owner, "prompt")

    def test_invalid_prompt(self):
        with self.assertRaises(ImageJobError):
            self.submit("a", " ")
        with self.assertRaises(ImageJobError):
            self.submit("a", "x" * 4001)


    def test_profile_id_is_required_and_validated(self):
        with self.assertRaises(TypeError):
            self.store.submit("a", "prompt")
        for profile_id in (None, 1, "", "Upper", "has space", "-lead", "x" * 49, "../etc"):
            with self.subTest(profile_id=profile_id), self.assertRaises(ImageJobError):
                self.store.submit("a", "prompt", profile_id=profile_id)
        self.assertIsNone(self.store.claim())

    def test_params_are_bounded_scalars_and_stored(self):
        job = self.store.submit("a", "prompt", profile_id="sdxl-base",
                                params={"width": 1024, "height": 1024, "steps": 30, "task": "text_to_image"})
        claimed = self.store.claim()
        self.assertEqual(claimed["id"], job["job_id"])
        self.assertEqual(claimed["profile_id"], "sdxl-base")
        self.assertEqual(claimed["params"], '{"height":1024,"steps":30,"task":"text_to_image","width":1024}')
        bad = ({"w": 1.5}, {"w": True}, {"w": [1]}, {"w": {"x": 1}}, {"Bad": 1}, {"w": "x" * 257},
               {f"k{i}": 1 for i in range(17)}, "not-a-dict", [("w", 1)])
        for params in bad:
            with self.subTest(params=params), self.assertRaises(ImageJobError):
                self.store.submit("b", "prompt", profile_id="sdxl-base", params=params)


if __name__ == "__main__":
    unittest.main()
