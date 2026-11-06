"""The media executor (G2, ModelRig #2296): lifecycle rules against fakes and the real ComfyUI stack.

Design 6510332634; every finding from reviews 6511335742, 6512440682 and 6513576382 has a test here.
Image runs use FakeImageAdapter (no torch) but the real GPU lease; video runs use the real
ComfySupervisor and ComfyVideoAdapter with the fake ComfyUI, and the conformance ReferenceSink.

Run: PYTHONPATH=worker python3 tests/worker_media_executor.py
"""
from __future__ import annotations

import io
import json
import os
import shutil
import sqlite3
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from pathlib import Path
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[1]
for extra in (ROOT / "worker", ROOT / "tests", ROOT / "tests" / "support"):
    sys.path.insert(0, str(extra))

from app.comfy_supervisor import ComfyLaunch  # noqa: E402
from app.comfy_video_adapter import ComfyVideoAdapter  # noqa: E402
from app.diffusers_image_adapter import GpuResourcesRetained  # noqa: E402
from app.gpu_lease import GpuBusy, acquire_gpu_lease  # noqa: E402
from app.media_generation_contract import ArtifactSinkUnavailable, RenderedArtifact  # noqa: E402
from app.media_generation_profiles import parse_profile  # noqa: E402
from worker_comfy_supervisor import FAKE_MAIN, AnyExistingDirectory, FakeSupervisor, free_port  # noqa: E402
from worker_comfy_video_adapter import raw, sha  # noqa: E402
from worker_media_generation_profiles import image_profile, video_profile  # noqa: E402
from worker_staged_sink_conformance import ReferenceSink  # noqa: E402

from app.gpu_lease import ExecutorAlreadyRunning, acquire_gpu_lease  # noqa: E402
from app.image_job_store import ImageJobError, ImageJobStore  # noqa: E402
from app.media_executor import (EXIT_DUPLICATE, EXIT_GPU_RETAINED, EXIT_SINK_UNAVAILABLE,  # noqa: E402
                                EXIT_UNRECORDED, ExecutorConfigError, MediaExecutor)
from app.media_generation_contract import GenerationCancelled  # noqa: E402

GPU_A = "GPU-6a7f0c2e-1b2d-4c3e-8f9a-0123456789ab"
GPU_B = "GPU-7b8f1d3f-2c3e-4d4f-9a0b-1234567890bc"


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


class FakeImageAdapter:
    """Takes the real GPU lease, so exclusivity and release are real; no torch."""

    def __init__(self, profile, *, lease_dir, gpu_uuid, close_ok=True, load_error=None, log=None, on_render=None,
                 fail_after_acquire=None):
        self.on_render = on_render
        self.fail_after_acquire = fail_after_acquire
        self.close_raises = close_ok == "raise"
        self.profile_id = profile.profile_id
        self.lease_dir, self.gpu_uuid, self.close_ok, self.load_error = lease_dir, gpu_uuid, close_ok, load_error
        self.lease = None
        self.log = log if log is not None else []

    def load(self):
        if self.load_error:
            raise self.load_error
        self.lease = acquire_gpu_lease(self.gpu_uuid, lease_dir=self.lease_dir)
        self.log.append(f"load:{self.profile_id}")
        if self.fail_after_acquire:  # a partial load: the GPU is already held
            # A fresh exception each time, so no shared traceback keeps this adapter alive.
            raise type(self.fail_after_acquire)(*self.fail_after_acquire.args)

    def render(self, request, *, should_cancel=None):
        if self.on_render:
            self.on_render()  # e.g. the owner cancels after the adapter's last poll
        return RenderedArtifact(b"\x89PNG\r\n\x1a\n" + b"\x00" * 16, "image/png")

    def close(self):
        self.log.append(f"close:{self.profile_id}")
        if self.lease is None and not self.close_raises:
            return True  # never acquired anything: nothing to release
        if self.close_raises:
            raise RuntimeError("offload hook failed")  # lease still held by this adapter
        if not self.close_ok:
            self.lease.hold_until_exit()
            return False
        self.lease.release()
        return True


class JobKeyedMemorySink:
    """Offers the job-keyed capability, like ExternalMediaSink."""

    def __init__(self):
        self.assets, self.calls = {}, []

    def publish(self, data, extension):
        raise AssertionError("a job-keyed sink must be published to by job")

    def publish_and_register_for_job(self, job_key, data, extension):
        self.calls.append(job_key)
        asset_id = f"job-{job_key}"
        self.assets[asset_id] = (data, extension)
        return asset_id


class MemorySink:
    def __init__(self):
        self.assets, self.available, self.on_publish = {}, True, None

    def publish(self, data, extension):
        if self.on_publish:
            self.on_publish()
        if not self.available:
            raise ArtifactSinkUnavailable("external media volume is not mounted")
        asset_id = f"asset{len(self.assets)}"
        self.assets[asset_id] = (data, extension)
        return asset_id


class HookedComfyVideoAdapter(ComfyVideoAdapter):
    """The real adapter plus one test seam: a hook that runs after render_to() returns."""

    after_render = None

    def render_to(self, request, sink_file, *, should_cancel=None):
        mime = super().render_to(request, sink_file, should_cancel=should_cancel)
        if self.after_render:
            self.after_render()  # e.g. the owner cancels after the last poll, before adopt()
        return mime


def lease_free(uuid, lease_dir) -> bool:
    import subprocess
    code = ("import sys; from app.gpu_lease import GpuBusy, acquire_gpu_lease\n"
            "try:\n    acquire_gpu_lease(sys.argv[1], lease_dir=sys.argv[2]).release(); print('free')\n"
            "except GpuBusy:\n    print('busy')\n")
    out = subprocess.run([sys.executable, "-c", code, uuid, lease_dir], capture_output=True, text=True,
                         env=dict(os.environ, PYTHONPATH=str(ROOT / "worker"))).stdout.strip()
    return out == "free"


class ExecutorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.lease_dir = os.path.join(self.tmp, "lease")
        os.mkdir(self.lease_dir, 0o700)
        self.store = ImageJobStore(os.path.join(self.tmp, "jobs.sqlite3"))
        self.clock = Clock()
        self.log = []
        self.sink = MemorySink()
        self.executors = []

    def tearDown(self):
        for ex in self.executors:
            if ex.adapter is not None:
                try:
                    ex.adapter.close()
                except Exception:
                    pass
            ex.release_lock()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def image(self, profile_id="sdxl-a", devices=("cuda:0",)):
        return parse_profile(image_profile(profile_id=profile_id, resources={"min_usable_gib": 8, "reserve_gib": 2,
                                                                              "devices": list(devices), "cpu_offload": False}))

    def executor(self, profiles, gpu=GPU_A, start=True, **kw):
        close_ok = kw.pop("close_ok", True)
        load_error = kw.pop("load_error", None)
        on_render = kw.pop("on_render", None)
        fail_after_acquire = kw.pop("fail_after_acquire", None)
        factory = kw.pop("factory", None) or (lambda p: FakeImageAdapter(p, lease_dir=self.lease_dir, gpu_uuid=gpu,
                                                                         close_ok=close_ok, load_error=load_error,
                                                                         log=self.log, on_render=on_render,
                                                                         fail_after_acquire=fail_after_acquire))
        ex = MediaExecutor(self.store, gpu_uuid=gpu, profiles={p.profile_id: p for p in profiles},
                           adapter_factory=factory, lease_dir=self.lease_dir, image_sink=kw.pop("image_sink", self.sink),
                           idle_unload_s=kw.pop("idle_unload_s", 60), clock=self.clock, **kw)
        self.executors.append(ex)
        if start:
            ex.start()
        return ex

    @staticmethod
    def crash(ex):
        """What the OS does when the process dies: its locks go."""
        for adapter in [ex.adapter, *ex._retained]:
            lease = getattr(adapter, "lease", None)
            if lease is not None and lease.held:
                lease.release()
        ex.adapter = None
        ex.release_lock()

    def submit(self, profile_id, owner="anders", **params):
        return self.store.submit(owner, "a red bicycle", profile_id=profile_id,
                                 params={"width": 1024, "height": 1024, "steps": 20, **params})["job_id"]

    def state(self, job_id, owner="anders"):
        return self.store.get(job_id, owner)

    # --- image path, residency, switching ----------------------------------------------------------
    def test_image_job_completes_and_the_model_stays_resident(self):
        ex = self.executor([self.image()])
        job = self.submit("sdxl-a")
        self.assertEqual(ex.step(), "completed")
        self.assertEqual(self.state(job)["state"], "completed")
        self.assertIn(self.state(job)["asset_id"], self.sink.assets)
        self.assertFalse(lease_free(GPU_A, self.lease_dir), "resident model keeps the lease")
        self.submit("sdxl-a")
        ex.step()
        self.assertEqual(self.log, ["load:sdxl-a"], "loaded once, reused")

    def test_idle_unload_frees_the_gpu_for_others(self):
        ex = self.executor([self.image()])
        self.submit("sdxl-a")
        ex.step()
        self.clock.now += 59
        ex.step()
        self.assertFalse(lease_free(GPU_A, self.lease_dir))
        self.clock.now += 2
        self.assertEqual(ex.step(), "idle")
        self.assertTrue(lease_free(GPU_A, self.lease_dir), "unloaded after the idle window")

    def test_switching_profiles_unloads_first_then_loads(self):
        ex = self.executor([self.image("sdxl-a"), self.image("sdxl-b")])
        self.submit("sdxl-a")
        self.submit("sdxl-b")
        ex.step()
        ex.step()
        self.assertEqual(self.log, ["load:sdxl-a", "close:sdxl-a", "load:sdxl-b"])

    # --- fatal exits ---------------------------------------------------------------------------------
    def test_memory_not_proven_free_on_switch_exits_70_and_fails_the_job_explicitly(self):
        ex = self.executor([self.image("sdxl-a"), self.image("sdxl-b")], close_ok=False, start=False)
        self.submit("sdxl-a")
        second = self.submit("sdxl-b")
        self.assertEqual(ex.run(max_steps=2, idle_sleep=lambda: None), EXIT_GPU_RETAINED)
        self.assertEqual((self.state(second)["state"], self.state(second)["error"]), ("failed", "gpu_memory_retained"))

    def test_unload_raising_on_a_switch_is_fatal_and_the_next_model_never_loads(self):
        ex = self.executor([self.image("sdxl-a"), self.image("sdxl-b")], close_ok="raise", start=False)
        self.submit("sdxl-a")
        second = self.submit("sdxl-b")
        self.assertEqual(ex.run(max_steps=3, idle_sleep=lambda: None), EXIT_GPU_RETAINED)
        self.assertEqual(self.log, ["load:sdxl-a", "close:sdxl-a"], "sdxl-b is never loaded on top")
        self.assertEqual((self.state(second)["state"], self.state(second)["error"]), ("failed", "gpu_memory_retained"))
        self.assertFalse(lease_free(GPU_A, self.lease_dir), "the failed adapter's lease is kept until exit")

    def test_after_a_fatal_unload_no_further_step_loads_or_claims(self):
        ex = self.executor([self.image("sdxl-a"), self.image("sdxl-b")], close_ok="raise")
        self.submit("sdxl-a")
        self.submit("sdxl-b")
        third = self.submit("sdxl-b")
        ex.step()
        with self.assertRaises(GpuResourcesRetained):
            ex.step()
        with self.assertRaises(GpuResourcesRetained):
            ex.step()  # an embedding loop that ignores the first exit still cannot load or claim
        self.assertEqual(self.log, ["load:sdxl-a", "close:sdxl-a"])
        self.assertEqual(self.state(third)["state"], "queued", "never claimed")

    def test_idle_unload_raising_is_fatal(self):
        ex = self.executor([self.image()], close_ok="raise", start=False)
        self.submit("sdxl-a")

        def idle_sleep():
            self.clock.now += 120
        self.assertEqual(ex.run(max_steps=3, idle_sleep=idle_sleep), EXIT_GPU_RETAINED)
        self.assertEqual(self.log, ["load:sdxl-a", "close:sdxl-a"])

    def test_a_publishing_job_still_counts_toward_the_owner_quota(self):
        ex = self.executor([self.image()])
        job = self.store.submit("anders", "a red bicycle", profile_id="sdxl-a", max_owner_active=1,
                                params={"width": 1024, "height": 1024, "steps": 20})["job_id"]
        self.store.claim_for(["sdxl-a"], ex.instance)
        self.assertTrue(self.store.begin_publish(job, ex.instance))
        with self.assertRaisesRegex(ImageJobError, "owner image job limit"):
            self.store.submit("anders", "another", profile_id="sdxl-a", max_owner_active=1)
        self.store.complete(job, ex.instance, "asset0")
        self.store.submit("anders", "another", profile_id="sdxl-a", max_owner_active=1)  # free again

    def test_retained_gpu_on_load_exits_70(self):
        ex = self.executor([self.image()], load_error=GpuResourcesRetained("not proven free"), start=False)
        job = self.submit("sdxl-a")
        self.assertEqual(ex.run(max_steps=1, idle_sleep=lambda: None), EXIT_GPU_RETAINED)
        self.assertEqual(self.state(job)["error"], "gpu_memory_retained")

    def test_missing_volume_exits_75_leaves_the_job_for_recovery_and_never_falls_back(self):
        self.sink.available = False
        ex = self.executor([self.image()], start=False)
        job = self.submit("sdxl-a")
        self.assertEqual(ex.run(max_steps=1, idle_sleep=lambda: None), EXIT_SINK_UNAVAILABLE)
        self.assertEqual(self.state(job)["state"], "publishing", "untouched by the failing executor")
        self.assertEqual(self.sink.assets, {})
        self.crash(ex)
        restarted = self.executor([self.image()], start=False)
        self.assertEqual(restarted.start(), 1)
        self.assertEqual((self.state(job)["state"], self.state(job)["error"]), ("failed", "interrupted_during_publication"),
                         "an asset may exist: flagged for reconciliation, not silently failed")

    # --- several executors (dual GPU) ----------------------------------------------------------------
    def test_each_executor_claims_only_its_own_profiles_and_recovers_only_its_own_jobs(self):
        a = self.executor([self.image("sdxl-a", devices=("cuda:0",))], gpu=GPU_A)
        b = self.executor([self.image("sdxl-b", devices=("cuda:1",))], gpu=GPU_B)
        job_b = self.submit("sdxl-b")
        self.assertEqual(a.step(), "idle", "A never claims B's job (today's claim() would, and fail it)")
        claimed = self.store.claim_for(["sdxl-b"], b.instance)  # B is mid-job...
        self.assertEqual(claimed["id"], job_b)
        job_a = self.submit("sdxl-a")
        self.store.claim_for(["sdxl-a"], a.instance)  # ...and so was A, which now crashes and restarts
        self.crash(a)
        restarted_a = self.executor([self.image("sdxl-a")], gpu=GPU_A)
        self.assertEqual(self.state(job_a)["state"], "failed")
        self.assertEqual(self.state(job_b)["state"], "running", "B's in-flight job is not A's to fail")
        self.assertFalse(self.store.complete(job_a, a.instance, "late-asset"), "a stale instance cannot complete")

    def test_no_claim_without_the_executor_lock(self):
        ex = self.executor([self.image()], start=False)
        job = self.submit("sdxl-a")
        with self.assertRaises(ExecutorConfigError):
            ex.step()
        self.assertEqual(self.state(job)["state"], "queued")

    # --- #2296 6511335742 P1: same GPU, overlapping startup ---------------------------------------------
    def test_a_second_executor_for_the_same_gpu_refuses_before_touching_any_claim(self):
        import subprocess
        job = self.submit("sdxl-a")
        child = subprocess.Popen([sys.executable, "-c", CHILD, str(ROOT), "-", self.store.path.as_posix(),
                                  self.lease_dir, GPU_A, job], stdout=subprocess.PIPE, text=True)
        try:
            self.assertEqual(child.stdout.readline().strip(), "READY", "child holds the executor lock and the job")
            self.assertEqual(self.state(job)["state"], "running")
            b = self.executor([self.image()], start=False)
            self.assertEqual(b.run(max_steps=1, idle_sleep=lambda: None), EXIT_DUPLICATE)
            self.assertEqual(self.state(job)["state"], "running", "the live executor's job is untouched")
            with self.assertRaises(ExecutorAlreadyRunning):
                self.executor([self.image()])
        finally:
            child.kill()
            child.wait()
            child.stdout.close()
        after = self.executor([self.image()])  # the holder is dead: now recovery is safe
        self.assertEqual((self.state(job)["state"], self.state(job)["error"]), ("failed", "interrupted_by_restart"))
        self.assertEqual(after.step(), "idle")

    # --- #2296 6511335742 P1: cancellation vs publication ------------------------------------------------
    def test_a_cancel_after_the_last_poll_but_before_publication_wins_and_nothing_is_published(self):
        holder = {}
        ex = self.executor([self.image()], on_render=lambda: self.store.request_cancel(holder["job"], "anders"))
        holder["job"] = self.submit("sdxl-a")
        self.assertEqual(ex.step(), "cancelled")
        self.assertEqual(self.state(holder["job"])["state"], "cancelled")
        self.assertEqual(self.sink.assets, {}, "publish() never called")

    def test_a_cancel_after_the_commit_point_is_too_late_and_the_job_completes(self):
        ex = self.executor([self.image()])
        job = self.submit("sdxl-a")
        answers = []
        self.sink.on_publish = lambda: answers.append(self.store.request_cancel(job, "anders"))
        self.assertEqual(ex.step(), "completed")
        self.assertEqual(answers, ["too_late"])
        self.assertEqual(self.state(job)["state"], "completed")

    # --- cancellation ---------------------------------------------------------------------------------
    def test_a_cancelled_queued_job_is_never_claimed(self):
        ex = self.executor([self.image()])
        job = self.submit("sdxl-a")
        self.assertEqual(self.store.request_cancel(job, "anders"), "cancelled")
        self.assertEqual(ex.step(), "idle")
        self.assertEqual(self.store.request_cancel(job, "someone-else"), None, "only the owner")

    def test_a_gpu_held_by_another_lease_taker_fails_the_job_as_gpu_busy_and_the_executor_continues(self):
        other = acquire_gpu_lease(GPU_A, lease_dir=self.lease_dir)  # e.g. the qualification harness
        try:
            ex = self.executor([self.image()])
            job = self.submit("sdxl-a")
            self.assertEqual(ex.step(), "failed")
            self.assertEqual(self.state(job)["error"], "gpu_busy")
        finally:
            other.release()
        self.submit("sdxl-a")
        self.assertEqual(ex.step(), "completed", "free again: the next job runs")

    # --- #2318 6516453287 P1: the executor lock is released on every terminal path ---------------
    def test_run_releases_the_executor_lock_on_every_exit_path(self):
        cases = {
            "done": dict(),
            "gpu retained": dict(load_error=GpuResourcesRetained("not proven free")),
            "sink unavailable": dict(sink_down=True),
            "publication unrecorded": dict(unrecorded=True),
        }
        expected = {"done": 0, "gpu retained": EXIT_GPU_RETAINED, "sink unavailable": EXIT_SINK_UNAVAILABLE,
                    "publication unrecorded": EXIT_UNRECORDED}
        for label, options in cases.items():
            with self.subTest(label):
                self.sink.available = not options.pop("sink_down", False)
                unrecorded = options.pop("unrecorded", False)
                ex = self.executor([self.image()], start=False, **options)
                if label != "done":
                    self.submit("sdxl-a")
                if unrecorded:
                    ex.store = Mock(wraps=self.store)
                    ex.store.complete = Mock(return_value=False)
                code = ex.run(max_steps=1, idle_sleep=lambda: None)
                self.assertEqual(code, expected[label])
                self.assertIsNone(ex._lock)
                again = self.executor([self.image()], start=False)
                again.start()  # same process, same GPU: the lock is free again
                again.release_lock()
                self.crash(ex)
                self.sink.available = True

    def test_run_after_start_is_a_config_error_and_still_releases_the_lock(self):
        ex = self.executor([self.image()])
        self.assertEqual(ex.run(max_steps=1, idle_sleep=lambda: None), 78)
        self.assertIsNone(ex._lock)

    # --- #2318 6516453287 P1: a failing database never masks the fatal GPU exit -----------------
    def test_gpu_retained_still_exits_70_when_the_failure_cannot_be_recorded(self):
        import sqlite3
        ex = self.executor([self.image()], load_error=GpuResourcesRetained("not proven free"), start=False)
        self.submit("sdxl-a")
        ex.store = Mock(wraps=self.store)
        ex.store.fail = Mock(side_effect=sqlite3.OperationalError("database is locked"))
        self.assertEqual(ex.run(max_steps=1, idle_sleep=lambda: None), EXIT_GPU_RETAINED)
        self.assertIn("record_failed:gpu_memory_retained", ex.events)

    # --- #2318 6623359226 P1: a partial load never loses the GPU --------------------------------
    def test_a_failed_load_that_proves_its_release_fails_the_job_and_the_executor_continues(self):
        ex = self.executor([self.image()], fail_after_acquire=RuntimeError("weights corrupt"))
        job = self.submit("sdxl-a")
        self.assertEqual(ex.step(), "failed")
        self.assertEqual(self.state(job)["error"], "generation_failed")
        self.assertTrue(lease_free(GPU_A, self.lease_dir), "close() released what load() took")
        self.assertEqual(ex.events[-2], "failed_load:sdxl-a:True")
        self.assertTrue(ex.events[-1].startswith("job:") and ":sdxl-a:failed:" in ex.events[-1])

    def test_a_failed_load_without_proven_release_is_fatal_and_nothing_more_is_claimed(self):
        for close_ok in (False, "raise"):
            with self.subTest(close_ok=close_ok):
                ex = self.executor([self.image()], fail_after_acquire=RuntimeError("ComfyUI half-started"),
                                   close_ok=close_ok, start=False)
                first, second = self.submit("sdxl-a"), self.submit("sdxl-a")
                self.assertEqual(ex.run(max_steps=3, idle_sleep=lambda: None), EXIT_GPU_RETAINED)
                self.assertEqual(self.state(first)["error"], "gpu_memory_retained")
                self.assertEqual(self.state(second)["state"], "queued", "no further claim after an unproven release")
                self.assertFalse(lease_free(GPU_A, self.lease_dir), "the failed adapter keeps the GPU until exit")
                self.assertTrue(ex._retained)
                ex._retained[0].lease.release()  # what process exit would do
                self.store.request_cancel(second, "anders")

    def test_a_load_that_holds_the_gpu_and_reports_it_retained_keeps_it_until_exit(self):
        import gc
        ex = self.executor([self.image()], fail_after_acquire=GpuResourcesRetained("memory not proven free"),
                           start=False)
        job, later = self.submit("sdxl-a"), self.submit("sdxl-a")
        self.assertEqual(ex.run(max_steps=3, idle_sleep=lambda: None), EXIT_GPU_RETAINED)
        gc.collect()  # a dropped adapter would let its lease go here
        self.assertFalse(lease_free(GPU_A, self.lease_dir), "the adapter is kept, so its lease is still held")
        self.assertEqual((self.state(job)["error"], self.state(later)["state"]), ("gpu_memory_retained", "queued"))

    # --- #2318 6517407242 / 6517442207: job-keyed publication and an unrecorded completion -------
    def test_publication_is_job_keyed_when_the_sink_offers_it(self):
        keyed = JobKeyedMemorySink()
        ex = self.executor([self.image()], image_sink=keyed)
        job = self.submit("sdxl-a")
        self.assertEqual(ex.step(), "completed")
        self.assertEqual(keyed.calls, [job])
        self.assertEqual(self.state(job)["asset_id"], f"job-{job}")

    def test_a_durable_artifact_whose_completion_fails_stays_publishing_and_recovers_for_reconciliation(self):
        import sqlite3
        for failure in ("returns False", "raises"):
            with self.subTest(failure):
                keyed = JobKeyedMemorySink()
                ex = self.executor([self.image()], image_sink=keyed, start=False)
                job = self.submit("sdxl-a")
                ex.store = Mock(wraps=self.store)
                ex.store.complete = (Mock(return_value=False) if failure == "returns False"
                                     else Mock(side_effect=sqlite3.OperationalError("disk I/O error")))
                self.assertEqual(ex.run(max_steps=1, idle_sleep=lambda: None), EXIT_UNRECORDED)
                self.assertEqual(self.state(job)["state"], "publishing", "never reported as generation_failed")
                self.assertIn(f"job-{job}", keyed.assets, "the durable artifact is kept")
                self.crash(ex)
                restarted = self.executor([self.image()], image_sink=keyed)
                self.assertEqual((self.state(job)["state"], self.state(job)["error"]),
                                 ("failed", "interrupted_during_publication"))
                restarted.release_lock()
                restarted._lock = None

    def test_a_publication_error_after_the_commit_point_is_recorded_as_such(self):
        class Refusing(MemorySink):
            def publish(self, data, extension):
                raise ValueError("invalid_artifact_bytes")
        ex = self.executor([self.image()], image_sink=Refusing())
        job = self.submit("sdxl-a")
        self.assertEqual(ex.step(), "failed")
        self.assertEqual(self.state(job)["error"], "publication_failed")

    def test_restart_reconciliation_with_the_real_gallery_sink(self):
        """End to end with ChatGPT's ExternalMediaSink and its read-only inspection (#2313)."""
        from unittest.mock import patch
        from app.media_gallery_store import ExternalMediaSink
        from app.media_generation_reconciliation import inspect_generation_consistency
        volume = Path(self.tmp)
        media = volume / "media"
        media.mkdir()
        sink = ExternalMediaSink(media, volume)
        with patch("app.media_gallery_catalog.os.path.ismount", return_value=True):
            ex = self.executor([self.image()], image_sink=sink, start=False)
            job = self.submit("sdxl-a")
            ex.store = Mock(wraps=self.store)
            ex.store.complete = Mock(return_value=False)
            self.assertEqual(ex.run(max_steps=1, idle_sleep=lambda: None), EXIT_UNRECORDED)
            self.crash(ex)
            restarted = self.executor([self.image()], image_sink=sink)
            findings = {f["job_id"]: f for f in inspect_generation_consistency(self.store, sink)}
            restarted.release_lock()
        self.assertEqual(findings[job]["status"], "failed_with_indexed_artifact")
        self.assertEqual(findings[job]["asset_id"], sink.job_asset_id(job))

    def test_config_is_checked_up_front(self):
        with self.assertRaises(ExecutorConfigError):
            self.executor([], start=False)
        with self.assertRaises(ExecutorConfigError):
            self.executor([self.image()], start=False, idle_unload_s=0)
        with self.assertRaises(ExecutorConfigError):
            self.executor([self.image()], start=False, image_sink=None)

    def test_job_errors_are_fixed_codes_never_exception_text(self):
        class Exploding(FakeImageAdapter):
            def render(self, request, *, should_cancel=None):
                raise RuntimeError(f"CUDA error while drawing {request.prompt!r} from C:/secret/path")
        ex = self.executor([self.image()], factory=lambda p: Exploding(p, lease_dir=self.lease_dir, gpu_uuid=GPU_A))
        job = self.submit("sdxl-a")
        self.assertEqual(ex.step(), "failed")
        self.assertEqual(self.state(job)["error"], "generation_failed")

    def test_config_refuses_video_without_a_staged_sink(self):
        video = parse_profile(video_profile(tasks=["text_to_video"]))
        with self.assertRaises(ExecutorConfigError):
            self.executor([video])


