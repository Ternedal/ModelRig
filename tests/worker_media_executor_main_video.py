#!/usr/bin/env python3
"""Gated text-to-video in the media executor's entry point (#2275 Task B, 6753013948).

The real entry point (build_from_env), the real executor, the real staged video sink on the
(test) publication volume, the real ComfyVideoAdapter and the real supervisor, driving the fake
ComfyUI as a real child process. No GPU, no ComfyUI install, loopback only.

Run: PYTHONPATH=worker python3 tests/worker_media_executor_main_video.py
"""
from __future__ import annotations

import functools
import hashlib
import json
import os
import shutil
import sys
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
for extra in (ROOT / "worker", ROOT / "tests"):
    sys.path.insert(0, str(extra))

from app.gpu_lease import GpuBusy, acquire_gpu_lease  # noqa: E402
from app.image_job_store import ImageJobStore  # noqa: E402
from app.media_executor import EXIT_CONFIG, EXIT_SINK_UNAVAILABLE  # noqa: E402
from app.media_executor_main import build_from_env, main  # noqa: E402
from app.media_gallery_catalog import list_gallery  # noqa: E402
from app.media_gallery_store import ExternalMediaSink  # noqa: E402
from app.media_generation_contract import ArtifactSinkUnavailable, RenderedArtifact  # noqa: E402
from worker_comfy_supervisor import FAKE_MAIN, FakeSupervisor, free_port  # noqa: E402
from worker_comfy_video_adapter import raw, sha  # noqa: E402
import worker_media_executor_main as image_suite  # noqa: E402  (its fixture; not its tests)
from worker_media_generation_profiles import video_profile  # noqa: E402

GPU = "GPU-6a7f0c2e-1b2d-4c3e-8f9a-0123456789ab"
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
WEIGHTS = b"wan weights" * 100
VIDEO_PARAMS = {"width": 832, "height": 480, "steps": 20, "frames": 33, "seed": 7}


class FakeImageAdapter:
    """The image pipeline stand-in (the diffusers adapter needs torch and a GPU)."""

    def __init__(self, profile, lease_dir):
        self.profile_id, self.lease_dir, self.lease = profile.profile_id, lease_dir, None

    def load(self):
        self.lease = acquire_gpu_lease(GPU, lease_dir=self.lease_dir)

    def render(self, request, *, should_cancel=None):
        return RenderedArtifact(PNG, "image/png")

    def close(self):
        if self.lease is not None and self.lease.held:
            self.lease.release()
        return True


