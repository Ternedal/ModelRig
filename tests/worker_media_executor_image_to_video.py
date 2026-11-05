#!/usr/bin/env python3
"""image_to_video through the executor (#2296 6635978072, seam #2339): the owner-gated source.

Real ComfySupervisor + ComfyVideoAdapter + fake ComfyUI (which records the exact bytes its
LoadImage would read); the source reader is injected, as ChatGPT's read_owned_source_png is in
production.

Run: PYTHONPATH=worker python3 tests/worker_media_executor_image_to_video.py
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for extra in (ROOT / "worker", ROOT / "tests"):
    sys.path.insert(0, str(extra))

from app.comfy_video_adapter import ComfyVideoAdapter  # noqa: E402
from app.media_executor import ExecutorConfigError, MediaExecutor  # noqa: E402
from app.media_generation_contract import ArtifactSinkUnavailable, SourceImageUnavailable  # noqa: E402
from app.media_generation_profiles import parse_profile  # noqa: E402
import worker_media_executor as base  # noqa: E402  (module import: its test classes must not run here)
from worker_comfy_image_to_video import I2V, png  # noqa: E402
from worker_comfy_video_adapter import raw, sha  # noqa: E402
from worker_media_generation_profiles import video_profile  # noqa: E402


class ImageToVideoExecutorTests(unittest.TestCase):
    setUp, tearDown = base.VideoExecutorTests.setUp, base.VideoExecutorTests.tearDown

    def i2v_executor(self, reader, render_seconds="0.2"):
        Path(self.dirs["templates"], "wan-i2v.json").write_bytes(raw(I2V))
        profile = parse_profile(video_profile(
            profile_id="wan-i2v", tasks=["image_to_video"],
            limits={"max_prompt_chars": 200, "sizes": [[832, 480]], "max_steps": 30, "max_frames": 81},
            backend_options={"template_name": "wan-i2v.json", "template_sha256": sha(raw(I2V)), "fps": 16,
                             "max_render_seconds": 60, "max_output_bytes": 1024 * 1024, "port": self.port}))
        loads = []

        def counting_factory(p):
            loads.append(p.profile_id)
            return self._factory(p)
        self._factory = self.real_factory(render_seconds)
        ex = MediaExecutor(self.store, gpu_uuid=base.GPU_A, profiles={profile.profile_id: profile},
                           adapter_factory=counting_factory, lease_dir=self.lease_dir, video_sink=self.sink,
                           cancel_poll_s=0.1, source_reader=reader)
        ex.start()
        self.executors.append(ex)
        return ex, loads

    def real_factory(self, render_seconds):
        from app.comfy_supervisor import ComfyLaunch
        from worker_comfy_supervisor import FAKE_MAIN, AnyExistingDirectory, FakeSupervisor

        def factory(profile):
            launch = ComfyLaunch(python_executable=sys.executable, main_py=str(FAKE_MAIN), port=self.port,
                                 input_directory=self.dirs["input"], output_directory=self.dirs["output"],
                                 temp_directory=self.dirs["temp"], user_directory=self.dirs["user"])
            sup = FakeSupervisor(fake_env={"FAKE_COMFY_STATE_DIR": self.dirs["state"],
                                           "FAKE_COMFY_RENDER_SECONDS": render_seconds},
                                 media_volume=AnyExistingDirectory(), gpu_uuid=base.GPU_A, lease_dir=self.lease_dir,
                                 launch=launch, reserve_gib=2, min_usable_gib=8, ready_timeout_s=15, stop_timeout_s=5,
                                 poll_s=0.05, base_env={"PATH": os.environ.get("PATH", "")})
            adapter = ComfyVideoAdapter(profile, supervisor=sup, template_dir=self.dirs["templates"],
                                        output_directory=self.dirs["output"], poll_s=0.05, settle_s=0.05)
            self.adapters.append(adapter)
            return adapter
        return factory

    def submit(self, owner="anders", asset="a" * 32, **extra):
        return self.store.submit(owner, "the kite takes off", profile_id="wan-i2v",
                                 params={"task": "image_to_video", "width": 832, "height": 480, "steps": 20,
                                         "frames": 33, "input_asset_id": asset, **extra})["job_id"]

    def test_the_source_of_the_jobs_own_owner_reaches_comfyui_and_the_job_completes(self):
        calls, source = [], png()
        ex, loads = self.i2v_executor(lambda owner, asset: calls.append((owner, asset)) or source)
        job = self.submit()
        self.assertEqual(ex.step(), "completed")
        self.assertEqual(calls, [("anders", "a" * 32)], "the claimed row's owner, read once")
        seen = json.loads(Path(self.dirs["state"], "loadimage.json").read_text())
        self.assertEqual([(s["sha256"], s["bytes"]) for s in seen], [(hashlib.sha256(source).hexdigest(), len(source))])
        row = self.store.get(job, "anders")
        self.assertEqual(row["state"], "completed")
        self.assertIn(row["asset_id"], self.sink.registry)
        self.assertEqual(os.listdir(self.dirs["input"]), [], "the staged source is removed")

    def test_an_owner_in_the_parameters_is_never_used(self):
        calls = []
        ex, _ = self.i2v_executor(lambda owner, asset: calls.append(owner) or png())
        job = self.store.submit("anders", "x", profile_id="wan-i2v",
                                params={"task": "image_to_video", "width": 832, "height": 480, "steps": 20,
                                        "frames": 33, "input_asset_id": "a" * 32, "owner": "eve"})["job_id"]
        self.assertEqual(ex.step(), "rejected", "unknown parameters are refused before any read")
        self.assertEqual(calls, [])
        self.assertEqual(self.store.get(job, "anders")["error"], "generation_request_rejected")

    def test_an_asset_level_refusal_fails_only_that_job_before_any_gpu_work(self):
        def reader(owner, asset):
            if asset == "b" * 32:
                raise SourceImageUnavailable("source_image_not_authorized")
            return png()
        ex, loads = self.i2v_executor(reader)
        refused, fine = self.submit(asset="b" * 32), self.submit()
        self.assertEqual(ex.step(), "failed")
        self.assertEqual(loads, [], "refused before the GPU was touched")
        row = self.store.get(refused, "anders")
        self.assertEqual((row["state"], row["error"]), ("failed", "source_image_unavailable"))
        self.assertEqual(ex.step(), "completed", "the executor continues with the next job")
        self.assertEqual(self.store.get(fine, "anders")["state"], "completed")

    def test_a_reader_returning_nothing_usable_fails_the_job(self):
        for bad in (b"", bytearray(png()), None):
            with self.subTest(bad=type(bad).__name__):
                ex, loads = self.i2v_executor(lambda owner, asset, bad=bad: bad)
                job = self.submit()
                self.assertEqual(ex.step(), "failed")
                self.assertEqual(self.store.get(job, "anders")["error"], "source_image_unavailable")
                self.assertEqual(loads, [])
                ex.release_lock()

    def test_a_lost_volume_while_reading_is_exit_75_and_the_job_is_recovered(self):
        def reader(owner, asset):
            raise ArtifactSinkUnavailable("source_index_unavailable")
        ex, _ = self.i2v_executor(reader)
        job = self.submit()
        with self.assertRaises(ArtifactSinkUnavailable):  # run() maps it to exit 75 (tested in the G2 suite)
            ex.step()
        self.assertEqual(self.store.get(job, "anders")["state"], "running", "left for recovery")
        ex.release_lock()  # the process ends
        ex2, _ = self.i2v_executor(lambda owner, asset: png())  # the next start of this GPU's executor
        row = self.store.get(job, "anders")
        self.assertEqual((row["state"], row["error"]), ("failed", "interrupted by restart"))
        del ex2

    def test_an_id_the_reader_rejects_is_a_rejected_request(self):
        def reader(owner, asset):
            raise ValueError("invalid_asset_id")
        ex, loads = self.i2v_executor(reader)
        job = self.submit()
        self.assertEqual(ex.step(), "rejected")
        self.assertEqual(self.store.get(job, "anders")["error"], "generation_request_rejected")
        self.assertEqual(loads, [])

    def test_image_to_video_needs_a_reader(self):
        with self.assertRaisesRegex(ExecutorConfigError, "owner-gated source reader"):
            self.i2v_executor(None)

    def test_a_text_to_video_job_never_calls_the_reader(self):
        calls = []
        Path(self.dirs["templates"], "wan-t2v.json").write_bytes(raw())
        profile = base.VideoExecutorTests.profile(self)
        ex = MediaExecutor(self.store, gpu_uuid=base.GPU_A, profiles={profile.profile_id: profile},
                           adapter_factory=self.real_factory("0.2"), lease_dir=self.lease_dir, video_sink=self.sink,
                           source_reader=lambda o, a: calls.append(o) or png())
        ex.start()
        self.executors.append(ex)
        base.VideoExecutorTests.submit(self)
        self.assertEqual(ex.step(), "completed")
        self.assertEqual(calls, [])


class VolumeVersusAssetTests(unittest.TestCase):
    """#2339 review note (ChatGPT 6666214754, P3): an EIO while reading the source because the
    volume went away must not be recorded as a per-asset "source_image_unavailable". In
    production the job store is opened with the media volume as its guard (G2b,
    media_executor_main), and recording the failure is a store access: the guard turns it into
    ArtifactSinkUnavailable (exit 75), the job stays for recovery, and nothing blames the asset."""
    setUp, tearDown = ImageToVideoExecutorTests.setUp, ImageToVideoExecutorTests.tearDown
    i2v_executor, real_factory, submit = (ImageToVideoExecutorTests.i2v_executor, ImageToVideoExecutorTests.real_factory,
                                          ImageToVideoExecutorTests.submit)

    def test_a_volume_lost_mid_read_is_exit_75_not_a_missing_asset(self):
        from app.image_job_store import ImageJobStore
        mounted = [True]

        def volume_guard():
            if not mounted[0]:
                raise ArtifactSinkUnavailable("external_media_unavailable")
        self.store = ImageJobStore(self.store.path, volume_guard=volume_guard)  # as media_executor_main opens it

        def reader(owner, asset):  # the read fails with EIO because the disk went away
            mounted[0] = False
            raise SourceImageUnavailable("source_image_read_failed")
        ex, loads = self.i2v_executor(reader)
        job = self.submit()
        with self.assertRaises(ArtifactSinkUnavailable):
            ex.step()
        self.assertEqual(loads, [], "no GPU work")
        mounted[0] = True
        row = self.store.get(job, "anders")
        self.assertEqual((row["state"], row["error"]), ("running", None), "left for recovery, the asset is not blamed")
        ex.release_lock()


class RealReaderTests(unittest.TestCase):
    """The production seam end to end: ChatGPT's read_owned_source_png over the real gallery sink and
    the real job store -- the source must be a completed asset of the same owner."""
    setUp, tearDown = ImageToVideoExecutorTests.setUp, ImageToVideoExecutorTests.tearDown
    i2v_executor, real_factory, submit = (ImageToVideoExecutorTests.i2v_executor, ImageToVideoExecutorTests.real_factory,
                                          ImageToVideoExecutorTests.submit)

    def completed_image(self, sink, owner):
        """A finished image job of `owner`, published job-keyed into the gallery, as the executor does."""
        job = self.store.submit(owner, "a red bicycle", profile_id="sdxl-a", max_owner_active=16)["job_id"]
        instance = base.GPU_A + ":" + "e" * 16
        self.assertEqual(self.store.claim_for(["sdxl-a"], instance)["id"], job)
        self.assertTrue(self.store.begin_publish(job, instance))
        asset = sink.publish_and_register_for_job(job, png(), ".png")
        self.assertTrue(self.store.complete(job, instance, asset))
        return asset

    def test_the_owners_own_completed_image_drives_the_video_and_anothers_does_not(self):
        from unittest.mock import patch
        from app.media_gallery_store import ExternalMediaSink
        from app.media_source_image import read_owned_source_png
        volume = Path(self.tmp, "volume")
        (volume / "media").mkdir(parents=True)
        with patch("app.media_gallery_catalog.os.path.ismount", side_effect=lambda p: Path(p) == volume):
            sink = ExternalMediaSink(str(volume / "media"), str(volume))
            asset = self.completed_image(sink, "anders")
            ex, loads = self.i2v_executor(lambda owner, asset_id: read_owned_source_png(sink, self.store, owner, asset_id))
            mine = self.submit(owner="anders", asset=asset)
            self.assertEqual(ex.step(), "completed")
            seen = json.loads(Path(self.dirs["state"], "loadimage.json").read_text())
            self.assertEqual(seen[0]["sha256"], hashlib.sha256(png()).hexdigest())
            theirs = self.submit(owner="eve", asset=asset)  # eve names anders' asset
            self.assertEqual(ex.step(), "failed")
            unknown = self.submit(owner="anders", asset="f" * 32)
            self.assertEqual(ex.step(), "failed")
        self.assertEqual(self.store.get(mine, "anders")["state"], "completed")
        self.assertEqual(self.store.get(theirs, "eve")["error"], "source_image_unavailable")
        self.assertEqual(self.store.get(unknown, "anders")["error"], "source_image_unavailable")


if __name__ == "__main__":
    unittest.main()
