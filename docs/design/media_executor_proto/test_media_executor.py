"""Evidence for the G2 executor design (#2296): prototype against fakes. Not part of a PR.

Run: WT=<ModelRig worktree at #2316 head> python test_media_executor.py
"""
from __future__ import annotations

import io
import json
import os
import shutil
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

WT = Path(os.environ["WT"]).resolve()
for extra in (WT / "worker", WT / "tests", WT / "tests" / "support", Path(__file__).parent):
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

from media_executor import (EXIT_GPU_RETAINED, EXIT_SINK_UNAVAILABLE, Cancelled, ExecutorConfigError,  # noqa: E402
                            GenerationJobStore, MediaExecutor)

GPU_A = "GPU-6a7f0c2e-1b2d-4c3e-8f9a-0123456789ab"
GPU_B = "GPU-7b8f1d3f-2c3e-4d4f-9a0b-1234567890bc"


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


class FakeImageAdapter:
    """Takes the real GPU lease, so exclusivity and release are real; no torch."""

    def __init__(self, profile, *, lease_dir, gpu_uuid, close_ok=True, load_error=None, log=None):
        self.profile_id = profile.profile_id
        self.lease_dir, self.gpu_uuid, self.close_ok, self.load_error = lease_dir, gpu_uuid, close_ok, load_error
        self.lease = None
        self.log = log if log is not None else []

    def load(self):
        if self.load_error:
            raise self.load_error
        self.lease = acquire_gpu_lease(self.gpu_uuid, lease_dir=self.lease_dir)
        self.log.append(f"load:{self.profile_id}")

    def render(self, request):
        return RenderedArtifact(b"\x89PNG\r\n\x1a\n" + b"\x00" * 16, "image/png")

    def close(self):
        self.log.append(f"close:{self.profile_id}")
        if not self.close_ok:
            self.lease.hold_until_exit()
            return False
        self.lease.release()
        return True


class MemorySink:
    def __init__(self):
        self.assets, self.available = {}, True

    def publish(self, data, extension):
        if not self.available:
            raise ArtifactSinkUnavailable("external media volume is not mounted")
        asset_id = f"asset{len(self.assets)}"
        self.assets[asset_id] = (data, extension)
        return asset_id


class CancellableComfyVideoAdapter(ComfyVideoAdapter):
    """What the design adds to ComfyVideoAdapter: a should_cancel hook checked in the poll loop."""

    def render_to(self, request, sink_file, *, should_cancel=None):
        self._should_cancel = should_cancel
        return super().render_to(request, sink_file)

    def _wait(self, prompt_id):
        real_history = self.supervisor.history

        def history(pid):
            if self._should_cancel is not None and self._should_cancel():
                self.supervisor.interrupt()
                raise Cancelled("cancelled while rendering")
            return real_history(pid)

        self.supervisor.history = history
        try:
            return super()._wait(prompt_id)
        finally:
            self.supervisor.history = real_history


def lease_free(uuid, lease_dir) -> bool:
    import subprocess
    code = ("import sys; from app.gpu_lease import GpuBusy, acquire_gpu_lease\n"
            "try:\n    acquire_gpu_lease(sys.argv[1], lease_dir=sys.argv[2]).release(); print('free')\n"
            "except GpuBusy:\n    print('busy')\n")
    out = subprocess.run([sys.executable, "-c", code, uuid, lease_dir], capture_output=True, text=True,
                         env=dict(os.environ, PYTHONPATH=str(WT / "worker"))).stdout.strip()
    return out == "free"


class ExecutorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.lease_dir = os.path.join(self.tmp, "lease")
        os.mkdir(self.lease_dir, 0o700)
        self.store = GenerationJobStore(os.path.join(self.tmp, "jobs.sqlite3"))
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
        shutil.rmtree(self.tmp, ignore_errors=True)

    def image(self, profile_id="sdxl-a", devices=("cuda:0",)):
        return parse_profile(image_profile(profile_id=profile_id, resources={"min_usable_gib": 8, "reserve_gib": 2,
                                                                              "devices": list(devices), "cpu_offload": False}))

    def executor(self, profiles, gpu=GPU_A, **kw):
        close_ok = kw.pop("close_ok", True)
        load_error = kw.pop("load_error", None)
        factory = kw.pop("factory", None) or (lambda p: FakeImageAdapter(p, lease_dir=self.lease_dir, gpu_uuid=gpu,
                                                                         close_ok=close_ok, load_error=load_error, log=self.log))
        ex = MediaExecutor(self.store, executor_id=gpu, profiles={p.profile_id: p for p in profiles},
                           adapter_factory=factory, image_sink=kw.pop("image_sink", self.sink),
                           idle_unload_s=60, clock=self.clock, **kw)
        self.executors.append(ex)
        return ex

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
        ex = self.executor([self.image("sdxl-a"), self.image("sdxl-b")], close_ok=False)
        self.submit("sdxl-a")
        second = self.submit("sdxl-b")
        self.assertEqual(ex.run(max_steps=2, idle_sleep=lambda: None), EXIT_GPU_RETAINED)
        self.assertEqual((self.state(second)["state"], self.state(second)["error"]), ("failed", "gpu_memory_retained"))

    def test_retained_gpu_on_load_exits_70(self):
        ex = self.executor([self.image()], load_error=GpuResourcesRetained("not proven free"))
        job = self.submit("sdxl-a")
        self.assertEqual(ex.run(max_steps=1, idle_sleep=lambda: None), EXIT_GPU_RETAINED)
        self.assertEqual(self.state(job)["error"], "gpu_memory_retained")

    def test_missing_volume_exits_75_leaves_the_job_for_recovery_and_never_falls_back(self):
        self.sink.available = False
        ex = self.executor([self.image()])
        job = self.submit("sdxl-a")
        self.assertEqual(ex.run(max_steps=1, idle_sleep=lambda: None), EXIT_SINK_UNAVAILABLE)
        self.assertEqual(self.state(job)["state"], "running", "untouched by the failing executor")
        self.assertEqual(self.sink.assets, {})
        ex.adapter.close()
        restarted = self.executor([self.image()])
        self.assertEqual(restarted.start(), 1)
        self.assertEqual((self.state(job)["state"], self.state(job)["error"]), ("failed", "interrupted by restart"))

    # --- several executors (dual GPU) ----------------------------------------------------------------
    def test_each_executor_claims_only_its_own_profiles_and_recovers_only_its_own_jobs(self):
        a = self.executor([self.image("sdxl-a", devices=("cuda:0",))], gpu=GPU_A)
        b = self.executor([self.image("sdxl-b", devices=("cuda:1",))], gpu=GPU_B)
        job_b = self.submit("sdxl-b")
        self.assertEqual(a.step(), "idle", "A never claims B's job (today's claim() would, and fail it)")
        claimed = self.store.claim_for(["sdxl-b"], GPU_B)  # B is mid-job...
        self.assertEqual(claimed["id"], job_b)
        self.submit("sdxl-a")
        self.store.claim_for(["sdxl-a"], GPU_A)  # ...and so was A, which now crashes and restarts
        restarted_a = self.executor([self.image("sdxl-a")], gpu=GPU_A)
        self.assertEqual(restarted_a.start(), 1)
        self.assertEqual(self.state(job_b)["state"], "running", "B's in-flight job is not A's to fail")

    # --- cancellation ---------------------------------------------------------------------------------
    def test_a_cancelled_queued_job_is_never_claimed(self):
        ex = self.executor([self.image()])
        job = self.submit("sdxl-a")
        self.assertEqual(self.store.request_cancel(job, "anders"), "cancelled")
        self.assertEqual(ex.step(), "idle")
        self.assertEqual(self.store.request_cancel(job, "someone-else"), None, "only the owner")

    def test_config_refuses_video_without_a_staged_sink(self):
        video = parse_profile(video_profile(tasks=["text_to_video"]))
        with self.assertRaises(ExecutorConfigError):
            self.executor([video])


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
        self.store = GenerationJobStore(os.path.join(self.tmp, "jobs.sqlite3"))
        self.sink = ReferenceSink(self.dirs["sink"], max_bytes=64 * 1024 * 1024)
        self.adapters = []

    def tearDown(self):
        for adapter in self.adapters:
            try:
                adapter.close()
            except Exception:
                pass
        shutil.rmtree(self.tmp, ignore_errors=True)

    def profile(self):
        return parse_profile(video_profile(
            tasks=["text_to_video"], limits={"max_prompt_chars": 200, "sizes": [[832, 480]], "max_steps": 30, "max_frames": 81},
            backend_options={"template_name": "wan-t2v.json", "template_sha256": sha(raw()), "fps": 16,
                             "max_render_seconds": 60, "max_output_bytes": 1024 * 1024, "port": self.port}))

    def executor(self, render_seconds="0.2"):
        def factory(profile):
            launch = ComfyLaunch(python_executable=sys.executable, main_py=str(FAKE_MAIN), port=self.port,
                                 input_directory=self.dirs["input"], output_directory=self.dirs["output"],
                                 temp_directory=self.dirs["temp"], user_directory=self.dirs["user"])
            sup = FakeSupervisor(fake_env={"FAKE_COMFY_STATE_DIR": self.dirs["state"], "FAKE_COMFY_RENDER_SECONDS": render_seconds},
                                 media_volume=AnyExistingDirectory(), gpu_uuid=GPU_A, lease_dir=self.lease_dir, launch=launch,
                                 reserve_gib=2, min_usable_gib=8, ready_timeout_s=15, stop_timeout_s=5, poll_s=0.05,
                                 base_env={"PATH": os.environ.get("PATH", "")})
            adapter = CancellableComfyVideoAdapter(profile, supervisor=sup, template_dir=self.dirs["templates"],
                                                   output_directory=self.dirs["output"], poll_s=0.05, settle_s=0.05)
            self.adapters.append(adapter)
            return adapter
        profile = self.profile()
        return MediaExecutor(self.store, executor_id=GPU_A, profiles={profile.profile_id: profile},
                             adapter_factory=factory, video_sink=self.sink, cancel_poll_s=0.1)

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


if __name__ == "__main__":
    unittest.main()
