"""Image job state machine tests, without GPU or HTTP dependencies.

Ported from worker/tests/test_image_job_store.py on
fix/image-job-quota-type-20261029 (ChatGPT hardening, 87a522d5). Changes for
ModelRig #2296: every job names a profile_id; the volume guard is any callable
(the media store is ChatGPT's slice, so this test uses its own exception).
"""
import tempfile
import time
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

    # --- G4 (Anders 5 Nov 2026): chat first, media waits for VRAM ---------------------------------
    def claimed(self, instance=A1):
        job = self.job()
        self.assertEqual(self.store.claim_for(["sdxl-a"], instance)["id"], job)
        return job

    def test_a_deferred_job_is_queued_again_and_remembers_when_it_first_waited(self):
        job = self.claimed()
        self.assertEqual(self.store.defer(job, A1, max_wait_s=600, error="gpu_unavailable", now=1000.0), "requeued")
        row = self.row(job)
        self.assertEqual((row["state"], row["claimed_by"], row["deferred_since"]), ("queued", None, 1000.0))
        self.assertEqual(self.store.claim_for(["sdxl-a"], A1)["id"], job, "claimable again")
        self.assertEqual(self.store.defer(job, A1, max_wait_s=600, error="gpu_unavailable", now=1300.0), "requeued")
        self.assertEqual(self.row(job)["deferred_since"], 1000.0, "the first deferral counts")

    def test_a_job_that_waited_too_long_fails(self):
        job = self.claimed()
        self.store.defer(job, A1, max_wait_s=600, error="gpu_unavailable", now=1000.0)
        self.store.claim_for(["sdxl-a"], A1)
        self.assertEqual(self.store.defer(job, A1, max_wait_s=600, error="gpu_unavailable", now=1600.0), "expired")
        row = self.row(job)
        self.assertEqual((row["state"], row["error"]), ("failed", "gpu_unavailable"))

    def test_a_cancel_requested_while_running_wins_over_requeueing(self):
        job = self.claimed()
        self.assertEqual(self.store.request_cancel(job, "anders"), "requested")
        self.assertEqual(self.store.defer(job, A1, max_wait_s=600, error="gpu_unavailable"), "cancelled")
        self.assertEqual(self.row(job)["state"], "cancelled", "never back in the queue to run anyway")

    def test_only_the_claiming_instance_can_defer(self):
        job = self.claimed()
        self.assertEqual(self.store.defer(job, A2, max_wait_s=600, error="gpu_unavailable"), "gone")
        self.assertEqual(self.row(job)["state"], "running")
        for bad in ({"max_wait_s": -1, "error": "x"}, {"max_wait_s": "600", "error": "x"}, {"max_wait_s": 600, "error": ""}):
            with self.subTest(bad=bad), self.assertRaises(ImageJobError):
                self.store.defer(job, A1, **bad)

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

    def test_concurrent_initialisers_serialise_the_migration(self):
        """#2318 review 4420958348: two initialisers that both read the schema before either
        migrates must not both ALTER. A barrier at the schema read makes the race deterministic."""
        import threading
        import app.image_job_store as module
        legacy = str(Path(self.temp.name) / "racing.sqlite3")
        with sqlite3.connect(legacy) as db:
            db.execute("""CREATE TABLE image_jobs (id TEXT PRIMARY KEY, owner TEXT NOT NULL, prompt TEXT NOT NULL,
                profile_id TEXT NOT NULL, params TEXT NOT NULL, state TEXT NOT NULL, created REAL NOT NULL,
                updated REAL NOT NULL, asset_id TEXT, error TEXT)""")
        barrier = threading.Barrier(2, timeout=1.0)
        real_connect = sqlite3.connect

        class AtSchemaRead:
            def __init__(self, connection):
                object.__setattr__(self, "_c", connection)

            def __getattr__(self, name):
                return getattr(self._c, name)

            def __setattr__(self, name, value):
                setattr(self._c, name, value)

            def execute(self, sql, *args):
                if sql.startswith("PRAGMA table_info"):
                    try:
                        barrier.wait()  # both initialisers meet here unless the first holds the write lock
                    except threading.BrokenBarrierError:
                        pass
                return self._c.execute(sql, *args)

            def __enter__(self):
                self._c.__enter__()
                return self

            def __exit__(self, *exc):
                return self._c.__exit__(*exc)

        errors = []

        def initialise():
            try:
                ImageJobStore(legacy)
            except Exception as exc:  # noqa: BLE001 - recorded for the assertion
                errors.append(f"{type(exc).__name__}: {exc}")

        with patch.object(module.sqlite3, "connect", lambda *a, **k: AtSchemaRead(real_connect(*a, **k))):
            threads = [threading.Thread(target=initialise) for _ in range(2)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(30)
        self.assertEqual(errors, [], "both initialisers succeed; neither hits 'duplicate column'")
        with sqlite3.connect(legacy) as db:
            columns = [row[1] for row in db.execute("PRAGMA table_info(image_jobs)")]
        self.assertEqual((columns.count("claimed_by"), columns.count("cancel_requested")), (1, 1))

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


class PromptRetentionTests(unittest.TestCase):
    """Anders' decision (5 Nov 2026): the prompt of a finished job is blanked after 30 days."""
    DAY = 24 * 3600

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.db = str(Path(self.temp.name) / "jobs.sqlite3")
        self.store = ImageJobStore(self.db)

    def job(self, state, prompt):
        job_id = self.store.submit("anders", prompt, profile_id="test-profile", max_owner_active=16)["job_id"]
        with sqlite3.connect(self.db) as db:  # set the state directly: this tests retention, not transitions
            db.execute("UPDATE image_jobs SET state=?, asset_id=? WHERE id=?",
                       (state, "a" * 32 if state == "completed" else None, job_id))
        return job_id

    def prompts(self):
        with sqlite3.connect(self.db) as db:
            return dict(db.execute("SELECT state, prompt FROM image_jobs").fetchall())

    def test_the_default_is_thirty_days(self):
        from app.image_job_store import PROMPT_RETENTION_S
        self.assertEqual(PROMPT_RETENTION_S, 30 * self.DAY)

    def test_only_finished_jobs_older_than_the_window_lose_their_prompt(self):
        ids = {state: self.job(state, f"prompt of the {state} job")
               for state in ("queued", "running", "publishing", "completed", "failed", "cancelled")}
        self.assertEqual(self.store.purge_prompts(now=time.time() + 29 * self.DAY), 0, "inside the window")
        self.assertEqual(self.store.purge_prompts(now=time.time() + 31 * self.DAY), 3)
        prompts = self.prompts()
        for state in ("completed", "failed", "cancelled"):
            self.assertEqual(prompts[state], "", state)
        for state in ("queued", "running", "publishing"):
            self.assertEqual(prompts[state], f"prompt of the {state} job", "still needed")
        row = self.store.get(ids["completed"], "anders")
        self.assertEqual((row["state"], row["asset_id"]), ("completed", "a" * 32), "the row itself stays")
        self.assertEqual(self.store.purge_prompts(now=time.time() + 31 * self.DAY), 0, "idempotent")

    def test_the_old_text_is_not_left_in_the_database_file(self):
        # Some SQLite builds have secure_delete on by default, others not: start every connection
        # with it OFF, so only the store's own PRAGMA can remove the old text from the file.
        real_connect = sqlite3.connect

        def off_by_default(*args, **kwargs):
            connection = real_connect(*args, **kwargs)
            connection.execute("PRAGMA secure_delete=OFF")
            return connection
        marker = "kaliv-retention-probe-7f3a91"
        with patch("app.image_job_store.sqlite3.connect", off_by_default):
            for i in range(3):
                self.job("queued", f"neighbour {i} " + "x" * 40)
            self.job("completed", f"a bicycle {marker} " + "m" * 100)
            for i in range(3):
                self.job("queued", f"neighbour after {i} " + "y" * 40)
            self.assertIn(marker.encode(), Path(self.db).read_bytes())
            self.store.purge_prompts(now=time.time() + 31 * self.DAY)
        self.assertNotIn(marker.encode(), Path(self.db).read_bytes(), "secure_delete overwrote it")

    def test_in_wal_mode_the_old_text_is_not_left_in_the_wal_file_either(self):
        # Another connection (a route, a tool) may have switched the database to WAL.
        with sqlite3.connect(self.db) as db:
            self.assertEqual(db.execute("PRAGMA journal_mode=WAL").fetchone()[0], "wal")
        marker = "kaliv-wal-probe-41c2"
        real_connect = sqlite3.connect

        def off_by_default(*args, **kwargs):
            connection = real_connect(*args, **kwargs)
            connection.execute("PRAGMA secure_delete=OFF")
            return connection
        keep_open = sqlite3.connect(self.db)  # a reader that keeps the WAL from being removed on close
        self.addCleanup(keep_open.close)
        with patch("app.image_job_store.sqlite3.connect", off_by_default):
            self.job("completed", f"a bicycle {marker} " + "m" * 100)
            files = lambda: b"".join(Path(p).read_bytes() for p in (self.db, self.db + "-wal") if Path(p).exists())
            self.assertIn(marker.encode(), files())
            self.store.purge_prompts(now=time.time() + 31 * self.DAY)
        self.assertNotIn(marker.encode(), files(), "neither the database nor its WAL keeps the old text")

    @staticmethod
    def secure_delete_off_by_default():
        """Some SQLite builds have secure_delete on by default, others not: start every connection
        with it OFF, so only the store's own PRAGMAs can keep old text out of the file."""
        real_connect = sqlite3.connect

        def off_by_default(*args, **kwargs):
            connection = real_connect(*args, **kwargs)
            connection.execute("PRAGMA secure_delete=OFF")
            return connection
        return patch("app.image_job_store.sqlite3.connect", off_by_default)

    def test_every_store_connection_has_secure_delete_on(self):
        with self.secure_delete_off_by_default(), self.store._db() as db:
            self.assertEqual(db.execute("PRAGMA secure_delete").fetchone()[0], 1)

    def test_a_build_that_ignores_secure_delete_is_refused(self):
        real_connect = sqlite3.connect

        class Ignoring:
            def __init__(self, connection):
                self.connection = connection

            def execute(self, sql, *args):
                if sql.replace(" ", "").upper().startswith("PRAGMASECURE_DELETE"):
                    return self.connection.execute("SELECT 0")
                return self.connection.execute(sql, *args)

            def __getattr__(self, name):
                return getattr(self.connection, name)

            def __setattr__(self, name, value):
                if name == "connection":
                    object.__setattr__(self, name, value)
                else:
                    setattr(self.connection, name, value)
        with patch("app.image_job_store.sqlite3.connect", lambda *a, **k: Ignoring(real_connect(*a, **k))):
            with self.assertRaisesRegex(ImageJobError, "secure_delete"):
                self.store.get("x", "anders")

    def test_real_transitions_leave_no_old_prompt_text_after_the_purge(self):
        # Codex 4477941179: 16 jobs, ~500-character prompts, the normal submit -> claim_for ->
        # begin_publish -> complete path; with secure_delete only during the purge, half the
        # markers survived in free space.
        markers = [f"kaliv-transition-probe-{i:02d}-c9e1" for i in range(16)]
        instance = A1
        with self.secure_delete_off_by_default():
            for i, marker in enumerate(markers):
                job = self.store.submit("anders", f"{marker} " + "p" * 480, profile_id="test-profile",
                                        max_owner_active=16)["job_id"]
                self.assertEqual(self.store.claim_for(["test-profile"], instance)["id"], job)
                if i % 4 == 3:
                    self.assertTrue(self.store.fail(job, instance, "generation_failed"))
                else:
                    self.assertTrue(self.store.begin_publish(job, instance))
                    self.assertTrue(self.store.complete(job, instance, f"{i:032x}"))
            self.assertEqual(self.store.purge_prompts(now=time.time() + 31 * self.DAY), 16)
        data = Path(self.db).read_bytes()
        self.assertEqual([m for m in markers if m.encode() in data], [])

    def test_a_database_written_before_this_version_is_scrubbed_on_the_first_purge(self):
        # The old text sits only in free space and every prompt is already blank, so the purge
        # itself blanks nothing: only the scrub owed on first open can remove it.
        legacy = str(Path(self.temp.name) / "legacy.sqlite3")
        marker = "kaliv-legacy-probe-5d20"
        with sqlite3.connect(legacy) as db:
            db.execute("PRAGMA secure_delete=OFF")
            db.execute("""CREATE TABLE image_jobs (
                id TEXT PRIMARY KEY, owner TEXT NOT NULL, prompt TEXT NOT NULL,
                profile_id TEXT NOT NULL, params TEXT NOT NULL,
                state TEXT NOT NULL, created REAL NOT NULL, updated REAL NOT NULL,
                asset_id TEXT, error TEXT)""")
            for i in range(8):
                db.execute("INSERT INTO image_jobs VALUES (?, 'anders', ?, 'test-profile', '{}', 'completed', 0, 0, ?, NULL)",
                           (f"{i:032x}", f"{marker} {i} " + "q" * 400, f"{i:032x}"))
        with sqlite3.connect(legacy) as db:
            db.execute("PRAGMA secure_delete=OFF")
            db.execute("UPDATE image_jobs SET prompt=''")
        self.assertIn(marker.encode(), Path(legacy).read_bytes(), "the residue this test is about")
        store = ImageJobStore(legacy)
        self.assertEqual(store.purge_prompts(now=time.time() + 31 * self.DAY), 0, "nothing left to blank")
        self.assertNotIn(marker.encode(), Path(legacy).read_bytes())
        with sqlite3.connect(legacy) as db:
            self.assertEqual(db.execute("SELECT owed FROM image_jobs_scrub").fetchone()[0], 0, "paid")
        self.assertEqual(store.get(f"{0:032x}", "anders")["state"], "completed", "the rows stay")

    def owed(self):
        with sqlite3.connect(self.db) as db:
            return db.execute("SELECT owed FROM image_jobs_scrub").fetchone()[0]

    def test_a_failed_scrub_stays_owed_and_is_paid_on_the_next_call(self):
        self.assertEqual(self.store.purge_prompts(), 0)
        self.assertEqual(self.owed(), 0, "the first-open scrub is paid")
        self.store.submit("anders", "a red bicycle", profile_id="test-profile")
        with sqlite3.connect(self.db) as db:
            db.execute("UPDATE image_jobs SET state='completed', asset_id=?", ("a" * 32,))
        with patch.object(ImageJobStore, "_scrub_if_owed", side_effect=sqlite3.OperationalError("locked")):
            with self.assertRaises(sqlite3.OperationalError):
                self.store.purge_prompts(now=time.time() + 31 * self.DAY)
        self.assertGreater(self.owed(), 0, "the blanking committed together with its debt")
        self.assertEqual(self.store.purge_prompts(now=time.time() + 31 * self.DAY), 0)
        self.assertEqual(self.owed(), 0)

    def test_the_scrub_keeps_its_temp_database_in_memory(self):
        statements = []
        real_connect = sqlite3.connect

        def recording(*args, **kwargs):
            connection = real_connect(*args, **kwargs)
            connection.set_trace_callback(statements.append)
            return connection
        with patch("app.image_job_store.sqlite3.connect", recording):
            self.store.purge_prompts()
            vacuum = statements.index("VACUUM")
            self.assertIn("PRAGMA temp_store=MEMORY", statements[:vacuum])
            statements.clear()
            self.store.purge_prompts()
        self.assertNotIn("VACUUM", statements, "nothing owed, no rebuild")

    def test_the_window_must_be_a_non_negative_number_of_seconds(self):
        for bad in (-1, "30", True, None):
            with self.subTest(bad=bad), self.assertRaises(ImageJobError):
                self.store.purge_prompts(older_than_s=bad)
        self.assertEqual(self.store.purge_prompts(older_than_s=0), 0)


if __name__ == "__main__":
    unittest.main()
