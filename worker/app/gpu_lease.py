"""Exclusive per-GPU lease across processes (ModelRig #2296, bounded GPU admission).

A VRAM snapshot alone does not bound anything: two generators that both see
enough free memory can load onto the same GPU a second later. Every generator
(image executor, Wan/ComfyUI dispatch, later others) takes this lease for the
GPU it will use, then checks the VRAM budget while holding it, and keeps it
until its model is unloaded.

The lease is an OS file lock (fcntl.flock on POSIX, msvcrt.locking on
Windows) on <lease dir>/gpu-<index>.lock. The operating system releases it when
the holding process exits or is killed, so a crashed generator never leaves a
stale lease behind. The lease directory should be local (not the external
media volume), so a lease still works while that volume is missing.
"""
from __future__ import annotations

import math
import os
import time
from pathlib import Path
from typing import Mapping

LEASE_DIR_ENV = "KALIV_GPU_LEASE_DIR"
MAX_GPU_INDEX = 15
MAX_TIMEOUT_SECONDS = 3600.0


class GpuLeaseError(RuntimeError):
    """The lease request itself is invalid (bad index, directory or timeout)."""


class GpuBusy(RuntimeError):
    """Another process holds the lease for this GPU."""


def _try_lock(fd: int) -> None:
    if os.name == "nt":  # pragma: no cover - exercised on the Windows rig, not in Linux CI
        import msvcrt
        os.lseek(fd, 0, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
    else:
        import fcntl
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)


def _unlock(fd: int) -> None:
    if os.name == "nt":  # pragma: no cover
        import msvcrt
        os.lseek(fd, 0, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
    else:
        import fcntl
        fcntl.flock(fd, fcntl.LOCK_UN)


def parse_cuda_device(device: str) -> int:
    """'cuda:1' -> 1. Anything else is refused."""
    if not isinstance(device, str) or not device.startswith("cuda:"):
        raise GpuLeaseError("device must be cuda:<index>")
    digits = device[len("cuda:"):]
    if not digits.isdigit() or (len(digits) > 1 and digits.startswith("0")):
        raise GpuLeaseError("device must be cuda:<index>")
    index = int(digits)
    if index > MAX_GPU_INDEX:
        raise GpuLeaseError("GPU index out of range")
    return index


def lease_dir_from_env(env: Mapping[str, str] | None = None) -> str:
    env = os.environ if env is None else env
    value = env.get(LEASE_DIR_ENV, "")
    if not value:
        raise GpuLeaseError(f"{LEASE_DIR_ENV} must name a local lease directory")
    return value


class GpuLease:
    def __init__(self, index: int, fd: int, path: Path):
        self.index = index
        self.path = path
        self._fd: int | None = fd

    @property
    def held(self) -> bool:
        return self._fd is not None

    def release(self) -> None:
        fd, self._fd = self._fd, None
        if fd is None:
            return
        try:
            _unlock(fd)
        finally:
            os.close(fd)

    def __enter__(self) -> "GpuLease":
        return self

    def __exit__(self, *_exc) -> None:
        self.release()

    def __del__(self) -> None:  # best effort; the OS releases on exit anyway
        try:
            self.release()
        except Exception:
            pass


def acquire_gpu_lease(index: int, *, lease_dir: str, timeout_s: float = 0.0,
                      poll_s: float = 0.25) -> GpuLease:
    """Take the exclusive lease for one GPU, waiting at most timeout_s seconds."""
    if type(index) is not int or not 0 <= index <= MAX_GPU_INDEX:
        raise GpuLeaseError("GPU index must be an integer in 0..15")
    if (type(timeout_s) not in (int, float) or not math.isfinite(timeout_s)
            or not 0 <= timeout_s <= MAX_TIMEOUT_SECONDS):
        raise GpuLeaseError("timeout must be a finite number of seconds in 0..3600")
    if type(poll_s) not in (int, float) or not math.isfinite(poll_s) or not 0.01 <= poll_s <= 5:
        raise GpuLeaseError("poll interval must be 0.01..5 seconds")
    directory = Path(lease_dir) if isinstance(lease_dir, str) and lease_dir else None
    if directory is None or not directory.is_absolute() or directory.is_symlink() or not directory.is_dir():
        raise GpuLeaseError("lease directory must be an existing absolute non-symlink directory")
    path = directory / f"gpu-{index}.lock"
    if path.is_symlink():
        raise GpuLeaseError("lease file must not be a symlink")

    flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0)
    fd = os.open(path, flags, 0o600)
    deadline = time.monotonic() + timeout_s
    while True:
        try:
            _try_lock(fd)
            return GpuLease(index, fd, path)
        except OSError:
            if time.monotonic() >= deadline:
                os.close(fd)
                raise GpuBusy(f"GPU {index} is leased by another process") from None
            time.sleep(poll_s)
