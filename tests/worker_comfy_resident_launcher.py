#!/usr/bin/env python3
"""Resident lock: held by ComfyUI's own process, honoured by every GPU lease (ModelRig #2296 slice 2).

Run: PYTHONPATH=worker python3 tests/worker_comfy_resident_launcher.py
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import textwrap
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "worker"))

from app.gpu_lease import (  # noqa: E402
    GpuBusy, GpuLeaseError, acquire_gpu_lease, resident_is_held, resident_lock_path,
)

LAUNCHER = ROOT / "worker" / "app" / "comfy_resident_launcher.py"
GPU = "GPU-6a7f0c2e-1b2d-4c3e-8f9a-0123456789ab"

PROBE_MAIN = textwrap.dedent("""
    import fcntl, json, os, sys, time
    out, lock = sys.argv[1], sys.argv[2]
    fd = os.open(lock, os.O_RDWR)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        held_by_other_fd = False
    except OSError:
        held_by_other_fd = True
    json.dump({"argv": sys.argv, "path0": sys.path[0], "pid": os.getpid(), "name": __name__,
               "held": held_by_other_fd, "token_visible": "KALIV_RESIDENT_TOKEN" in os.environ,
               "proof": json.load(open(lock + ".proof"))}, open(out, "w"))
    if len(sys.argv) > 3:
        time.sleep(float(sys.argv[3]))