CHILD = """
import os, sys, time
sys.path[:0] = [os.path.join(sys.argv[1], 'worker')]
from app.gpu_lease import acquire_executor_lock
from app.image_job_store import ImageJobStore
store = ImageJobStore(sys.argv[3])
lock = acquire_executor_lock(sys.argv[5], lease_dir=sys.argv[4])
job = store.claim_for(['sdxl-a'], sys.argv[5] + ':' + 'c' * 16)
assert job['id'] == sys.argv[6]
print('READY', flush=True)
time.sleep(60)
"""


class DiagnosticsTests(unittest.TestCase):
    """Track 3: restart and recovery are observable, and the record never grows without bound."""
    setUp, tearDown = ExecutorTests.setUp, ExecutorTests.tearDown
    image, submit, executor = ExecutorTests.image, ExecutorTests.submit, ExecutorTests.executor

    def test_each_lifecycle_step_is_one_structured_event_without_prompt_text(self):
        seen = []
        ex = self.executor([self.image()], start=False)
        ex.events.sink = seen.append
        job = self.submit("sdxl-a")
        self.assertEqual(ex.run(max_steps=2, idle_sleep=lambda: None), 0)
        kinds = [e["event"] for e in seen]
        for kind in ("recovered", "purged", "loaded", "job", "closed", "exit"):
            self.assertIn(kind, kinds)
        done = next(e for e in seen if e["event"] == "job")
        self.assertTrue(done["detail"].startswith(f"{job}:sdxl-a:completed:"))
        self.assertEqual(seen[-1], {"event": "exit", "detail": "0"})
        self.assertNotIn("a red bicycle", json.dumps(seen))

    def test_a_failing_sink_never_stops_the_work(self):
        ex = self.executor([self.image()])
        ex.events.sink = lambda event: 1 / 0
        self.submit("sdxl-a")
        self.assertEqual(ex.step(), "completed")

    def test_the_record_keeps_only_the_last_entries(self):
        from app.media_executor import EVENTS_KEPT
        ex = self.executor([self.image()])
        for i in range(EVENTS_KEPT + 500):
            ex.events.append(f"tick:{i}")
        self.assertEqual(len(ex.events), EVENTS_KEPT)
        self.assertEqual(ex.events[0], "tick:500")


