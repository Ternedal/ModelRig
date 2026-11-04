#!/usr/bin/env python3
"""The media executor's entry point (G2b, ModelRig #2296 6636146026): configuration, exit codes, end to end.

Run: PYTHONPATH=worker python3 tests/worker_media_executor_main.py
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
for extra in (ROOT / "worker", ROOT / "tests"):
    sys.path.insert(0, str(extra))

from app.gpu_lease import acquire_gpu_lease  # noqa: E402
from app.media_executor import EXIT_CONFIG, EXIT_SINK_UNAVAILABLE  # noqa: E402
from app.media_executor_main import build_from_env, main  # noqa: E402
from app.media_generation_contract import RenderedArtifact  # noqa: E402
from worker_media_generation_profiles import image_profile, video_profile  # noqa: E402

GPU = "GPU-6a7f0c2e-1b2d-4c3e-8f9a-0123456789ab"
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32


class FakeAdapter:
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


class EntryPointTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        for name in ("lease", "profiles", "volume/media", "state"):
            (self.tmp / name).mkdir(parents=True)
        os.chmod(self.tmp / "lease", 0o700)
        self.write_profile(image_profile(profile_id="sdxl-a", resources={
            "min_usable_gib": 8, "reserve_gib": 2, "devices": ["cuda:0"], "cpu_offload": False}))
        self.env = {
            "KALIV_MEDIA_EXECUTOR": "1",
            "KALIV_MEDIA_JOB_DB": str(self.tmp / "state" / "jobs.sqlite3"),
            "KALIV_MEDIA_ROOT": str(self.tmp / "volume" / "media"),
            "KALIV_MEDIA_VOLUME_ROOT": str(self.tmp / "volume"),
            "KALIV_MEDIA_PROFILE_DIR": str(self.tmp / "profiles"),
            "KALIV_MEDIA_PROFILES_ENABLED": "sdxl-a",
            "KALIV_MEDIA_ALLOW_CANDIDATE_PROFILES": "1",
            "KALIV_GPU_LEASE_DIR": str(self.tmp / "lease"),
            "KALIV_GPU_DEVICE_UUIDS": f"cuda:0={GPU}",
            "CUDA_DEVICE_ORDER": "PCI_BUS_ID",
        }

    def write_profile(self, profile):
        Path(self.tmp, "profiles", f"{profile['profile_id']}.json").write_text(json.dumps(profile))

    def run_entry(self, env):
        """The real process, as the Go supervisor starts it: the exit code is what it sees."""
        return subprocess.run([sys.executable, "-m", "app.media_executor_main", "--device", "cuda:0"],
                              env={"PATH": os.environ.get("PATH", ""), "PYTHONPATH": str(ROOT / "worker"),
                                   "PYTHONDONTWRITEBYTECODE": "1", **env},
                              capture_output=True, text=True, timeout=60)

    def test_the_switch_is_required(self):
        self.assertEqual(main(["--device", "cuda:0"], {**self.env, "KALIV_MEDIA_EXECUTOR": "0"}), EXIT_CONFIG)
        result = self.run_entry({k: v for k, v in self.env.items() if k != "KALIV_MEDIA_EXECUTOR"})
        self.assertEqual(result.returncode, EXIT_CONFIG, result.stderr)
        self.assertIn("is off", result.stderr)

    def test_paths_must_be_absolute_and_present(self):
        for name in ("KALIV_MEDIA_JOB_DB", "KALIV_MEDIA_ROOT", "KALIV_MEDIA_VOLUME_ROOT", "KALIV_MEDIA_PROFILE_DIR"):
            for value in ("", "relative/path"):
                with self.subTest(name=name, value=value):
                    self.assertEqual(main(["--device", "cuda:0"], {**self.env, name: value}), EXIT_CONFIG)
        missing_parent = {**self.env, "KALIV_MEDIA_JOB_DB": str(self.tmp / "no-such-dir" / "jobs.sqlite3")}
        with patch("app.media_gallery_catalog.os.path.ismount", return_value=True):
            self.assertEqual(main(["--device", "cuda:0"], missing_parent), EXIT_CONFIG)
        self.assertFalse((self.tmp / "no-such-dir").exists(), "a missing directory is never created")

    def test_gpu_configuration_is_required(self):
        for change in ({"KALIV_GPU_DEVICE_UUIDS": ""}, {"CUDA_DEVICE_ORDER": ""}, {"KALIV_GPU_LEASE_DIR": ""}):
            with self.subTest(change=change):
                self.assertEqual(main(["--device", "cuda:0"], {**self.env, **change}), EXIT_CONFIG)
        self.assertEqual(main(["--device", "cuda:3"], self.env), EXIT_CONFIG, "no UUID for this device")
        # The profile allows cuda:0, but only cuda:1 has a UUID: refused before the volume is even looked at.
        self.assertEqual(main(["--device", "cuda:0"], {**self.env, "KALIV_GPU_DEVICE_UUIDS": f"cuda:1={GPU}"}),
                         EXIT_CONFIG, "no UUID for the executor's own device")

    def test_no_enabled_profile_for_this_device_is_a_config_error(self):
        self.assertEqual(main(["--device", "cuda:1"], {**self.env, "KALIV_GPU_DEVICE_UUIDS": f"cuda:1={GPU}"}),
                         EXIT_CONFIG)

    def test_a_video_profile_is_refused_until_a_staged_sink_exists(self):
        self.write_profile(video_profile(profile_id="wan-a", tasks=["text_to_video"], resources={
            "min_usable_gib": 8, "reserve_gib": 2, "devices": ["cuda:0"], "cpu_offload": False}))
        env = {**self.env, "KALIV_MEDIA_PROFILES_ENABLED": "wan-a"}
        with patch("app.media_gallery_catalog.os.path.ismount", return_value=True):
            self.assertEqual(main(["--device", "cuda:0"], env), EXIT_CONFIG)

    def test_an_unmounted_volume_exits_75_from_the_real_process(self):
        result = self.run_entry(self.env)  # a plain temp dir is not a mount point
        self.assertEqual(result.returncode, EXIT_SINK_UNAVAILABLE, result.stderr)
        self.assertIn("volume is not available", result.stderr)
        self.assertFalse(Path(self.env["KALIV_MEDIA_JOB_DB"]).exists(), "nothing written before the volume is proven")

    def test_end_to_end_a_job_is_published_job_keyed_to_the_gallery(self):
        from app.image_job_store import ImageJobStore
        from app.media_gallery_catalog import list_gallery
        from app.media_gallery_store import ExternalMediaSink
        with patch("app.media_gallery_catalog.os.path.ismount", return_value=True):
            store = ImageJobStore(self.env["KALIV_MEDIA_JOB_DB"])
            job = store.submit("anders", "a red bicycle", profile_id="sdxl-a",
                               params={"width": 1024, "height": 1024, "steps": 20})["job_id"]
            executor = build_from_env("cuda:0", self.env,
                                      adapter_factory=lambda p: FakeAdapter(p, self.env["KALIV_GPU_LEASE_DIR"]))
            self.assertEqual(executor.run(max_steps=2, idle_sleep=lambda: None), 0)
            sink = ExternalMediaSink(self.env["KALIV_MEDIA_ROOT"], self.env["KALIV_MEDIA_VOLUME_ROOT"])
            items = list_gallery(self.env["KALIV_MEDIA_ROOT"], verified_volume_root=self.env["KALIV_MEDIA_VOLUME_ROOT"])["items"]
        row = store.get(job, "anders")
        self.assertEqual((row["state"], row["asset_id"]), ("completed", sink.job_asset_id(job)))
        self.assertEqual([item["id"] for item in items], [row["asset_id"]])


if __name__ == "__main__":
    unittest.main()