class VideoEntryPointTests(unittest.TestCase):
    """The image entry point's fixture (work area, G1 volume, image profile, env), plus ComfyUI."""

    write_profile = image_suite.EntryPointTests.write_profile
    run_entry = image_suite.EntryPointTests.run_entry

    def setUp(self):
        image_suite.EntryPointTests.setUp(self)
        self.comfy = self.tmp / "work" / "comfy"
        for name in ("input", "output", "temp", "user"):
            (self.comfy / name).mkdir(parents=True)
        os.chmod(self.comfy, 0o700)
        root = self.tmp / "comfy-root"
        (root / "models" / "diffusion_models").mkdir(parents=True)
        shutil.copy(FAKE_MAIN, root / "main.py")
        (root / "models" / "diffusion_models" / "wan2.2_t2v_example.safetensors").write_bytes(WEIGHTS)
        self.templates = self.tmp / "templates"
        self.templates.mkdir()
        (self.templates / "wan-t2v.json").write_bytes(raw())
        self.fake_state = self.tmp / "fake-comfy-state"
        self.fake_state.mkdir()
        self.port = free_port()
        self.write_video_profile()
        self.env.update({
            "KALIV_MEDIA_PROFILES_ENABLED": "wan-a",
            "KALIV_MEDIA_VIDEO": "1",
            "KALIV_COMFY_PYTHON": sys.executable,
            "KALIV_COMFY_MAIN": str(root / "main.py"),
            "KALIV_COMFY_DIR": str(self.comfy),
            "KALIV_COMFY_TEMPLATE_DIR": str(self.templates),
        })
        self.fake = {"FAKE_COMFY_STATE_DIR": str(self.fake_state)}
        self.executors = []
        self.addCleanup(self._stop_comfy)

    def _stop_comfy(self):
        for executor in self.executors:
            if executor.adapter is not None:
                executor.adapter.close()
        pid = self.fake_state / "pid"
        if pid.exists():
            try:
                os.kill(int(pid.read_text()), 9)
            except (ProcessLookupError, ValueError):
                pass

    def write_video_profile(self, **options):
        backend = {"template_name": "wan-t2v.json", "template_sha256": sha(raw()), "fps": 16,
                   "max_render_seconds": 60, "max_output_bytes": 1024 * 1024, "port": self.port,
                   "comfyui_version": "fake",
                   "weights": [{"path": "diffusion_models/wan2.2_t2v_example.safetensors",
                                "sha256": hashlib.sha256(WEIGHTS).hexdigest(), "bytes": len(WEIGHTS)}]}
        tasks = options.pop("tasks", ["text_to_video"])
        backend.update(options)
        self.write_profile(video_profile(
            profile_id="wan-a", tasks=tasks, backend_options=backend,
            limits={"max_prompt_chars": 200, "sizes": [[832, 480]], "max_steps": 30, "max_frames": 81},
            resources={"min_usable_gib": 8, "reserve_gib": 2, "devices": ["cuda:0"], "cpu_offload": False}))

    def build(self, env=None, fake=None, **kwargs):
        supervisor = functools.partial(FakeSupervisor, fake_env={**self.fake, **(fake or {})},
                                       ready_timeout_s=15, stop_timeout_s=5, poll_s=0.05)
        executor = build_from_env("cuda:0", env or self.env, supervisor_class=supervisor,
                                  image_adapter_factory=lambda p: FakeImageAdapter(p, self.env["KALIV_GPU_LEASE_DIR"]),
                                  **kwargs)
        self.executors.append(executor)
        return executor

    def store(self):
        return ImageJobStore(self.env["KALIV_MEDIA_JOB_DB"])

    def gallery(self):
        return list_gallery(self.env["KALIV_MEDIA_ROOT"], verified_volume_root=self.env["KALIV_MEDIA_VOLUME_ROOT"])

    def published(self) -> list:
        """Gallery items; no index yet means nothing was ever published."""
        if not Path(self.env["KALIV_MEDIA_ROOT"], "gallery-index.json").exists():
            return []
        return self.gallery()["items"]

    def lease_is_free(self) -> bool:
        try:
            acquire_gpu_lease(GPU, lease_dir=self.env["KALIV_GPU_LEASE_DIR"]).release()
            return True
        except GpuBusy:
            return False

    # --- fail closed ------------------------------------------------------------------------
    def test_video_needs_its_own_switch(self):
        env = {k: v for k, v in self.env.items() if k != "KALIV_MEDIA_VIDEO"}
        with patch("app.media_gallery_catalog.os.path.ismount", return_value=True):
            self.assertEqual(main(["--device", "cuda:0"], env), EXIT_CONFIG)
            self.assertEqual(main(["--device", "cuda:0"], {**env, "KALIV_MEDIA_VIDEO": "0"}), EXIT_CONFIG)

    def test_video_is_off_without_its_own_switch_and_the_queue_is_untouched(self):
        import contextlib
        import io
        err = io.StringIO()
        with patch("app.media_gallery_catalog.os.path.ismount", return_value=True), contextlib.redirect_stderr(err):
            self.assertEqual(main(["--device", "cuda:0"], {**self.env, "KALIV_MEDIA_VIDEO": "0"}), EXIT_CONFIG)
        self.assertIn("video is off", err.getvalue())
        self.assertFalse(Path(self.env["KALIV_MEDIA_JOB_DB"]).exists(), "the job database was never opened")

    def test_every_comfyui_setting_is_required_and_checked(self):
        for name in ("KALIV_COMFY_PYTHON", "KALIV_COMFY_MAIN", "KALIV_COMFY_DIR", "KALIV_COMFY_TEMPLATE_DIR"):
            for value in ("", "relative/path", str(self.tmp / "missing" / "x")):
                with self.subTest(name=name, value=value), patch("app.media_gallery_catalog.os.path.ismount",
                                                                  return_value=True):
                    self.assertEqual(main(["--device", "cuda:0"], {**self.env, name: value}), EXIT_CONFIG)
        not_main = self.tmp / "comfy-root" / "server.py"
        not_main.write_text("")
        link = self.tmp / "comfy-root" / "link" / "main.py"
        link.parent.mkdir()
        link.symlink_to(self.tmp / "comfy-root" / "main.py")
        for value in (not_main, link):
            with self.subTest(main=value), patch("app.media_gallery_catalog.os.path.ismount", return_value=True):
                self.assertEqual(main(["--device", "cuda:0"], {**self.env, "KALIV_COMFY_MAIN": str(value)}), EXIT_CONFIG)

    def test_comfyui_folders_must_be_existing_folders_in_the_work_area(self):
        outside = self.tmp / "elsewhere"
        for name in ("input", "output", "temp", "user"):
            (outside / name).mkdir(parents=True)
        with patch("app.media_gallery_catalog.os.path.ismount", return_value=True):
            self.assertEqual(main(["--device", "cuda:0"], {**self.env, "KALIV_COMFY_DIR": str(outside)}), EXIT_CONFIG)
            os.rmdir(self.comfy / "temp")
            self.assertEqual(main(["--device", "cuda:0"], self.env), EXIT_CONFIG)
            self.assertFalse((self.comfy / "temp").exists(), "a missing folder is never created")
            (self.comfy / "temp").mkdir()
            cache_outside = {**self.env, "KALIV_COMFY_WEIGHTS_CACHE": str(outside / "weights.json")}
            self.assertEqual(main(["--device", "cuda:0"], cache_outside), EXIT_CONFIG)

    def test_unpinned_image_to_video_or_clashing_profiles_are_refused(self):
        cases = {
            "no version pin": dict(comfyui_version=None),
            "no weight pins": dict(weights=[]),
            "image to video": dict(tasks=["text_to_video", "image_to_video"]),
        }
        for label, options in cases.items():
            with self.subTest(label), patch("app.media_gallery_catalog.os.path.ismount", return_value=True):
                options = dict(options)
                if options.get("comfyui_version", "x") is None:
                    options.pop("comfyui_version")
                    self.write_video_profile()
                    profile = json.loads((self.tmp / "profiles" / "wan-a.json").read_text())
                    del profile["backend_options"]["comfyui_version"]
                    (self.tmp / "profiles" / "wan-a.json").write_text(json.dumps(profile))
                else:
                    self.write_video_profile(**options)
                self.assertEqual(main(["--device", "cuda:0"], self.env), EXIT_CONFIG)
        self.write_video_profile()
        twin = json.loads((self.tmp / "profiles" / "wan-a.json").read_text())
        twin["profile_id"] = "wan-b"
        (self.tmp / "profiles" / "wan-b.json").write_text(json.dumps(twin))
        with patch("app.media_gallery_catalog.os.path.ismount", return_value=True):
            self.assertEqual(main(["--device", "cuda:0"], {**self.env, "KALIV_MEDIA_PROFILES_ENABLED": "wan-a,wan-b"}),
                             EXIT_CONFIG, "two video profiles on one ComfyUI port")

    def test_an_unmounted_volume_is_still_75_with_video_on(self):
        with patch("app.media_gallery_catalog.os.path.ismount", return_value=False):
            self.assertEqual(main(["--device", "cuda:0"], self.env), EXIT_SINK_UNAVAILABLE)

    # --- running ----------------------------------------------------------------------------
    def test_end_to_end_text_to_video_is_published_job_keyed_to_the_gallery(self):
        with patch("app.media_gallery_catalog.os.path.ismount", return_value=True):
            store = self.store()
            job = store.submit("anders", "a red kite over Nørrebro", profile_id="wan-a", params=VIDEO_PARAMS)["job_id"]
            executor = self.build()
            self.assertEqual(executor.run(max_steps=2, idle_sleep=lambda: None), 0)
            items = self.gallery()["items"]
            row = store.get(job, "anders")
            sink = ExternalMediaSink(self.env["KALIV_MEDIA_ROOT"], self.env["KALIV_MEDIA_VOLUME_ROOT"])
            self.assertEqual((row["state"], row["asset_id"]), ("completed", sink.job_asset_id(job)))
            self.assertEqual([(i["id"], i["kind"], i["mime_type"]) for i in items],
                             [(row["asset_id"], "video", "video/mp4")])
            published = Path(self.env["KALIV_MEDIA_ROOT"], f"{row['asset_id']}.mp4")
            self.assertEqual(published.read_bytes()[4:8], b"ftyp")
            self.assertEqual(os.listdir(self.comfy / "output"), [], "the work-area copy is removed after publication")
            self.assertEqual([n for n in os.listdir(self.env["KALIV_MEDIA_ROOT"]) if n.endswith(".tmp")], [],
                             "no staged leftover on the volume")
            sent = json.loads((self.fake_state / "last_prompt.json").read_text())["prompt"]
            self.assertEqual((sent["6"]["inputs"]["text"], sent["7"]["inputs"]["length"]), ("a red kite over Nørrebro", 33))
            self.assertIsNone(executor.adapter, "the executor stopped its ComfyUI when it returned")
            self.assertTrue(self.lease_is_free(), "and the GPU lease went with it")

    def test_image_and_video_jobs_on_one_executor(self):
        """Release parity: the image smoke contract on the same executor, next to video."""
        with patch("app.media_gallery_catalog.os.path.ismount", return_value=True):
            store = self.store()
            image = store.submit("anders", "a red bicycle", profile_id="sdxl-a",
                                 params={"width": 1024, "height": 1024, "steps": 20})["job_id"]
            video = store.submit("anders", "a red kite", profile_id="wan-a", params=VIDEO_PARAMS)["job_id"]
            executor = self.build({**self.env, "KALIV_MEDIA_PROFILES_ENABLED": "sdxl-a,wan-a"})
            self.assertEqual(executor.run(max_steps=3, idle_sleep=lambda: None), 0)
            kinds = sorted(i["kind"] for i in self.gallery()["items"])
            self.assertEqual([store.get(j, "anders")["state"] for j in (image, video)], ["completed", "completed"])
            self.assertEqual(kinds, ["image", "video"])

    def test_a_render_past_the_profile_deadline_is_stopped_and_nothing_is_published(self):
        self.write_video_profile(max_render_seconds=10)  # the profile minimum
        with patch("app.media_gallery_catalog.os.path.ismount", return_value=True):
            store = self.store()
            job = store.submit("anders", "a slow kite", profile_id="wan-a", params=VIDEO_PARAMS)["job_id"]
            executor = self.build(fake={"FAKE_COMFY_RENDER_SECONDS": "30"})
            started = time.monotonic()
            executor.run(max_steps=2, idle_sleep=lambda: None)
            self.assertLess(time.monotonic() - started, 25, "bounded by the profile (10 s), not by the render (30 s)")
            self.assertEqual(store.get(job, "anders")["state"], "failed")
            self.assertEqual(self.published(), [])

    def test_a_cancel_during_the_render_publishes_nothing_and_cleans_the_work_area(self):
        with patch("app.media_gallery_catalog.os.path.ismount", return_value=True):
            store = self.store()
            job = store.submit("anders", "a kite to cancel", profile_id="wan-a", params=VIDEO_PARAMS)["job_id"]
            executor = self.build(fake={"FAKE_COMFY_RENDER_SECONDS": "4"})
            executor.cancel_poll_s = 0.1

            def cancel_when_running():
                deadline = time.monotonic() + 20
                while time.monotonic() < deadline:
                    if (store.get(job, "anders") or {}).get("state") == "running" and \
                            (self.fake_state / "last_prompt.json").exists():
                        store.request_cancel(job, "anders")
                        return
                    time.sleep(0.05)
            canceller = threading.Thread(target=cancel_when_running, daemon=True)
            canceller.start()
            executor.run(max_steps=2, idle_sleep=lambda: None)
            canceller.join(5)
            self.assertEqual(store.get(job, "anders")["state"], "cancelled")
            self.assertEqual(self.published(), [])
            self.assertEqual(os.listdir(self.comfy / "output"), [], "the cancelled render's file is removed")

    def test_a_volume_lost_during_the_render_stops_the_executor_and_a_restart_recovers_the_job(self):
        from app import media_volume
        with patch("app.media_gallery_catalog.os.path.ismount", return_value=True):
            store = self.store()
            job = store.submit("anders", "a kite", profile_id="wan-a", params=VIDEO_PARAMS)["job_id"]
            executor = self.build()
            real_verify = media_volume.MountedMediaVolume.verify
            calls = {"n": 0}

            def verify(volume):
                # Fine for the start-up and the claim, then gone once the render has been submitted.
                if (self.fake_state / "last_prompt.json").exists():
                    raise ArtifactSinkUnavailable("media_volume_missing")
                calls["n"] += 1
                return real_verify(volume)
            with patch.object(media_volume.MountedMediaVolume, "verify", verify):
                self.assertEqual(executor.run(max_steps=2, idle_sleep=lambda: None), EXIT_SINK_UNAVAILABLE)
            self.assertEqual(self.published(), [], "nothing reached the gallery")
            executor.adapter.close()
            executor.adapter = None
            (self.fake_state / "last_prompt.json").unlink()
            restarted = self.build()
            restarted.run(max_steps=1, idle_sleep=lambda: None)
            row = store.get(job, "anders")
            self.assertIn(row["state"], ("failed",), row)
            self.assertNotEqual(row.get("error"), None)