class QueuedExpiryExecutorTests(unittest.TestCase):
    """Anders, 6 Nov 2026: queued jobs nobody claimed for 24 hours expire; the executor enforces it."""
    setUp, tearDown = ExecutorTests.setUp, ExecutorTests.tearDown
    image, executor = ExecutorTests.image, ExecutorTests.executor

    def stale_job(self, age_s=25 * 3600):
        with patch("app.image_job_store.time.time", return_value=__import__("time").time() - age_s):
            return self.store.submit("anders", "a red bicycle", profile_id="sdxl-a",
                                     params={"width": 1024, "height": 1024, "steps": 20})["job_id"]

    def stored_state(self, job):
        import sqlite3
        with sqlite3.connect(self.store.path) as db:
            return db.execute("SELECT state, error FROM image_jobs WHERE id=?", (job,)).fetchone()

    def test_an_executor_starting_after_a_long_pause_expires_instead_of_rendering(self):
        job = self.stale_job()
        ex = self.executor([self.image()], start=False)
        ex.start()
        self.assertIn("expired:1", ex.events)
        self.assertEqual(self.stored_state(job), ("expired", "expired_unclaimed"))
        self.assertEqual(ex.step(), "idle", "nothing to render")
        self.assertIsNone(ex.adapter, "no model was loaded for it")

    def test_a_job_that_ages_out_while_the_executor_waits_for_vram_expires(self):
        ex = self.executor([self.image()])
        job = self.stale_job(age_s=23 * 3600)
        ex._claim_not_before = self.clock.now + 10 ** 6  # waiting for VRAM: no claims (G4)
        later = __import__("time").time() + 2 * 3600
        with patch("app.image_job_store.time.time", return_value=later):
            self.assertEqual(ex.step(), "idle")
            self.assertEqual(self.stored_state(job)[0], "queued", "no claim, so nothing expired it yet")
            ex.idle_housekeeping()
            self.assertEqual(self.stored_state(job)[0], "queued", "not due again within a minute")
            self.clock.now += 60
            ex.idle_housekeeping()
        self.assertEqual(self.stored_state(job), ("expired", "expired_unclaimed"))
        self.assertIn("expired:1", ex.events)

    def test_fresh_jobs_are_rendered_as_before(self):
        ex = self.executor([self.image()])
        job = self.stale_job(age_s=23 * 3600)
        self.assertEqual(ex.step(), "completed")
        self.assertEqual(self.stored_state(job)[0], "completed")

    def test_a_failing_expiry_never_stops_the_work(self):
        ex = self.executor([self.image()], start=False)
        with patch.object(self.store, "expire_queued", side_effect=sqlite3_error()):
            ex.start()
        self.assertTrue(any(e.startswith("expire_failed:") for e in ex.events))


