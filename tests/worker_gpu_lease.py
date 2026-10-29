"""Exclusive GPU lease across real processes (ModelRig #2296, bounded GPU admission).

Uses spawned child processes, as on Windows. The Linux run exercises
fcntl.flock; the msvcrt path is exercised only on the Windows rig.
"""
import multiprocessing
import os
import signal
import sys
import tempfile
import time
import unittest
from pathlib import Path

from app.gpu_lease import GpuBusy, GpuLeaseError, acquire_gpu_lease, lease_dir_from_env, parse_cuda_device

CTX = multiprocessing.get_context("spawn")


def _hold(lease_dir, index, ready, release, hold_seconds):
    lease = acquire_gpu_lease(index, lease_dir=lease_dir)
    ready.set()
    if hold_seconds is not None:
        time.sleep(hold_seconds)
        lease.release()
        release.wait(30)
        return
    release.wait(60)
    lease.release()


class GpuLeaseTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = self.tmp.name

    def _child(self, index, hold_seconds=None):
        ready, release = CTX.Event(), CTX.Event()
        child = CTX.Process(target=_hold, args=(self.dir, index, ready, release, hold_seconds))
        child.start()
        self.addCleanup(lambda: (release.set(), child.join(10), child.kill() if child.is_alive() else None))
        self.assertTrue(ready.wait(30), "child did not take the lease")
        return child, release

    def test_second_process_cannot_take_the_same_gpu(self):
        self._child(1)
        with self.assertRaises(GpuBusy):
            acquire_gpu_lease(1, lease_dir=self.dir)
        start = time.monotonic()
        with self.assertRaises(GpuBusy):
            acquire_gpu_lease(1, lease_dir=self.dir, timeout_s=0.3, poll_s=0.05)
        self.assertGreaterEqual(time.monotonic() - start, 0.3)

    def test_different_gpus_can_be_held_at_once(self):
        self._child(0)
        with acquire_gpu_lease(1, lease_dir=self.dir) as lease:
            self.assertTrue(lease.held)

    def test_a_killed_holder_never_leaves_a_stale_lease(self):
        child, _release = self._child(1)
        os.kill(child.pid, signal.SIGKILL)
        child.join(10)
        self.assertFalse(child.is_alive())
        with acquire_gpu_lease(1, lease_dir=self.dir) as lease:
            self.assertTrue(lease.held)

    def test_waiting_acquire_succeeds_when_the_holder_releases(self):
        self._child(1, hold_seconds=0.4)
        with acquire_gpu_lease(1, lease_dir=self.dir, timeout_s=10, poll_s=0.05) as lease:
            self.assertTrue(lease.held)

    def test_one_process_cannot_hold_the_same_gpu_twice(self):
        first = acquire_gpu_lease(0, lease_dir=self.dir)
        try:
            with self.assertRaises(GpuBusy):
                acquire_gpu_lease(0, lease_dir=self.dir)
        finally:
            first.release()
        first.release()  # idempotent
        with acquire_gpu_lease(0, lease_dir=self.dir):
            pass

    def test_invalid_index_is_refused(self):
        for index in (True, False, 1.0, "1", -1, 16, None):
            with self.subTest(index=index), self.assertRaises(GpuLeaseError):
                acquire_gpu_lease(index, lease_dir=self.dir)

    def test_invalid_timeouts_are_refused(self):
        for kwargs in ({"timeout_s": float("nan")}, {"timeout_s": -1}, {"timeout_s": 4000},
                       {"timeout_s": True}, {"poll_s": 0}, {"poll_s": float("inf")}):
            with self.subTest(kwargs=kwargs), self.assertRaises(GpuLeaseError):
                acquire_gpu_lease(0, lease_dir=self.dir, **kwargs)

    def test_lease_directory_must_be_an_existing_absolute_real_directory(self):
        file_path = Path(self.dir) / "not-a-dir"
        file_path.write_text("x")
        link = Path(self.dir) / "link"
        target = Path(self.dir) / "real"
        target.mkdir()
        link.symlink_to(target, target_is_directory=True)
        for bad in ("relative/dir", "", str(Path(self.dir) / "missing"), str(file_path), str(link), None):
            with self.subTest(bad=bad), self.assertRaises(GpuLeaseError):
                acquire_gpu_lease(0, lease_dir=bad)

    def test_a_symlinked_lease_file_is_refused(self):
        (Path(self.dir) / "elsewhere").write_text("")
        (Path(self.dir) / "gpu-3.lock").symlink_to(Path(self.dir) / "elsewhere")
        with self.assertRaises(GpuLeaseError):
            acquire_gpu_lease(3, lease_dir=self.dir)

    def test_cuda_device_names(self):
        self.assertEqual(parse_cuda_device("cuda:0"), 0)
        self.assertEqual(parse_cuda_device("cuda:15"), 15)
        for bad in ("cuda:01", "cuda:16", "cuda:-1", "cuda:", "cpu", "CUDA:1", 1, None):
            with self.subTest(bad=bad), self.assertRaises(GpuLeaseError):
                parse_cuda_device(bad)

    def test_lease_dir_comes_from_the_environment_or_is_refused(self):
        self.assertEqual(lease_dir_from_env({"KALIV_GPU_LEASE_DIR": self.dir}), self.dir)
        with self.assertRaises(GpuLeaseError):
            lease_dir_from_env({})


if __name__ == "__main__":
    if sys.platform == "win32":  # the CI loop is Linux; the rig runs this too
        print("note: running the msvcrt lease path")
    unittest.main()