""")


@unittest.skipIf(os.name == "nt", "POSIX flock probe in the test script")
class LauncherTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.lease_dir = tempfile.mkdtemp(dir=self.tmp)
        os.chmod(self.lease_dir, 0o700)
        self.comfy = tempfile.mkdtemp(dir=self.tmp)
        self.main = os.path.join(self.comfy, "main.py")
        Path(self.main).write_text(PROBE_MAIN)
        self.lock = str(resident_lock_path(GPU, lease_dir=self.lease_dir))
        self.out = os.path.join(self.tmp, "out.json")

    TOKEN = "ab" * 16

    def run_launcher(self, *args, wait=True, token=TOKEN):
        cmd = [sys.executable, str(LAUNCHER), *args]
        env = {k: v for k, v in os.environ.items() if k != "KALIV_RESIDENT_TOKEN"}
        if token is not None:
            env["KALIV_RESIDENT_TOKEN"] = token
        if wait:
            return subprocess.run(cmd, capture_output=True, text=True, timeout=30, env=env)
        return subprocess.Popen(cmd, env=env)

    def test_runs_main_in_the_same_process_holding_the_lock(self):
        result = self.run_launcher("--resident-lock", self.lock, "--", self.main, self.out, self.lock)
        self.assertEqual(result.returncode, 0, result.stderr)
        seen = json.loads(Path(self.out).read_text())
        self.assertEqual(seen["argv"], [self.main, self.out, self.lock], "ComfyUI sees its own argv")
        self.assertEqual(seen["path0"], self.comfy, "ComfyUI's directory comes first on sys.path")
        self.assertEqual(seen["name"], "__main__")
        self.assertTrue(seen["held"], "the lock is held while ComfyUI's code runs")
        self.assertEqual(seen["proof"], {"token": self.TOKEN, "pid": seen["pid"]},
                         "the proof names this very process and the supervisor's token")
        self.assertFalse(seen["token_visible"], "ComfyUI's code never sees the token")
        self.assertFalse(resident_is_held(GPU, lease_dir=self.lease_dir), "released when the process exits")

    def test_the_lock_lives_exactly_as_long_as_the_process(self):
        proc = self.run_launcher("--resident-lock", self.lock, "--", self.main, self.out, self.lock, "30", wait=False)
        try:
            deadline = time.monotonic() + 15
            while not os.path.exists(self.out) and time.monotonic() < deadline:
                time.sleep(0.05)
            self.assertTrue(resident_is_held(GPU, lease_dir=self.lease_dir))
            with self.assertRaisesRegex(GpuBusy, "resident"):
                acquire_gpu_lease(GPU, lease_dir=self.lease_dir)
        finally:
            proc.kill()
            proc.wait(10)
        acquire_gpu_lease(GPU, lease_dir=self.lease_dir, timeout_s=5, poll_s=0.05).release()

    def test_refuses_to_start_when_the_lock_is_already_held(self):
        holder = self.run_launcher("--resident-lock", self.lock, "--", self.main, self.out, self.lock, "30", wait=False)
        try:
            deadline = time.monotonic() + 15
            while not os.path.exists(self.out) and time.monotonic() < deadline:
                time.sleep(0.05)
            second_out = os.path.join(self.tmp, "second.json")
            result = self.run_launcher("--resident-lock", self.lock, "--", self.main, second_out, self.lock)
            self.assertEqual(result.returncode, 75)
            self.assertFalse(os.path.exists(second_out), "ComfyUI's code never ran")
            proof = json.loads(Path(self.lock + ".proof").read_text())
            self.assertEqual(proof["pid"], holder.pid, "a launcher that did not get the lock wrote no proof")
        finally:
            holder.kill()
            holder.wait(10)

    def test_usage_errors(self):
        link = os.path.join(self.tmp, "link.lock")
        os.symlink(os.path.join(self.tmp, "target.lock"), link)
        other = os.path.join(self.comfy, "server.py")
        Path(other).write_text("raise SystemExit(9)")
        cases = {
            "no args": ((), 64),
            "missing separator": (("--resident-lock", self.lock, self.main), 64),
            "relative lock": (("--resident-lock", "r.lock", "--", self.main), 64),
            "relative main": (("--resident-lock", self.lock, "--", "main.py"), 64),
            "not main.py": (("--resident-lock", self.lock, "--", other), 64),
            "missing main": (("--resident-lock", self.lock, "--", os.path.join(self.tmp, "main.py")), 64),
            "symlinked lock": (("--resident-lock", link, "--", self.main, self.out, self.lock), 75),
        }
        for label, (args, code) in cases.items():
            with self.subTest(label):
                self.assertEqual(self.run_launcher(*args).returncode, code)
                self.assertFalse(os.path.exists(self.out))
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "target.lock")), "a symlink is never followed")

    def test_a_missing_or_malformed_token_refuses_before_locking(self):
        for token in (None, "", "xyz", "AB" * 16, "ab" * 15):
            with self.subTest(token=token):
                result = self.run_launcher("--resident-lock", self.lock, "--", self.main, self.out, self.lock,
                                           token=token)
                self.assertEqual(result.returncode, 64)
                self.assertFalse(os.path.exists(self.out))
                self.assertFalse(os.path.exists(self.lock + ".proof"))

    def test_comfyui_exit_code_passes_through(self):
        Path(self.main).write_text("raise SystemExit(3)")
        Path(self.out).unlink(missing_ok=True)
        self.assertEqual(self.run_launcher("--resident-lock", self.lock, "--", self.main).returncode, 3)


@unittest.skipIf(os.name == "nt", "POSIX")
class ResidentLeaseTests(unittest.TestCase):
    def setUp(self):
        self.lease_dir = tempfile.mkdtemp()
        os.chmod(self.lease_dir, 0o700)

    def hold_resident(self, seconds: float) -> subprocess.Popen:
        code = ("import fcntl, os, sys, time\n"
                "fd = os.open(sys.argv[1], os.O_RDWR | os.O_CREAT, 0o600)\n"
                "fcntl.flock(fd, fcntl.LOCK_EX)\n"
                "open(sys.argv[1] + '.ready', 'w').close()\n"
                "time.sleep(float(sys.argv[2]))\n")
        path = str(resident_lock_path(GPU, lease_dir=self.lease_dir))
        proc = subprocess.Popen([sys.executable, "-c", code, path, str(seconds)])
        deadline = time.monotonic() + 15
        while not os.path.exists(path + ".ready") and time.monotonic() < deadline:
            time.sleep(0.02)
        os.unlink(path + ".ready")
        return proc

    def test_a_held_resident_lock_makes_the_gpu_busy_and_leaves_the_main_lease_free(self):
        import fcntl
        proc = self.hold_resident(30)
        try:
            with self.assertRaisesRegex(GpuBusy, "resident"):
                acquire_gpu_lease(GPU, lease_dir=self.lease_dir)
            fd = os.open(os.path.join(self.lease_dir, f"{GPU}.lock"), os.O_RDWR)
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)  # the refused attempt did not keep the main lock
            finally:
                os.close(fd)
        finally:
            proc.kill()
            proc.wait(10)

    def test_a_waiting_acquire_does_not_hog_the_main_lock(self):
        """While it waits for a resident to go, a lease attempt holds the main lock only for its probes."""
        import fcntl
        import threading
        proc = self.hold_resident(1.5)
        got = []
        waiter = threading.Thread(target=lambda: got.append(
            acquire_gpu_lease(GPU, lease_dir=self.lease_dir, timeout_s=15, poll_s=0.1)))
        waiter.start()
        time.sleep(0.3)
        fd = os.open(os.path.join(self.lease_dir, f"{GPU}.lock"), os.O_RDWR)
        free_seen = False
        try:
            for _ in range(10):
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    fcntl.flock(fd, fcntl.LOCK_UN)
                    free_seen = True
                    break
                except OSError:
                    time.sleep(0.03)
        finally:
            os.close(fd)
        self.assertTrue(free_seen, "the main lock must not be held across the wait")
        waiter.join(20)
        got[0].release()
        proc.wait(10)

    def test_waits_for_the_resident_to_go_within_the_timeout(self):
        proc = self.hold_resident(0.5)
        started = time.monotonic()
        lease = acquire_gpu_lease(GPU, lease_dir=self.lease_dir, timeout_s=15, poll_s=0.05)
        self.assertGreater(time.monotonic() - started, 0.2)
        lease.release()
        proc.wait(10)

    def test_resident_lock_path_is_checked(self):
        with self.assertRaises(GpuLeaseError):
            resident_lock_path(GPU, lease_dir="relative")
        path = resident_lock_path(GPU, lease_dir=self.lease_dir)
        os.symlink(os.path.join(self.lease_dir, "elsewhere"), path)
        with self.assertRaises(GpuLeaseError):
            resident_is_held(GPU, lease_dir=self.lease_dir)
        with self.assertRaises(GpuLeaseError):
            acquire_gpu_lease(GPU, lease_dir=self.lease_dir)
        os.unlink(path)
        acquire_gpu_lease(GPU, lease_dir=self.lease_dir).release()  # the refused attempt left no lock behind


if __name__ == "__main__":
    unittest.main(verbosity=2)