def sqlite3_error():
    import sqlite3
    return sqlite3.OperationalError("database is locked")


class VramWaitTests(unittest.TestCase):
    """G4, Anders 5 Nov 2026: chat first, media waits. Too little free VRAM re-queues the job."""
    setUp, tearDown = ExecutorTests.setUp, ExecutorTests.tearDown
    image, submit = ExecutorTests.image, ExecutorTests.submit

    def executor(self, short):
        from app.image_gpu_admission import GpuMemoryShortage

        def factory(profile):  # a fresh exception per load: Ollama holds the VRAM while short[0]
            error = GpuMemoryShortage("insufficient free VRAM after reservation") if short[0] else None
            return FakeImageAdapter(profile, lease_dir=self.lease_dir, gpu_uuid=GPU_A, load_error=error, log=self.log)
        return ExecutorTests.executor(self, [self.image()], factory=factory)

    def test_a_shortage_requeues_the_job_waits_then_runs_it_when_vram_frees(self):
        short = [True]
        ex = self.executor(short)
        job = self.submit("sdxl-a")
        self.assertEqual(ex.step(), "deferred")
        row = self.store.get(job, "anders")
        self.assertEqual((row["state"], row["claimed_by"], row["error"]), ("queued", None, None), "not failed")
        self.clock.now += 29
        self.assertEqual(ex.step(), "idle", "no claim within the 30 s back-off")
        self.assertEqual(self.store.get(job, "anders")["state"], "queued")
        short[0] = False  # Ollama unloaded its model
        self.clock.now += 1
        self.assertEqual(ex.step(), "completed")
        self.assertEqual(self.store.get(job, "anders")["state"], "completed")

    def test_after_ten_minutes_of_waiting_the_job_fails_gpu_unavailable(self):
        short = [True]
        ex = self.executor(short)
        job = self.submit("sdxl-a")
        real_time = __import__("time").time
        start = real_time()
        with patch("app.image_job_store.time.time", side_effect=lambda: start + offset[0]):
            offset = [0.0]
            outcomes = []
            for minute in range(0, 11):
                offset[0] = minute * 60.0
                self.clock.now += 60
                outcomes.append(ex.step())
        self.assertEqual(outcomes[:10], ["deferred"] * 10)
        self.assertEqual(outcomes[10], "failed")
        row = self.store.get(job, "anders")
        self.assertEqual((row["state"], row["error"]), ("failed", "gpu_unavailable"))

    def test_waiting_never_holds_the_gpu(self):
        ex = self.executor([True])
        self.submit("sdxl-a")
        self.assertEqual(ex.step(), "deferred")
        self.assertIsNone(ex.adapter, "the refused load left nothing resident")
        self.assertTrue(lease_free(GPU_A, self.lease_dir), "Ollama can have the GPU")

    def test_a_shortage_on_a_resident_model_unloads_it_before_waiting(self):
        # Codex 4477938515: the first job loaded the model; the next one's pre-job check is short.
        from app.image_gpu_admission import GpuMemoryShortage
        short = [False]

        class Resident(FakeImageAdapter):
            def render(self, request, *, should_cancel=None):
                if short[0]:
                    raise GpuMemoryShortage("insufficient free VRAM after reservation")
                return super().render(request, should_cancel=should_cancel)

        def factory(profile):
            return Resident(profile, lease_dir=self.lease_dir, gpu_uuid=GPU_A, log=self.log)
        ex = ExecutorTests.executor(self, [self.image()], factory=factory)
        self.submit("sdxl-a")
        self.assertEqual(ex.step(), "completed")
        self.assertFalse(lease_free(GPU_A, self.lease_dir), "resident after the first job")
        short[0] = True  # Ollama loaded a model meanwhile
        job = self.submit("sdxl-a")
        self.assertEqual(ex.step(), "deferred")
        self.assertIsNone(ex.adapter, "unloaded at once, not after idle_unload_s")
        self.assertTrue(lease_free(GPU_A, self.lease_dir), "the GPU is free while the job waits")
        self.assertEqual(self.store.get(job, "anders")["state"], "queued")
        short[0] = False
        self.clock.now += 30
        self.assertEqual(ex.step(), "completed", "reloaded when VRAM is back")

    def test_a_resident_model_that_cannot_prove_its_unload_is_fatal_but_the_job_stays_queued(self):
        from app.image_gpu_admission import GpuMemoryShortage
        short = [False]

        class Resident(FakeImageAdapter):
            def render(self, request, *, should_cancel=None):
                if short[0]:
                    raise GpuMemoryShortage("insufficient free VRAM after reservation")
                return super().render(request, should_cancel=should_cancel)

        def factory(profile):
            return Resident(profile, lease_dir=self.lease_dir, gpu_uuid=GPU_A, close_ok=False, log=self.log)
        ex = ExecutorTests.executor(self, [self.image()], factory=factory)
        self.submit("sdxl-a")
        self.assertEqual(ex.step(), "completed")
        short[0] = True
        job = self.submit("sdxl-a")
        with self.assertRaises(GpuResourcesRetained):
            ex.step()
        row = self.store.get(job, "anders")
        self.assertEqual((row["state"], row["claimed_by"]), ("queued", None), "requeued before the unload")

    def test_other_failures_still_fail_at_once(self):
        from app.image_gpu_admission import ImageGpuAdmissionError

        def factory(profile):
            return FakeImageAdapter(profile, lease_dir=self.lease_dir, gpu_uuid=GPU_A,
                                    load_error=ImageGpuAdmissionError("GPU identity mismatch"), log=self.log)
        ex = ExecutorTests.executor(self, [self.image()], factory=factory)
        job = self.submit("sdxl-a")
        self.assertEqual(ex.step(), "failed")
        self.assertEqual(self.store.get(job, "anders")["error"], "generation_failed")

