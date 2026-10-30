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



GPU_A = "GPU-6a7f0c2e-1b2d-4c3e-8f9a-0123456789ab"
GPU_B = "GPU-7b8f1d3f-2c3e-4d4f-9a0b-1234567890bc"
A1, A2, B1 = GPU_A + ":" + "a" * 16, GPU_A + ":" + "b" * 16, GPU_B + ":" + "c" * 16


class ExecutorProtocolTests(unittest.TestCase):
    """G2 (#2296): claims scoped to profiles and instances, the publication commit point, recovery."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.db = str(Path(self.temp.name) / "jobs.sqlite3")
        self.store = ImageJobStore(self.db)

    def job(self, profile="sdxl-a", owner="anders"):
        return self.store.submit(owner, "a red bicycle", profile_id=profile, max_owner_active=16)["job_id"]

    def row(self, job_id, owner="anders"):
        return self.store.get(job_id, owner)

    def test_the_migration_adds_columns_to_an_existing_database_without_touching_rows(self):
        legacy = str(Path(self.temp.name) / "legacy.sqlite3")
        with sqlite3.connect(legacy) as db:
            db.execute("""CREATE TABLE image_jobs (id TEXT PRIMARY KEY, owner TEXT NOT NULL, prompt TEXT NOT NULL,
                profile_id TEXT NOT NULL, params TEXT NOT NULL, state TEXT NOT NULL, created REAL NOT NULL,
                updated REAL NOT NULL, asset_id TEXT, error TEXT)""")
            db.execute("INSERT INTO image_jobs VALUES ('j1','anders','p','sdxl-a','{}','completed',1,1,'asset','')")
        store = ImageJobStore(legacy)
        ImageJobStore(legacy)  # idempotent
        row = store.get("j1", "anders")
        self.assertEqual((row["state"], row["asset_id"], row["claimed_by"], row["cancel_requested"]),
                         ("completed", "asset", None, 0))

    def test_claim_for_takes_only_the_listed_profiles_and_records_the_instance(self):
        other = self.job("sdxl-b")
        mine = self.job("sdxl-a")
        claimed = self.store.claim_for(["sdxl-a"], A1)
        self.assertEqual((claimed["id"], claimed["claimed_by"]), (mine, A1))
        self.assertEqual(self.row(other)["state"], "queued")
        self.assertIsNone(self.store.claim_for(["sdxl-a"], A1))

    def test_instance_ids_and_profile_ids_are_validated(self):
        self.job()
        for bad in ("worker", GPU_A, GPU_A + ":short", "GPU-x:" + "a" * 16, None):
            with self.subTest(bad=bad), self.assertRaises(ImageJobError):
                self.store.claim_for(["sdxl-a"], bad)
        with self.assertRaises(ImageJobError):
            self.store.claim_for([], A1)
        with self.assertRaises(ImageJobError):
            self.store.claim_for(["Bad Profile"], A1)

    def test_recovery_fails_only_this_gpus_dead_instances_and_flags_publication(self):
        running_a, publishing_a, running_b, live = self.job(), self.job(), self.job("sdxl-b"), self.job()
        self.store.claim_for(["sdxl-a"], A1)          # running_a
        self.store.claim_for(["sdxl-a"], A1)          # publishing_a
        self.store.begin_publish(publishing_a, A1)
        self.store.claim_for(["sdxl-b"], B1)          # another GPU's job
        self.store.claim_for(["sdxl-a"], A2)          # 'live' claimed by the new instance itself
        self.assertEqual(self.store.recover_gpu(GPU_A, A2), 2)
        self.assertEqual((self.row(running_a)["state"], self.row(running_a)["error"]), ("failed", "interrupted by restart"))
        self.assertEqual(self.row(publishing_a)["error"], "interrupted during publication")
        self.assertEqual(self.row(running_b)["state"], "running", "another GPU's job is untouched")
        self.assertEqual(self.row(live)["state"], "running", "the recovering instance's own claim is untouched")
        with self.assertRaises(ImageJobError):
            self.store.recover_gpu(GPU_B, A2)

    def test_cancel_answers_and_the_commit_point(self):
        queued, running, publishing = self.job(), self.job(), self.job()
        self.store.claim_for(["sdxl-a"], A1)  # queued is oldest: claim it, then the others
        self.store.claim_for(["sdxl-a"], A1)
        self.store.claim_for(["sdxl-a"], A1)
        self.store.begin_publish(publishing, A1)
        # 'queued' was claimed too; submit a fresh one to test the queued answer
        fresh = self.job()
        self.assertEqual(self.store.request_cancel(fresh, "anders"), "cancelled")
        self.assertEqual(self.store.request_cancel(running, "anders"), "requested")
        self.assertEqual(self.store.request_cancel(publishing, "anders"), "too_late")
        self.assertIsNone(self.store.request_cancel(running, "someone-else"))
        self.assertTrue(self.store.cancel_requested(running, A1))
        self.assertFalse(self.store.begin_publish(running, A1), "a requested cancel wins at the commit point")
        self.assertTrue(self.store.finish_cancelled(running, A1))
        self.assertEqual(self.row(running)["state"], "cancelled")
        self.assertTrue(self.store.complete(publishing, A1, "asset1"))
        self.assertEqual(self.row(queued)["state"], "running")

    def test_transitions_require_the_claiming_instance_and_the_right_state(self):
        job = self.job()
        self.store.claim_for(["sdxl-a"], A1)
        self.assertFalse(self.store.complete(job, A1, "asset"), "complete only from publishing")
        self.assertFalse(self.store.begin_publish(job, A2), "another instance cannot publish it")
        self.assertFalse(self.store.fail(job, A2, "generation_failed"))
        self.assertFalse(self.store.finish_cancelled(job, A2))
        self.assertTrue(self.store.begin_publish(job, A1))
        self.assertFalse(self.store.finish_cancelled(job, A1), "past the commit point a job is not cancelled")
        self.assertTrue(self.store.fail(job, A1, "generation_failed"), "fail is allowed from publishing")
        self.assertEqual(self.row(job)["error"], "generation_failed")

    def test_publishing_counts_toward_the_owner_limit(self):
        job = self.store.submit("anders", "x", profile_id="sdxl-a", max_owner_active=1)["job_id"]
        self.store.claim_for(["sdxl-a"], A1)
        self.store.begin_publish(job, A1)
        with self.assertRaisesRegex(ImageJobError, "owner image job limit"):
            self.store.submit("anders", "y", profile_id="sdxl-a", max_owner_active=1)
        self.store.complete(job, A1, "asset")
        self.store.submit("anders", "y", profile_id="sdxl-a", max_owner_active=1)


if __name__ == "__main__":
    unittest.main()
