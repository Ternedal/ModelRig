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
from app.media_executor_main import _on_one_device as real_on_one_device, build_from_env, main  # noqa: E402
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
        for name in ("lease", "profiles", "volume/media", "work/state"):
            (self.tmp / name).mkdir(parents=True)
        os.chmod(self.tmp / "lease", 0o700)
        # Anders, 6 Nov: generate in a private work area on the internal disk, publish on the volume.
        # The job database is in the work area. A temp dir cannot be on another filesystem type or
        # device than the volume, so those two facts are patched for every test (and tested below).
        self.state = self.tmp / "work" / "state"
        os.chmod(self.tmp / "work", 0o700)
        for target, value in (("app.media_work_area.WorkAreaProbe.containing_filesystem", ("ext4", False)),
                              ("app.media_executor_main._on_one_device", False)):
            patcher = patch(target, return_value=value)
            patcher.start()
            self.addCleanup(patcher.stop)
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
            "KALIV_MEDIA_WORK_ROOT": str(self.tmp / "work"),
            "KALIV_MEDIA_JOB_DB": str(self.state / "jobs.sqlite3"),
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
        for name in ("KALIV_MEDIA_JOB_DB", "KALIV_MEDIA_ROOT", "KALIV_MEDIA_VOLUME_ROOT", "KALIV_MEDIA_PROFILE_DIR",
                     "KALIV_MEDIA_WORK_ROOT"):
            for value in ("", "relative/path"):
                with self.subTest(name=name, value=value):
                    self.assertEqual(main(["--device", "cuda:0"], {**self.env, name: value}), EXIT_CONFIG)
        missing_parent = {**self.env, "KALIV_MEDIA_JOB_DB": str(self.tmp / "work" / "no-such-dir" / "jobs.sqlite3")}
        with patch("app.media_gallery_catalog.os.path.ismount", return_value=True):
            self.assertEqual(main(["--device", "cuda:0"], missing_parent), EXIT_CONFIG)
        self.assertFalse((self.tmp / "work" / "no-such-dir").exists(), "a missing directory is never created")

    def test_a_job_database_that_is_not_a_regular_sqlite_file_is_78_not_a_crash(self):
        # #2337 review 4477759300: a directory raised sqlite3.OperationalError, exit 1, restarted forever.
        (self.state / "a-directory").mkdir()
        real = self.state / "real.sqlite3"
        __import__("sqlite3").connect(real).close()
        (self.state / "a-link").symlink_to(real)
        os.mkfifo(self.state / "a-fifo")
        (self.state / "not-sqlite").write_bytes(b"not a database " * 100)
        import threading
        for name in ("a-directory", "a-link", "a-fifo", "not-sqlite"):
            with self.subTest(name=name), patch("app.media_gallery_catalog.os.path.ismount", return_value=True):
                env = {**self.env, "KALIV_MEDIA_JOB_DB": str(self.state / name)}
                codes = []  # in a thread: SQLite opening a FIFO blocks, and a test must fail, not hang
                worker = threading.Thread(target=lambda: codes.append(main(["--device", "cuda:0"], env)), daemon=True)
                worker.start()
                worker.join(10)
                self.assertEqual(codes, [EXIT_CONFIG], "refused promptly")
        self.assertEqual((self.state / "not-sqlite").read_bytes(), b"not a database " * 100, "untouched")

    def test_an_unmounted_volume_is_75_before_the_job_database_is_inspected(self):
        env = {**self.env, "KALIV_MEDIA_JOB_DB": str(self.state)}  # would be 78 if inspected
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

    # -- Anders, 6 Nov 2026 (#2275 6686905826): generate on the internal disk, publish on the volume --

    def test_the_work_area_is_checked_at_start_and_any_failure_is_78(self):
        work = self.tmp / "work"
        link = self.tmp / "work-link"
        link.symlink_to(work)
        with patch("app.media_gallery_catalog.os.path.ismount", return_value=True):
            for value, why in ((str(self.tmp / "absent"), "missing"), (str(link), "a link"),
                               ("relative/work", "relative")):
                with self.subTest(why=why):
                    self.assertEqual(main(["--device", "cuda:0"], {**self.env, "KALIV_MEDIA_WORK_ROOT": value}),
                                     EXIT_CONFIG)
            os.chmod(work, 0o750)
            self.assertEqual(main(["--device", "cuda:0"], self.env), EXIT_CONFIG, "others can read prompts")
            os.chmod(work, 0o700)
            for fs in (("nfs4", False), ("ntfs", True), (None, False)):
                with self.subTest(fs=fs), patch("app.media_work_area.WorkAreaProbe.containing_filesystem",
                                                return_value=fs):
                    self.assertEqual(main(["--device", "cuda:0"], self.env), EXIT_CONFIG, "network or unknown")
        self.assertFalse(Path(self.env["KALIV_MEDIA_JOB_DB"]).exists(), "nothing written before the work area is proven")

    def test_the_job_database_must_be_in_the_work_area(self):
        outside = self.tmp / "elsewhere"
        outside.mkdir()
        elsewhere = self.tmp / "work" / "jump"
        elsewhere.symlink_to(outside)
        cases = {"on the publication volume": self.tmp / "volume" / "jobs.sqlite3",
                 "outside both": outside / "jobs.sqlite3",
                 "behind a link in the work area": elsewhere / "jobs.sqlite3"}
        with patch("app.media_gallery_catalog.os.path.ismount", return_value=True), \
                patch("app.media_executor_main.MediaExecutor.run",
                      side_effect=AssertionError("a refused configuration must never run")):
            for why, path in cases.items():
                with self.subTest(why=why):
                    self.assertEqual(main(["--device", "cuda:0"], {**self.env, "KALIV_MEDIA_JOB_DB": str(path)}),
                                     EXIT_CONFIG)
        for path in cases.values():
            self.assertFalse(Path(path).exists(), f"no database was created at {path}")

    def test_a_job_database_moved_in_with_its_old_permissions_is_78(self):
        # On Windows a same-disk move keeps the file's old ACL; the per-entry check catches it there.
        __import__("sqlite3").connect(self.env["KALIV_MEDIA_JOB_DB"]).close()
        Path(self.env["KALIV_MEDIA_JOB_DB"] + "-wal").write_bytes(b"")
        # Every folder and file private (POSIX modes stand in for the Windows ACL here), so the only
        # refusal below is the one patched in.
        for path, mode in ((self.state, 0o700), (self.env["KALIV_MEDIA_JOB_DB"], 0o600),
                           (self.env["KALIV_MEDIA_JOB_DB"] + "-wal", 0o600)):
            os.chmod(path, mode)
        for leaky in ("", "-wal"):
            refused = {self.env["KALIV_MEDIA_JOB_DB"] + leaky}
            real_private = __import__("app.media_work_area", fromlist=["WorkAreaProbe"]).WorkAreaProbe.private

            def private(probe, path, info, refused=refused, real=real_private):
                return (False, "test: Users can read it") if path in refused else real(probe, path, info)
            with self.subTest(file=leaky or "the database"), \
                    patch("app.media_gallery_catalog.os.path.ismount", return_value=True), \
                    patch("app.media_work_area.WorkAreaProbe.acl_per_entry", new=True), \
                    patch("app.media_work_area.WorkAreaProbe.private", private), \
                    patch("app.media_executor_main.MediaExecutor.run",
                          side_effect=AssertionError("a refused configuration must never run")):
                self.assertEqual(main(["--device", "cuda:0"], self.env), EXIT_CONFIG)
        with patch("app.media_gallery_catalog.os.path.ismount", return_value=True), \
                patch("app.media_work_area.WorkAreaProbe.acl_per_entry", new=True), \
                patch("app.media_executor_main.MediaExecutor.run", return_value=0):
            self.assertEqual(main(["--device", "cuda:0"], self.env), 0, "private files are accepted")

    def test_the_work_area_must_not_be_on_the_publication_volume(self):
        with patch("app.media_gallery_catalog.os.path.ismount", return_value=True), \
                patch("app.media_executor_main._on_one_device", return_value=True):
            self.assertEqual(main(["--device", "cuda:0"], self.env), EXIT_CONFIG)

        class Work:
            device = os.stat(self.tmp / "work").st_dev

        class Volume:
            root = self.tmp / "volume"

        self.assertTrue(real_on_one_device(Work(), Volume()), "the real check compares the devices")
        Work.device += 1
        self.assertFalse(real_on_one_device(Work(), Volume()))

    def test_a_work_area_that_changes_while_running_stops_the_executor_before_the_next_claim(self):
        from app.image_job_store import ImageJobStore
        work = self.tmp / "work"
        with patch("app.media_gallery_catalog.os.path.ismount", return_value=True):
            store = ImageJobStore(self.env["KALIV_MEDIA_JOB_DB"])
            executor = build_from_env("cuda:0", self.env,
                                      adapter_factory=lambda p: FakeAdapter(p, self.env["KALIV_GPU_LEASE_DIR"]))
            jobs = []

            def opened_up():  # running and idle; then a job arrives and the work area is opened to others
                jobs.append(store.submit("anders", "a red bicycle", profile_id="sdxl-a",
                                         params={"width": 1024, "height": 1024, "steps": 20})["job_id"])
                os.chmod(work, 0o755)
            self.assertEqual(executor.run(max_steps=3, idle_sleep=opened_up), EXIT_SINK_UNAVAILABLE)
        os.chmod(work, 0o700)
        self.assertEqual(len(jobs), 1)
        self.assertEqual(store.get(jobs[0], "anders")["state"], "queued", "not claimed, not rendered")

    def test_a_full_disk_while_publishing_an_image_stops_the_executor_and_shows_nothing(self):
        # Track 2: the image path publishes bytes (ExternalMediaSink, used unchanged). A full volume
        # is the volume being unusable: exit 75, not a failed job and on to the next claim.
        import errno
        from app.image_job_store import ImageJobStore
        from app.media_gallery_catalog import list_gallery
        from app.media_gallery_store import ExternalMediaSink
        with patch("app.media_gallery_catalog.os.path.ismount", return_value=True):
            store = ImageJobStore(self.env["KALIV_MEDIA_JOB_DB"])
            jobs = [store.submit("anders", "a red bicycle", profile_id="sdxl-a",
                                 params={"width": 1024, "height": 1024, "steps": 20})["job_id"] for _ in range(2)]
            executor = build_from_env("cuda:0", self.env,
                                      adapter_factory=lambda p: FakeAdapter(p, self.env["KALIV_GPU_LEASE_DIR"]))
            with patch("app.media_gallery_store.os.fsync", side_effect=OSError(errno.ENOSPC, "No space left on device")):
                self.assertEqual(executor.run(max_steps=3, idle_sleep=lambda: None), EXIT_SINK_UNAVAILABLE)
            self.assertEqual(store.get(jobs[0], "anders")["state"], "publishing", "left for recovery, not failed")
            self.assertEqual(store.get(jobs[1], "anders")["state"], "queued", "the next job was never claimed")
            sink = ExternalMediaSink(self.env["KALIV_MEDIA_ROOT"], self.env["KALIV_MEDIA_VOLUME_ROOT"])
            self.assertFalse(Path(self.env["KALIV_MEDIA_ROOT"], "gallery-index.json").exists(), "nothing was indexed")
            self.assertEqual((sink.inspect_temporary_files(), sink.inspect_unindexed_assets()), ([], []),
                             "no partial file and nothing unindexed")
            if executor.adapter is not None:  # what the process exit does: the GPU lease goes with it
                executor.adapter.close()
            # Space is back: the restart fails the interrupted job and publishes the next one.
            executor = build_from_env("cuda:0", self.env,
                                      adapter_factory=lambda p: FakeAdapter(p, self.env["KALIV_GPU_LEASE_DIR"]))
            self.assertEqual(executor.run(max_steps=2, idle_sleep=lambda: None), 0)
        self.assertEqual((store.get(jobs[0], "anders")["state"], store.get(jobs[0], "anders")["error"]),
                         ("failed", "interrupted_during_publication"))
        self.assertEqual(store.get(jobs[1], "anders")["state"], "completed")
        with patch("app.media_gallery_catalog.os.path.ismount", return_value=True):
            items = list_gallery(self.env["KALIV_MEDIA_ROOT"], verified_volume_root=self.env["KALIV_MEDIA_VOLUME_ROOT"])
        self.assertEqual([item["id"] for item in items["items"]], [store.get(jobs[1], "anders")["asset_id"]])

    def test_the_running_executor_logs_one_json_line_per_event_and_never_a_prompt(self):
        import contextlib
        import io
        from app.image_job_store import ImageJobStore
        with patch("app.media_gallery_catalog.os.path.ismount", return_value=True):
            ImageJobStore(self.env["KALIV_MEDIA_JOB_DB"]).submit(
                "anders", "SECRET-PROMPT-8812", profile_id="sdxl-a", params={"width": 1024, "height": 1024, "steps": 20})
            executor = build_from_env("cuda:0", self.env,
                                      adapter_factory=lambda p: FakeAdapter(p, self.env["KALIV_GPU_LEASE_DIR"]))
            real_run = executor.run
            err = io.StringIO()
            with patch("app.media_executor_main.build_from_env", return_value=executor), \
                    patch.object(executor, "run", lambda idle_sleep: real_run(max_steps=2, idle_sleep=lambda: None)), \
                    contextlib.redirect_stderr(err):
                self.assertEqual(main(["--device", "cuda:0"], self.env), 0)
        lines = [line for line in err.getvalue().splitlines() if line.startswith("kaliv-media-event ")]
        events = [json.loads(line[len("kaliv-media-event "):]) for line in lines]
        self.assertEqual({e["gpu"] for e in events}, {GPU})
        self.assertEqual([e["event"] for e in events if e["event"] in ("recovered", "job", "exit")],
                         ["recovered", "job", "exit"])
        self.assertTrue(next(e for e in events if e["event"] == "job")["detail"].endswith(":sdxl-a:completed:0.0")
                        or ":sdxl-a:completed:" in next(e for e in events if e["event"] == "job")["detail"])
        self.assertNotIn("SECRET-PROMPT-8812", err.getvalue())

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