class PromptRetentionExecutorTests(unittest.TestCase):
    """The executor applies the retention at start and then at most hourly while idle."""
    setUp, tearDown = ExecutorTests.setUp, ExecutorTests.tearDown
    executor, image, submit = ExecutorTests.executor, ExecutorTests.image, ExecutorTests.submit

    def old_finished_job(self, prompt="an old prompt"):
        job = self.store.submit("anders", prompt, profile_id="sdxl-a", max_owner_active=16)["job_id"]
        with sqlite3.connect(self.store.path) as db:
            db.execute("UPDATE image_jobs SET state='completed', asset_id=?, updated=? WHERE id=?",
                       ("a" * 32, time.time() - 31 * 24 * 3600, job))
        return job

    def prompt(self, job):
        with sqlite3.connect(self.store.path) as db:
            return db.execute("SELECT prompt FROM image_jobs WHERE id=?", (job,)).fetchone()[0]

    def test_start_blanks_old_prompts(self):
        job = self.old_finished_job()
        ex = self.executor([self.image()])
        self.assertEqual(self.prompt(job), "")
        self.assertIn("purged:1", ex.events)

    def test_then_at_most_hourly_while_idle(self):
        ex = self.executor([self.image()], start=False)
        seen = []

        def idle():  # every idle tick is half an hour; an old job appears after the first one
            seen.append(self.prompt(late[0]) if late else None)
            self.clock.now += 1800
            if not late:
                late.append(self.old_finished_job("appeared later"))
        late = []
        self.assertEqual(ex.run(max_steps=3, idle_sleep=idle), 0)
        # t0: start purges; t0+30 min: still there; t0+60 min: the idle check purges it.
        self.assertEqual(seen, [None, "appeared later", ""])
        self.assertEqual([e for e in ex.events if e.startswith("purged")], ["purged:0", "purged:1"])

    def test_a_failing_purge_is_recorded_and_never_fatal(self):
        with patch.object(self.store, "purge_prompts", side_effect=sqlite3.OperationalError("database is locked")):
            ex = self.executor([self.image()])
            job = self.submit("sdxl-a")
            self.assertEqual(ex.step(), "completed")
        self.assertIn("purge_failed:OperationalError", ex.events)
        self.assertEqual(self.store.get(job, "anders")["state"], "completed")