class PinnedStagedVideoSinkTests(unittest.TestCase):
    def test_the_pinned_volume_is_verified_before_staging_and_before_adoption(self):
        from app.media_executor_main import PinnedStagedVideoSink

        class Volume:
            def __init__(self):
                self.ok, self.calls = True, 0

            def verify(self):
                self.calls += 1
                if not self.ok:
                    raise ArtifactSinkUnavailable("media_volume_replaced")

        class Inner:
            def __init__(self):
                self.staged_calls, self.adopted = 0, []

            def staged(self, extension):
                import contextlib

                @contextlib.contextmanager
                def context():
                    self.staged_calls += 1
                    yield "handle"
                return context()

            def adopt(self, handle, mime):
                self.adopted.append(("adopt", handle))
                return "id-1"

            def adopt_for_job(self, handle, mime, job):
                self.adopted.append((job, handle))
                return "id-2"

        volume, inner = Volume(), Inner()
        sink = PinnedStagedVideoSink(inner, volume)
        with sink.staged(".mp4") as out:
            self.assertEqual(sink.adopt_for_job(out, "video/mp4", "job"), "id-2")
        self.assertEqual((volume.calls, inner.staged_calls, inner.adopted), (2, 1, [("job", "handle")]))
        volume.ok = False
        with self.assertRaises(ArtifactSinkUnavailable):
            with sink.staged(".mp4"):
                pass
        self.assertEqual(inner.staged_calls, 1, "nothing is staged on a volume that is not the pinned one")
        volume.ok = True
        with sink.staged(".mp4") as out:
            volume.ok = False
            with self.assertRaises(ArtifactSinkUnavailable):
                sink.adopt(out, "video/mp4")
        self.assertEqual(len(inner.adopted), 1, "nothing is adopted onto a swapped disk")
        from app.media_generation_contract import JobKeyedStagedSink, StagedFileArtifactSink
        self.assertIsInstance(sink, StagedFileArtifactSink)
        self.assertIsInstance(sink, JobKeyedStagedSink)


if __name__ == "__main__":
    unittest.main()
