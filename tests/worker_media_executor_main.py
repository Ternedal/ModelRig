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
        # G1: the volume's marker, and the two facts a temp dir cannot have (patched for every test;
        # whether the root is a mount point stays per test, through os.path.ismount as before).
        (self.tmp / "volume" / ".kaliv-media-volume").write_text("kaliv-test-volume-1")
        for name, value in (("filesystem", "ext4"), ("system_volume_dev", -1)):
            patcher = patch(f"app.media_volume.SystemProbe.{name}", return_value=value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.write_profile(image_profile(profile_id="sdxl-a", resources={
            "min_usable_gib": 8, "reserve_gib": 2, "devices": ["cuda:0"], "cpu_offload": False}))
        self.env = {
            "KALIV_MEDIA_EXECUTOR": "1",
            "KALIV_MEDIA_JOB_DB": str(self.tmp / "state" / "jobs.sqlite3"),
            "KALIV_MEDIA_ROOT": str(self.tmp / "volume" / "media"),
            "KALIV_MEDIA_VOLUME_ROOT": str(self.tmp / "volume"),
            "KALIV_MEDIA_VOLUME_ID": "kaliv-test-volume-1",
            "KALIV_MEDIA_PROFILE_DIR": str(self.tmp / "profiles"),
            "KALIV_MEDIA_PROFILES_ENABLED": "sdxl-a",
            "KALIV_MEDIA_ALLOW_CANDIDATE_PROFILES": "1",
            "KALIV_GPU_LEASE_DIR": str(self.tmp / "lease"),
            "KALIV_GPU_DEVICE_UUIDS": f"cuda:0={GPU}",
            "CUDA_DEVICE_ORDER": "PCI_BUS_ID",
            "HF_HUB_OFFLINE": "1",
            "TRANSFORMERS_OFFLINE": "1",
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

    def test_a_job_database_that_is_not_a_regular_sqlite_file_is_78_not_a_crash(self):
        # #2337 review 4477759300: a directory raised sqlite3.OperationalError, exit 1, restarted forever.
        (self.tmp / "state" / "a-directory").mkdir()
        real = self.tmp / "state" / "real.sqlite3"
        __import__("sqlite3").connect(real).close()
        (self.tmp / "state" / "a-link").symlink_to(real)
        os.mkfifo(self.tmp / "state" / "a-fifo")
        (self.tmp / "state" / "not-sqlite").write_bytes(b"not a database " * 100)
        import threading
        for name in ("a-directory", "a-link", "a-fifo", "not-sqlite"):
            with self.subTest(name=name), patch("app.media_gallery_catalog.os.path.ismount", return_value=True):
                env = {**self.env, "KALIV_MEDIA_JOB_DB": str(self.tmp / "state" / name)}
                codes = []  # in a thread: SQLite opening a FIFO blocks, and a test must fail, not hang
                worker = threading.Thread(target=lambda: codes.append(main(["--device", "cuda:0"], env)), daemon=True)
                worker.start()
                worker.join(10)
                self.assertEqual(codes, [EXIT_CONFIG], "refused promptly")
        self.assertEqual((self.tmp / "state" / "not-sqlite").read_bytes(), b"not a database " * 100, "untouched")

    def test_an_unmounted_volume_is_75_before_the_job_database_is_inspected(self):
        env = {**self.env, "KALIV_MEDIA_JOB_DB": str(self.tmp / "state")}  # would be 78 if inspected
        with patch("app.media_gallery_catalog.os.path.ismount", return_value=False):
            self.assertEqual(main(["--device", "cuda:0"], env), EXIT_SINK_UNAVAILABLE)

    def test_a_locked_database_is_not_a_configuration_error(self):
        # Transient: exit 1, which the supervisor restarts with back-off; 78 would stop it for good.
        import sqlite3
        with patch("app.media_gallery_catalog.os.path.ismount", return_value=True), \
                patch("app.media_executor_main.ImageJobStore", side_effect=sqlite3.OperationalError("database is locked")):
            with self.assertRaises(sqlite3.OperationalError):
                main(["--device", "cuda:0"], self.env)

    def test_an_unusable_lease_directory_is_a_config_error_not_a_crash(self):
        # #2337 review 4477083816: it used to pass configuration and fail at the first lock (exit 1,
        # restarted forever). Each case must be 78, which the supervisor never restarts.
        (self.tmp / "open-lease").mkdir()
        os.chmod(self.tmp / "open-lease", 0o777)
        (self.tmp / "lease-link").symlink_to(self.tmp / "lease")
        for value in ("relative/lease", str(self.tmp / "no-such-lease"), str(self.tmp / "lease-link"),
                      str(self.tmp / "open-lease")):
            with self.subTest(value=value), patch("app.media_gallery_catalog.os.path.ismount", return_value=True):
                self.assertEqual(main(["--device", "cuda:0"], {**self.env, "KALIV_GPU_LEASE_DIR": value}), EXIT_CONFIG)
        result = self.run_entry({**self.env, "KALIV_GPU_LEASE_DIR": "relative/lease"})  # the real process
        self.assertEqual(result.returncode, EXIT_CONFIG, result.stderr)

    def test_a_lease_error_from_the_running_executor_is_78(self):
        class Breaks:
            def run(self, **kwargs):
                from app.gpu_lease import GpuLeaseError
                raise GpuLeaseError("lease directory must not be group- or world-writable")
        with patch("app.media_executor_main.build_from_env", return_value=Breaks()):
            self.assertEqual(main(["--device", "cuda:0"], self.env), EXIT_CONFIG)

    def test_a_volume_lost_while_running_stops_the_executor_before_the_next_claim(self):
        # #2337 review 4477083808: the volume is checked before every job-database access.
        from app.image_job_store import ImageJobStore
        mounted = [True]
        with patch("app.media_gallery_catalog.os.path.ismount", side_effect=lambda p: mounted[0]):
            store = ImageJobStore(self.env["KALIV_MEDIA_JOB_DB"])
            executor = build_from_env("cuda:0", self.env,
                                      adapter_factory=lambda p: FakeAdapter(p, self.env["KALIV_GPU_LEASE_DIR"]))
            jobs = []

            def unplug_while_idle():  # the executor started and went idle; then a job arrives and the disk goes
                jobs.append(store.submit("anders", "a red bicycle", profile_id="sdxl-a",
                                         params={"width": 1024, "height": 1024, "steps": 20})["job_id"])
                mounted[0] = False
            self.assertEqual(executor.run(max_steps=3, idle_sleep=unplug_while_idle), EXIT_SINK_UNAVAILABLE)
        self.assertEqual(len(jobs), 1, "it was running (one idle tick) before the volume went")
        self.assertEqual(store.get(jobs[0], "anders")["state"], "queued", "not claimed, not rendered")

    def test_offline_mode_is_required_and_a_missing_flag_leaves_the_queue_untouched(self):
        # #2337 review 4477167705: the diffusers adapter refuses to load without these, which used to
        # turn every claimed job into generation_failed. Now it is 78 before anything is claimed.
        from app.image_job_store import ImageJobStore
        store = ImageJobStore(self.env["KALIV_MEDIA_JOB_DB"])
        job = store.submit("anders", "a red bicycle", profile_id="sdxl-a",
                           params={"width": 1024, "height": 1024, "steps": 20})["job_id"]
        for flag in ("HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE"):
            for value in (None, "0", "true"):
                env = {k: v for k, v in self.env.items() if k != flag}
                if value is not None:
                    env[flag] = value
                with self.subTest(flag=flag, value=value), \
                        patch("app.media_gallery_catalog.os.path.ismount", return_value=True), \
                        patch("app.media_executor_main.MediaExecutor.run",
                              side_effect=AssertionError("the executor must not start")):  # fail fast, never hang
                    self.assertEqual(main(["--device", "cuda:0"], env), EXIT_CONFIG)
        self.assertEqual(store.get(job, "anders")["state"], "queued", "nothing claimed")
        result = self.run_entry({k: v for k, v in self.env.items() if k != "HF_HUB_OFFLINE"})
        self.assertEqual(result.returncode, EXIT_CONFIG, result.stderr)
        self.assertIn("never a download", result.stderr)

    def test_the_default_adapter_sees_the_same_environment_that_was_checked(self):
        from app.media_executor_main import default_adapter_factory
        from app.media_generation_profiles import parse_profile
        adapter = default_adapter_factory("cuda:0", self.env["KALIV_GPU_LEASE_DIR"], self.env)(
            parse_profile(image_profile(profile_id="sdxl-a", resources={
                "min_usable_gib": 8, "reserve_gib": 2, "devices": ["cuda:0"], "cpu_offload": False})))
        self.assertIs(adapter._env, self.env)

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

    def test_g1_volume_configuration_is_78_and_an_absent_or_foreign_volume_is_75(self):
        with patch("app.media_gallery_catalog.os.path.ismount", return_value=True):
            for env in ({k: v for k, v in self.env.items() if k != "KALIV_MEDIA_VOLUME_ID"},
                        {**self.env, "KALIV_MEDIA_VOLUME_ID": "bad id"}):
                with self.subTest(id=env.get("KALIV_MEDIA_VOLUME_ID")):
                    self.assertEqual(main(["--device", "cuda:0"], env), EXIT_CONFIG)
            with patch("app.media_volume.SystemProbe.filesystem", return_value="exfat"):
                self.assertEqual(main(["--device", "cuda:0"], self.env), EXIT_CONFIG, "no stable file ids")
            with patch("app.media_volume.SystemProbe.system_volume_dev",
                       return_value=os.lstat(self.tmp / "volume").st_dev):
                self.assertEqual(main(["--device", "cuda:0"], self.env), EXIT_CONFIG, "the system disk")
            # another disk at the same path: its marker does not match
            self.assertEqual(main(["--device", "cuda:0"], {**self.env, "KALIV_MEDIA_VOLUME_ID": "kaliv-other-disk-1"}),
                             EXIT_SINK_UNAVAILABLE)
        self.assertFalse(Path(self.env["KALIV_MEDIA_JOB_DB"]).exists(), "nothing written before the volume is proven")

    def test_a_disk_swapped_while_running_stops_the_executor_before_the_next_claim(self):
        # G1 pins the volume's identity at start: the same marker on another disk is not enough.
        from app.image_job_store import ImageJobStore
        volume = self.tmp / "volume"
        with patch("app.media_gallery_catalog.os.path.ismount", return_value=True):
            store = ImageJobStore(self.env["KALIV_MEDIA_JOB_DB"])
            executor = build_from_env("cuda:0", self.env,
                                      adapter_factory=lambda p: FakeAdapter(p, self.env["KALIV_GPU_LEASE_DIR"]))
            jobs = []

            def swap_disk():
                jobs.append(store.submit("anders", "a red bicycle", profile_id="sdxl-a",
                                         params={"width": 1024, "height": 1024, "steps": 20})["job_id"])
                volume.rename(self.tmp / "volume-old")
                (volume / "media").mkdir(parents=True)
                (volume / ".kaliv-media-volume").write_text("kaliv-test-volume-1")
            self.assertEqual(executor.run(max_steps=3, idle_sleep=swap_disk), EXIT_SINK_UNAVAILABLE)
        self.assertEqual(len(jobs), 1)
        self.assertEqual(store.get(jobs[0], "anders")["state"], "queued", "not claimed on the other disk")

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