class VideoExecutorTests(unittest.TestCase):
    """Real ComfySupervisor + adapter + fake ComfyUI; ReferenceSink from the conformance suite."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.lease_dir = os.path.join(self.tmp, "lease")
        os.mkdir(self.lease_dir, 0o700)
        self.dirs = {n: os.path.join(self.tmp, n) for n in ("input", "output", "temp", "user", "templates", "state", "sink")}
        for d in self.dirs.values():
            os.mkdir(d)
        Path(self.dirs["templates"], "wan-t2v.json").write_bytes(raw())
        self.port = free_port()
        self.store = ImageJobStore(os.path.join(self.tmp, "jobs.sqlite3"))
        self.sink = ReferenceSink(self.dirs["sink"], max_bytes=64 * 1024 * 1024)
        self.adapters = []
        self.executors = []

    def tearDown(self):
        for ex in self.executors:
            ex.release_lock()
        for adapter in self.adapters:
            try:
                adapter.close()
            except Exception:
                pass
        shutil.rmtree(self.tmp, ignore_errors=True)

    def profile(self, **pins):
        return parse_profile(video_profile(
            tasks=["text_to_video"], limits={"max_prompt_chars": 200, "sizes": [[832, 480]], "max_steps": 30, "max_frames": 81},
            backend_options={"template_name": "wan-t2v.json", "template_sha256": sha(raw()), "fps": 16,
                             "max_render_seconds": 60, "max_output_bytes": 1024 * 1024, "port": self.port, **pins}))

    def executor_with_fake(self, fake_env):
        return self.executor(extra_fake=fake_env)

    def executor(self, render_seconds="0.2", extra_fake=None, **pins):
        def factory(profile):
            launch = ComfyLaunch(python_executable=sys.executable, main_py=str(FAKE_MAIN), port=self.port,
                                 input_directory=self.dirs["input"], output_directory=self.dirs["output"],
                                 temp_directory=self.dirs["temp"], user_directory=self.dirs["user"])
            sup = FakeSupervisor(fake_env={"FAKE_COMFY_STATE_DIR": self.dirs["state"], "FAKE_COMFY_RENDER_SECONDS": render_seconds,
                                           **(extra_fake or {})},
                                 work_area=AnyExistingDirectory(), gpu_uuid=GPU_A, lease_dir=self.lease_dir, launch=launch,
                                 reserve_gib=2, min_usable_gib=8, ready_timeout_s=15, stop_timeout_s=5, poll_s=0.05,
                                 base_env={"PATH": os.environ.get("PATH", "")})
            adapter = HookedComfyVideoAdapter(profile, supervisor=sup, template_dir=self.dirs["templates"],
                                                   output_directory=self.dirs["output"], poll_s=0.05, settle_s=0.05)
            self.adapters.append(adapter)
            return adapter
        profile = self.profile(**pins)
        ex = MediaExecutor(self.store, gpu_uuid=GPU_A, profiles={profile.profile_id: profile},
                           adapter_factory=factory, lease_dir=self.lease_dir, video_sink=self.sink, cancel_poll_s=0.1)
        ex.start()
        self.executors.append(ex)
        return ex

    def submit(self):
        return self.store.submit("anders", "a red kite", profile_id="wan-t2v",
                                 params={"task": "text_to_video", "width": 832, "height": 480, "steps": 20, "frames": 33})["job_id"]

    def test_video_job_goes_through_staged_adopt_and_leaves_nothing_behind(self):
        ex = self.executor()
        job = self.submit()
        self.assertEqual(ex.step(), "completed")
        row = self.store.get(job, "anders")
        self.assertIn(row["asset_id"], self.sink.registry)
        self.assertEqual(os.listdir(self.sink.staging), [], "no staged leftovers")
        self.assertEqual(os.listdir(self.dirs["output"]), [], "ComfyUI's own output removed")

    def test_a_comfyui_vram_shortage_at_start_requeues_and_frees_the_lease(self):
        ex = self.executor_with_fake({"FAKE_COMFY_VRAM_FREE_GIB": "5"})  # Ollama holds the rest
        job = self.submit()
        self.assertEqual(ex.step(), "deferred")
        self.assertEqual(self.store.get(job, "anders")["state"], "queued")
        self.assertTrue(lease_free(GPU_A, self.lease_dir), "ComfyUI was stopped; the GPU is free")

    def test_a_comfyui_vram_shortage_before_a_job_requeues_without_submitting(self):
        ex = self.executor()
        first = self.submit()
        self.assertEqual(ex.step(), "completed")
        Path(self.dirs["state"], "vram_free_gib").write_text("5")  # Ollama loaded a model meanwhile
        submissions = Path(self.dirs["state"], "prompts.log").read_text().count("submitted")
        job = self.submit()
        self.assertEqual(ex.step(), "deferred")
        self.assertEqual(self.store.get(job, "anders")["state"], "queued")
        self.assertEqual(Path(self.dirs["state"], "prompts.log").read_text().count("submitted"), submissions)
        self.assertEqual(self.store.get(first, "anders")["state"], "completed")
        # Codex 4477938515: the resident ComfyUI is stopped at once, with a proven release.
        self.assertIsNone(ex.adapter)
        self.assertTrue(lease_free(GPU_A, self.lease_dir), "ComfyUI stopped; the GPU is free while the job waits")

    def test_cancelling_a_running_video_interrupts_comfyui_and_publishes_nothing(self):
        ex = self.executor(render_seconds="5")
        job = self.submit()
        threading.Timer(0.8, lambda: self.store.request_cancel(job, "anders")).start()
        started = time.monotonic()
        self.assertEqual(ex.step(), "cancelled")
        self.assertLess(time.monotonic() - started, 4, "interrupted, not waited out")
        self.assertEqual(self.store.get(job, "anders")["state"], "cancelled")
        self.assertEqual(self.sink.registry, set())
        self.assertEqual(os.listdir(self.sink.staging), [])
        self.assertTrue(ex.adapter is not None, "ComfyUI stays resident for the next job")
        follow_up = self.submit()
        self.assertEqual(ex.step(), "completed", "the next job is not refused as 'queue not empty'")
        self.assertEqual(self.store.get(follow_up, "anders")["state"], "completed")

    def test_a_comfyui_whose_cancel_did_not_drain_is_restarted_before_the_next_job(self):
        """#2318 review 4469472651: the stuck ComfyUI is unloaded (proven) and a fresh one takes the next job."""
        from unittest.mock import patch
        import app.comfy_video_adapter as adapter_module
        ex = self.executor(render_seconds="5")
        job = self.submit()
        threading.Timer(0.5, lambda: self.store.request_cancel(job, "anders")).start()
        real_factory, made = ex.adapter_factory, []

        def factory(profile):
            adapter = real_factory(profile)
            made.append(adapter)
            if len(made) == 1:  # only the first ComfyUI's queue refuses to drain after its interrupt
                sup, submitted = adapter.supervisor, []
                real_submit, real_queue = sup.submit, sup.queue_is_empty
                sup.submit = lambda graph: (submitted.append(1), real_submit(graph))[1]
                sup.queue_is_empty = lambda: real_queue() if not submitted else False
            return adapter
        ex.adapter_factory = factory
        with patch.object(adapter_module, "DRAIN_SECONDS", 0.3):
            self.assertEqual(ex.step(), "cancelled")
        self.assertIsNone(ex.adapter, "unloaded: the stuck ComfyUI takes no further job")
        self.assertIn("restart:wan-t2v", ex.events)
        self.assertFalse(made[0].supervisor.running, "its ComfyUI was stopped")
        follow_up = self.submit()
        self.assertEqual(ex.step(), "completed", "a fresh ComfyUI renders the next job")
        self.assertEqual(len(made), 2)
        self.assertEqual(self.store.get(follow_up, "anders")["state"], "completed")

    def test_a_comfyui_version_mismatch_fails_the_job_with_a_proven_stop_and_the_executor_continues(self):
        ex = self.executor(comfyui_version="9.9.9")  # the fake reports "fake"
        job = self.submit()
        self.assertEqual(ex.step(), "failed")
        self.assertEqual(self.store.get(job, "anders")["error"], "generation_failed")
        self.assertIsNone(ex.adapter)
        self.assertIn("failed_load:wan-t2v:True", ex.events, "close() proved the stop, so it continues")
        self.assertEqual(ex.step(), "idle")

    def test_video_adoption_is_job_keyed_when_the_staged_sink_offers_it(self):
        class JobKeyedReference(ReferenceSink):
            def __init__(self, *a, **k):
                super().__init__(*a, **k)
                self.keys = []

            def adopt_for_job(self, handle, mime_type, job_key):
                self.keys.append(job_key)
                return self.adopt(handle, mime_type)
        self.sink = JobKeyedReference(os.path.join(self.tmp, "keyed-sink"), max_bytes=64 * 1024 * 1024) \
            if os.mkdir(os.path.join(self.tmp, "keyed-sink")) is None else None
        ex = self.executor()
        job = self.submit()
        self.assertEqual(ex.step(), "completed")
        self.assertEqual(self.sink.keys, [job])

    def test_a_cancel_after_render_to_returns_but_before_adopt_wins(self):
        ex = self.executor()
        job = self.submit()
        HookedComfyVideoAdapter.after_render = lambda _self: self.store.request_cancel(job, "anders")
        try:
            self.assertEqual(ex.step(), "cancelled")
        finally:
            HookedComfyVideoAdapter.after_render = None
        self.assertEqual(self.store.get(job, "anders")["state"], "cancelled")
        self.assertEqual(self.sink.registry, set(), "adopt() never called")
        self.assertEqual(os.listdir(self.sink.staging), [], "staged file removed")
        self.assertEqual(os.listdir(self.dirs["output"]), [], "the owner cancelled: the work-area copy goes too")

    # -- Anders, 6 Nov 2026: publish on the volume, THEN remove the copy in the work area -------------
    def test_the_work_area_copy_is_still_there_when_the_file_is_published_and_removed_after(self):
        output = self.dirs["output"]

        class Recording(ReferenceSink):
            seen = []

            def adopt(self, handle, mime_type):
                Recording.seen.append(sorted(os.listdir(output)))
                return super().adopt(handle, mime_type)
        os.mkdir(os.path.join(self.tmp, "recording-sink"))
        self.sink = Recording(os.path.join(self.tmp, "recording-sink"), max_bytes=64 * 1024 * 1024)
        ex = self.executor()
        job = self.submit()
        self.assertEqual(ex.step(), "completed")
        self.assertEqual(len(Recording.seen), 1)
        self.assertEqual(len(Recording.seen[0]), 1, "the finished render is still on C: while it is published")
        self.assertEqual(os.listdir(output), [], "and removed once publication succeeded")
        self.assertIn(self.store.get(job, "anders")["asset_id"], self.sink.registry)

    def test_a_failed_publication_keeps_the_work_area_copy_for_recovery(self):
        from app.media_generation_contract import ArtifactSinkUnavailable

        class Unplugged(ReferenceSink):
            def adopt(self, handle, mime_type):
                raise ArtifactSinkUnavailable("test: the volume went away during publication")
        os.mkdir(os.path.join(self.tmp, "unplugged-sink"))
        self.sink = Unplugged(os.path.join(self.tmp, "unplugged-sink"), max_bytes=64 * 1024 * 1024)
        ex = self.executor()
        job = self.submit()
        with self.assertRaises(ArtifactSinkUnavailable):
            ex.step()
        kept = os.listdir(self.dirs["output"])
        self.assertEqual(len(kept), 1, "the finished file was never deleted before it was published")
        self.assertEqual(ex.adapter.last_cleanup["kept_for_recovery"], kept)
        self.assertEqual(self.store.get(job, "anders")["state"], "publishing", "left for recovery")

    def test_the_hand_off_receipt_is_stored_and_matches_the_published_file(self):
        import hashlib
        import sqlite3
        ex = self.executor()
        ex.volume_root = self.tmp
        job = self.submit()
        self.assertEqual(ex.step(), "completed")
        with sqlite3.connect(os.path.join(self.tmp, "jobs.sqlite3")) as db:
            receipt = json.loads(db.execute("SELECT record FROM image_jobs_handoff WHERE job_id=?", (job,)).fetchone()[0])
        asset = self.store.get(job, "anders")["asset_id"]
        published = (self.sink.store / f"{asset}.mp4").read_bytes()
        self.assertEqual(receipt["stage"], "copied")
        root = os.stat(self.tmp)
        self.assertEqual(receipt["volume"], {"dev": root.st_dev, "ino": root.st_ino})
        self.assertEqual((receipt["sha256"], receipt["size"]), (hashlib.sha256(published).hexdigest(), len(published)))
        self.assertNotIn("a red kite", json.dumps(receipt), "never the prompt")

    def test_a_hand_off_that_cannot_be_recorded_fails_the_job_before_any_copy(self):
        ex = self.executor()
        job = self.submit()
        with patch.object(self.store, "record_handoff", return_value=False):
            self.assertEqual(ex.step(), "failed")
        self.assertEqual(self.store.get(job, "anders")["state"], "failed")
        self.assertEqual(self.sink.registry, set(), "nothing published")
        self.assertEqual(os.listdir(self.sink.staging), [], "nothing staged")
        self.assertEqual(os.listdir(self.dirs["output"]), [], "never handed over: cleaned at once")

    def test_a_render_that_fails_is_cleaned_at_once_even_while_held(self):
        ex = self.executor_with_fake({"FAKE_COMFY_OUTPUT_MODE": "notmp4"})
        job = self.submit()
        self.assertEqual(ex.step(), "failed")
        self.assertEqual(self.store.get(job, "anders")["state"], "failed")
        self.assertEqual(os.listdir(self.dirs["output"]), [], "no finished file: nothing to keep")
        self.assertNotIn("kept_for_recovery", ex.adapter.last_cleanup if ex.adapter else {})


if __name__ == "__main__":
    unittest.main()
