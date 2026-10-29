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

from app.gpu_lease import (
    GpuBusy, GpuLeaseError, acquire_gpu_lease, device_uuid_map, lease_dir_from_env, normalize_gpu_uuid,
    parse_cuda_device,
)

CTX = multiprocessing.get_context("spawn")
GPU0 = "GPU-00000000-1111-2222-3333-444444444444"
GPU1 = "GPU-aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"


def _wait_for(path, seconds):
    deadline = time.monotonic() + seconds
    while not os.path.exists(path):
        if time.monotonic() >= deadline:
            return False
        time.sleep(0.02)
    return True


def _hold(lease_dir, gpu, flags, hold_seconds):
    # Flag files, not multiprocessing.Event: a test kills this process with
    # SIGKILL, and a process killed inside Event.wait() leaves the condition's
    # sleeper count behind, so a later Event.set() in the parent blocks forever
    # (seen as 12 hangs in 20 concurrent runs before this change).
    lease = acquire_gpu_lease(gpu, lease_dir=lease_dir)
    Path(flags, "ready").touch()
    if hold_seconds is not None:
        time.sleep(hold_seconds)
        lease.release()
        return
    _wait_for(os.path.join(flags, "release"), 60)
    lease.release()


class GpuLeaseTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = self.tmp.name

    def _child(self, gpu, hold_seconds=None):
        flags = tempfile.mkdtemp(dir=self.dir)
        child = CTX.Process(target=_hold, args=(self.dir, gpu, flags, hold_seconds))
        child.start()

        def stop():
            Path(flags, "release").touch()
            child.join(10)
            if child.is_alive():
                child.kill()
                child.join(10)

        self.addCleanup(stop)
        self.assertTrue(_wait_for(os.path.join(flags, "ready"), 60), "child did not take the lease")
        return child, flags

    def test_second_process_cannot_take_the_same_gpu(self):
        self._child(GPU1)
        with self.assertRaises(GpuBusy):
            acquire_gpu_lease(GPU1, lease_dir=self.dir)
        start = time.monotonic()
        with self.assertRaises(GpuBusy):
            acquire_gpu_lease(GPU1, lease_dir=self.dir, timeout_s=0.3, poll_s=0.05)
        self.assertGreaterEqual(time.monotonic() - start, 0.3)

    def test_different_gpus_can_be_held_at_once(self):
        self._child(GPU0)
        with acquire_gpu_lease(GPU1, lease_dir=self.dir) as lease:
            self.assertTrue(lease.held)

    def test_a_killed_holder_never_leaves_a_stale_lease(self):
        child, _release = self._child(GPU1)
        os.kill(child.pid, signal.SIGKILL)
        child.join(10)
        self.assertFalse(child.is_alive())
        with acquire_gpu_lease(GPU1, lease_dir=self.dir) as lease:
            self.assertTrue(lease.held)

    def test_waiting_acquire_succeeds_when_the_holder_releases(self):
        self._child(GPU1, hold_seconds=0.4)
        with acquire_gpu_lease(GPU1, lease_dir=self.dir, timeout_s=10, poll_s=0.05) as lease:
            self.assertTrue(lease.held)

    def test_one_process_cannot_hold_the_same_gpu_twice(self):
        first = acquire_gpu_lease(GPU0, lease_dir=self.dir)
        try:
            with self.assertRaises(GpuBusy):
                acquire_gpu_lease(GPU0.lower().replace("gpu-", "GPU-"), lease_dir=self.dir)
        finally:
            first.release()
        first.release()  # idempotent
        with acquire_gpu_lease(GPU0, lease_dir=self.dir):
            pass

    def test_the_lease_is_per_physical_gpu_not_per_spelling(self):
        with acquire_gpu_lease(GPU1, lease_dir=self.dir):
            for spelling in (GPU1.upper().replace("GPU-", "gpu-"), GPU1[len("GPU-"):], "  " + GPU1 + " "):
                with self.subTest(spelling=spelling), self.assertRaises(GpuBusy):
                    acquire_gpu_lease(spelling, lease_dir=self.dir)

    def test_invalid_gpu_identity_is_refused(self):
        for gpu in (True, 1, 1.0, None, "", "cuda:1", "GPU-1234", GPU1 + "0", GPU1.replace("a", "g"), "../" + GPU1):
            with self.subTest(gpu=gpu), self.assertRaises(GpuLeaseError):
                acquire_gpu_lease(gpu, lease_dir=self.dir)

    def test_invalid_timeouts_are_refused(self):
        for kwargs in ({"timeout_s": float("nan")}, {"timeout_s": -1}, {"timeout_s": 4000},
                       {"timeout_s": True}, {"poll_s": 0}, {"poll_s": float("inf")}):
            with self.subTest(kwargs=kwargs), self.assertRaises(GpuLeaseError):
                acquire_gpu_lease(GPU0, lease_dir=self.dir, **kwargs)

    def test_lease_directory_must_be_an_existing_absolute_real_directory(self):
        file_path = Path(self.dir) / "not-a-dir"
        file_path.write_text("x")
        link = Path(self.dir) / "link"
        target = Path(self.dir) / "real"
        target.mkdir()
        link.symlink_to(target, target_is_directory=True)
        for bad in ("relative/dir", "", str(Path(self.dir) / "missing"), str(file_path), str(link), None):
            with self.subTest(bad=bad), self.assertRaises(GpuLeaseError):
                acquire_gpu_lease(GPU0, lease_dir=bad)

    def test_a_symlinked_lease_file_is_refused(self):
        (Path(self.dir) / "elsewhere").write_text("")
        (Path(self.dir) / f"{GPU1}.lock").symlink_to(Path(self.dir) / "elsewhere")
        with self.assertRaises(GpuLeaseError):
            acquire_gpu_lease(GPU1, lease_dir=self.dir)

    def test_cuda_device_names(self):
        self.assertEqual(parse_cuda_device("cuda:0"), 0)
        self.assertEqual(parse_cuda_device("cuda:15"), 15)
        for bad in ("cuda:01", "cuda:16", "cuda:-1", "cuda:", "cpu", "CUDA:1", 1, None):
            with self.subTest(bad=bad), self.assertRaises(GpuLeaseError):
                parse_cuda_device(bad)

    def test_lease_directory_must_be_private_to_this_user(self):
        shared = Path(self.dir) / "shared"
        shared.mkdir()
        os.chmod(shared, 0o777)
        with self.assertRaises(GpuLeaseError):
            acquire_gpu_lease(GPU0, lease_dir=str(shared))
        os.chmod(shared, 0o770)
        with self.assertRaises(GpuLeaseError):
            acquire_gpu_lease(GPU0, lease_dir=str(shared))
        os.chmod(shared, 0o700)
        with acquire_gpu_lease(GPU0, lease_dir=str(shared)):
            pass

    @unittest.skipUnless(hasattr(os, "geteuid") and os.geteuid() == 0, "needs root to chown")
    def test_lease_directory_owned_by_another_user_is_refused(self):
        foreign = Path(self.dir) / "foreign"
        foreign.mkdir(mode=0o700)
        os.chown(foreign, 12345, 12345)
        with self.assertRaises(GpuLeaseError):
            acquire_gpu_lease(GPU0, lease_dir=str(foreign))

    def test_gpu_uuid_normalization(self):
        self.assertEqual(normalize_gpu_uuid("gpu-AAAAAAAA-BBBB-CCCC-DDDD-EEEEEEEEEEEE"), GPU1)
        self.assertEqual(normalize_gpu_uuid("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"), GPU1)

    def test_device_uuid_map_requires_pci_bus_order_and_a_clean_mapping(self):
        good = {"CUDA_DEVICE_ORDER": "PCI_BUS_ID", "KALIV_GPU_DEVICE_UUIDS": f"cuda:0={GPU0}, cuda:1={GPU1.lower()}"}
        self.assertEqual(device_uuid_map(good), {0: GPU0, 1: GPU1})
        bad = [
            {"KALIV_GPU_DEVICE_UUIDS": f"cuda:0={GPU0}"},
            {"CUDA_DEVICE_ORDER": "FASTEST_FIRST", "KALIV_GPU_DEVICE_UUIDS": f"cuda:0={GPU0}"},
            {"CUDA_DEVICE_ORDER": "PCI_BUS_ID"},
            {"CUDA_DEVICE_ORDER": "PCI_BUS_ID", "KALIV_GPU_DEVICE_UUIDS": f"cuda:0={GPU0},cuda:0={GPU1}"},
            {"CUDA_DEVICE_ORDER": "PCI_BUS_ID", "KALIV_GPU_DEVICE_UUIDS": f"cuda:0={GPU0},cuda:1={GPU0}"},
            {"CUDA_DEVICE_ORDER": "PCI_BUS_ID", "KALIV_GPU_DEVICE_UUIDS": f"cuda:0 {GPU0}"},
            {"CUDA_DEVICE_ORDER": "PCI_BUS_ID", "KALIV_GPU_DEVICE_UUIDS": "cuda:0=GPU-bad"},
            {"CUDA_DEVICE_ORDER": "PCI_BUS_ID", "KALIV_GPU_DEVICE_UUIDS": f"1={GPU0}"},
        ]
        for env in bad:
            with self.subTest(env=env), self.assertRaises(GpuLeaseError):
                device_uuid_map(env)

    def test_lease_dir_comes_from_the_environment_or_is_refused(self):
        self.assertEqual(lease_dir_from_env({"KALIV_GPU_LEASE_DIR": self.dir}), self.dir)
        with self.assertRaises(GpuLeaseError):
            lease_dir_from_env({})


if __name__ == "__main__":
    if sys.platform == "win32":  # the CI loop is Linux; the rig runs this too
        print("note: running the msvcrt lease path")
    unittest.main()
