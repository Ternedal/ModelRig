#!/usr/bin/env python3
"""The operator preflight for the C:/Z: media layout (R17; ChatGPT 6689780350 P2/P3).

POSIX: real folders, modes, a real SQLite job database and real processes; a fake probe only for
the mount point, the filesystem types and a foreign device. Windows: the real SIDs and ACLs are in
tests/support/windows_media_preflight_contract.py.

Run: PYTHONPATH=worker python3 tests/worker_media_preflight.py
"""
from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
for extra in (ROOT / "worker", ROOT / "tests"):
    sys.path.insert(0, str(extra))

from app.media_preflight import current_account, preflight, process_account  # noqa: E402
from app.media_volume import MARKER_NAME  # noqa: E402
from worker_media_volume import FakeProbe  # noqa: E402

VOLUME_ID = "kaliv-preflight-01"


@unittest.skipIf(os.name == "nt", "POSIX test; Windows runs windows_media_preflight_contract.py")
class PreflightTests(unittest.TestCase):
    def setUp(self):
        self.base = os.path.realpath(tempfile.mkdtemp(prefix="kaliv-pre-"))
        self.addCleanup(shutil.rmtree, self.base, True)
        self.work = os.path.join(self.base, "work")
        os.makedirs(os.path.join(self.work, "state"))
        os.chmod(self.work, 0o700)
        self.db = os.path.join(self.work, "state", "jobs.sqlite3")
        sqlite3.connect(self.db).close()
        self.volume = os.path.join(self.base, "vol")
        os.mkdir(self.volume)
        Path(self.volume, MARKER_NAME).write_text(VOLUME_ID)
        self.vprobe = FakeProbe({self.volume})
        self.vprobe.overrides[self.volume] = {"st_dev": os.stat(self.volume).st_dev + 1}  # another disk
        fs = patch("app.media_work_area.WorkAreaProbe.containing_filesystem", return_value=("ext4", False))
        fs.start()
        self.addCleanup(fs.stop)

    def run_preflight(self, **kw):
        values = dict(work_root=self.work, job_db=self.db, volume_root=self.volume, volume_id=VOLUME_ID,
                      volume_probe=self.vprobe, min_free_gib_work=0, min_free_gib_volume=0, env={})
        values.update(kw)
        return preflight(**values)

    def results(self, report):
        return {c["check"]: c["ok"] for c in report["checks"]}

    def test_a_good_layout_passes_every_check(self):
        Path(self.db + "-wal").write_bytes(b"")
        report = self.run_preflight(pids=[os.getpid()])
        self.assertTrue(report["ok"], report)
        self.assertEqual(set(self.results(report)),
                         {"work_area", "job_db_folder_in_work_area", "private:jobs.sqlite3", "private:jobs.sqlite3-wal",
                          "publication_volume", "separate_disks", "free_space:work_area",
                          "free_space:publication_volume", f"same_account:pid {os.getpid()}"})
        self.assertEqual((report["account"], report["executor_switch"]), (str(os.geteuid()), "off"))
        self.assertIn("not a physical rig qualification", report["note"])

    def test_each_problem_is_named_and_fails_the_preflight(self):
        cases = {
            "work_area": lambda: os.chmod(self.work, 0o755),
            "publication_volume": lambda: Path(self.volume, MARKER_NAME).write_text("kaliv-other-disk-9"),
            "separate_disks": lambda: self.vprobe.overrides.clear(),
            "job_db_folder_in_work_area": lambda: None,
        }
        for name, breaks in cases.items():
            with self.subTest(check=name):
                breaks()
                kw = {"job_db": os.path.join(self.volume, "jobs.sqlite3")} if name == "job_db_folder_in_work_area" else {}
                report = self.run_preflight(**kw)
                self.assertFalse(report["ok"])
                self.assertIs(self.results(report)[name], False, report)
                # put it back
                os.chmod(self.work, 0o700)
                Path(self.volume, MARKER_NAME).write_text(VOLUME_ID)
                self.vprobe.overrides[self.volume] = {"st_dev": os.stat(self.volume).st_dev + 1}
        self.assertTrue(self.run_preflight()["ok"])

    def test_a_job_database_others_can_read_fails(self):
        # Windows judges every file's own ACL; here the POSIX mode stands in for it.
        os.chmod(os.path.join(self.work, "state"), 0o700)
        os.chmod(self.db, 0o644)
        with patch("app.media_work_area.WorkAreaProbe.acl_per_entry", new=True):
            report = self.run_preflight()
            self.assertIs(self.results(report)["private:jobs.sqlite3"], False)
            os.chmod(self.db, 0o600)
            self.assertIs(self.results(self.run_preflight())["private:jobs.sqlite3"], True)

    def test_too_little_free_space_fails(self):
        report = self.run_preflight(min_free_gib_volume=10 ** 9)
        self.assertIs(self.results(report)["free_space:publication_volume"], False)
        self.assertIs(self.results(report)["free_space:work_area"], True)

    def test_a_process_of_another_account_or_a_missing_one_fails(self):
        child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
        self.addCleanup(child.kill)
        self.assertEqual(process_account(child.pid), current_account(), "a child of ours runs as us")
        self.assertIsNone(process_account(2 ** 30), "no such process")
        report = self.run_preflight(pids=[child.pid, 2 ** 30])
        self.assertIs(self.results(report)[f"same_account:pid {child.pid}"], True)
        self.assertIs(self.results(report)[f"same_account:pid {2 ** 30}"], False)
        with patch("app.media_preflight.process_account", return_value="12345"):
            self.assertIs(self.results(self.run_preflight(pids=[child.pid]))[f"same_account:pid {child.pid}"], False)

    def test_the_switch_is_reported_never_a_secret(self):
        env = {"KALIV_MEDIA_EXECUTOR": "1", "KALIV_PAIRING_TOKEN": "secret-token-123"}
        report = self.run_preflight(env=env)
        self.assertEqual(report["executor_switch"], "on")
        self.assertNotIn("secret-token-123", json.dumps(report))

    def test_the_cli_exits_0_or_1(self):
        spec = importlib.util.spec_from_file_location("preflight_cli", ROOT / "scripts/media_work_area_preflight.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        env = {"KALIV_MEDIA_WORK_ROOT": self.work, "KALIV_MEDIA_JOB_DB": self.db,
               "KALIV_MEDIA_VOLUME_ROOT": self.volume, "KALIV_MEDIA_VOLUME_ID": VOLUME_ID}
        out = io.StringIO()
        with contextlib.redirect_stdout(out), patch("app.media_preflight.MountedMediaVolume.__init__",
                                                    side_effect=__import__("app.media_volume", fromlist=["x"])
                                                    .MediaVolumeConfigError("media_volume_is_system_volume")):
            code = module.main(["--min-free-gib-work", "0", "--min-free-gib-volume", "0"], env=env)
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(out.getvalue())["checks"][-3]["detail"], "media_volume_is_system_volume")
        with self.assertRaises(SystemExit), contextlib.redirect_stderr(io.StringIO()):
            module.main([], env={})


if __name__ == "__main__":
    unittest.main()
