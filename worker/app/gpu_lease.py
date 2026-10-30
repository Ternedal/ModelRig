"""Exclusive per-GPU lease across processes (ModelRig #2296, bounded GPU admission).

A VRAM snapshot alone does not bound anything: two generators that both see
enough free memory can load onto the same GPU a second later. Every generator
in this layer takes this lease for the physical GPU it will use, checks the
VRAM budget and the GPU's identity while holding it, and keeps it for as long
as its model is resident (load, inference, until close()).

The lease is keyed by the physical GPU UUID, not by a CUDA index, which can
change with CUDA_VISIBLE_DEVICES or device ordering. The operator maps CUDA
indices to UUIDs in KALIV_GPU_DEVICE_UUIDS and sets CUDA_DEVICE_ORDER=PCI_BUS_ID;
the budget check then verifies that torch's device really has that UUID.

The lease is an OS file lock (fcntl.flock on POSIX, msvcrt.locking on
Windows) on <lease dir>/<GPU UUID>.lock. The operating system releases it when
the holding process exits or is killed, so a crashed generator never leaves a
stale lease behind.

Resident lock (slice 2): a long-running server such as ComfyUI holds
<lease dir>/<GPU UUID>.resident.lock in its OWN process (comfy_resident_launcher)
for as long as it lives. acquire_gpu_lease() treats a held resident lock as
busy, so an orphaned ComfyUI blocks every cooperating generator until it has
exited, on POSIX and Windows alike. Only a process started by the holder of
the main lease takes the resident lock.

A third lock, <lease dir>/<GPU UUID>.executor.lock, marks the one media
executor process for that GPU (G2, #2296 6511335742). The executor takes it
before it recovers interrupted jobs and keeps it for its whole life, so a
second executor for the same GPU is refused before it can touch a live
executor's job. It is independent of the main lease (which is held only while
a model is resident).

Scope (decision 6491161681): the lease coordinates only processes that take
it. Ollama, a WSL2 instance or any other worker that does not use this module
is NOT covered; whole-rig GPU exclusivity is unproven and not claimed.

The lease directory must be a local, absolute, non-symlink directory owned by
this user and not group/world-writable (POSIX). On Windows, ACLs are not
checked here; that is a stated limit.
"""
from __future__ import annotations

import math
import os
import re
import stat
import time
from pathlib import Path
from typing import Mapping

LEASE_DIR_ENV = "KALIV_GPU_LEASE_DIR"
DEVICE_UUIDS_ENV = "KALIV_GPU_DEVICE_UUIDS"
DEVICE_ORDER_ENV = "CUDA_DEVICE_ORDER"
MAX_GPU_INDEX = 15
MAX_TIMEOUT_SECONDS = 3600.0
RESIDENT_SUFFIX = ".resident.lock"
EXECUTOR_SUFFIX = ".executor.lock"

_UUID = re.compile(r"GPU-[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")


class GpuLeaseError(RuntimeError):
    """The lease request itself is invalid (bad identity, directory or timeout)."""


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


def normalize_gpu_uuid(value: object) -> str:
    """'GPU-6A7F…' or '6a7f…' -> 'GPU-6a7f…'. Anything else is refused."""
    if not isinstance(value, str):
        raise GpuLeaseError("GPU UUID must be a string")
    text = value.strip().lower()
    if text.startswith("gpu-"):
        text = text[len("gpu-"):]
    candidate = "GPU-" + text
    if not _UUID.fullmatch(candidate):
        raise GpuLeaseError("GPU UUID must look like GPU-xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx")
    return candidate


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


def device_uuid_map(env: Mapping[str, str] | None = None) -> dict[int, str]:
    """KALIV_GPU_DEVICE_UUIDS='cuda:0=GPU-…,cuda:1=GPU-…' with CUDA_DEVICE_ORDER=PCI_BUS_ID."""
    env = os.environ if env is None else env
    if env.get(DEVICE_ORDER_ENV) != "PCI_BUS_ID":
        raise GpuLeaseError(f"{DEVICE_ORDER_ENV}=PCI_BUS_ID is required so CUDA indices are stable")
    raw = env.get(DEVICE_UUIDS_ENV, "").strip()
    if not raw:
        raise GpuLeaseError(f"{DEVICE_UUIDS_ENV} must map cuda:<index> to GPU UUIDs")
    mapping: dict[int, str] = {}
    for entry in raw.split(","):
        device, sep, uuid = entry.strip().partition("=")
        if not sep:
            raise GpuLeaseError(f"{DEVICE_UUIDS_ENV} entries must be cuda:<index>=GPU-<uuid>")
        index = parse_cuda_device(device.strip())
        normalized = normalize_gpu_uuid(uuid)
        if index in mapping or normalized in mapping.values():
            raise GpuLeaseError(f"{DEVICE_UUIDS_ENV} maps a device or UUID twice")
        mapping[index] = normalized
    return mapping


def lease_dir_from_env(env: Mapping[str, str] | None = None) -> str:
    env = os.environ if env is None else env
    value = env.get(LEASE_DIR_ENV, "")
    if not value:
        raise GpuLeaseError(f"{LEASE_DIR_ENV} must name a local lease directory")
    return value


def _check_lease_dir(lease_dir: object) -> Path:
    directory = Path(lease_dir) if isinstance(lease_dir, str) and lease_dir else None
    if directory is None or not directory.is_absolute() or directory.is_symlink() or not directory.is_dir():
        raise GpuLeaseError("lease directory must be an existing absolute non-symlink directory")
    if os.name != "nt":
        info = directory.stat()
        if info.st_uid != os.getuid():
            raise GpuLeaseError("lease directory must be owned by the current user")
        if info.st_mode & (stat.S_IWGRP | stat.S_IWOTH):
            raise GpuLeaseError("lease directory must not be group- or world-writable")
    return directory


class GpuLease:
    def __init__(self, gpu_uuid: str, fd: int, path: Path):
        self.gpu_uuid = gpu_uuid
        self.path = path
        self._fd: int | None = fd
        self._hold_until_exit = False

    @property
    def held(self) -> bool:
        return self._fd is not None

    def hold_until_exit(self) -> None:
        """Never release on garbage collection: only an explicit release() or process exit frees it.

        For a GPU whose memory could not be proven free (#2315 review 5697335934).
        """
        self._hold_until_exit = True

    def fileno(self) -> int:
        """The locked descriptor, for handing to a supervised child (pass_fds).

        flock belongs to the open file description, so a child that inherits
        this descriptor keeps the GPU leased until both processes have closed
        it (or exited), even if the parent dies first.
        """
        if self._fd is None:
            raise GpuLeaseError("lease already released")
        return self._fd

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
        if getattr(self, "_hold_until_exit", False):
            return  # the descriptor stays open: the OS drops the lock with the process
        try:
            self.release()
        except Exception:
            pass


def _open_lock_file(path: Path) -> int:
    if path.is_symlink():
        raise GpuLeaseError("lease file must not be a symlink")
    flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0)
    return os.open(path, flags, 0o600)


def resident_lock_path(gpu_uuid: str, *, lease_dir: str) -> Path:
    return _check_lease_dir(lease_dir) / f"{normalize_gpu_uuid(gpu_uuid)}{RESIDENT_SUFFIX}"


def _resident_held(path: Path) -> bool:
    fd = _open_lock_file(path)
    try:
        try:
            _try_lock(fd)
        except OSError:
            return True
        _unlock(fd)
        return False
    finally:
        os.close(fd)


class ExecutorAlreadyRunning(RuntimeError):
    """Another live process holds this GPU's executor lock."""


class ExecutorLock:
    """Held for the life of the executor process; the OS releases it when the process ends."""

    def __init__(self, gpu_uuid: str, fd: int, path: Path):
        self.gpu_uuid, self._fd, self.path = gpu_uuid, fd, path

    def __del__(self) -> None:  # deliberately never released before process exit
        pass


def acquire_executor_lock(gpu_uuid: str, *, lease_dir: str) -> ExecutorLock:
    """Take <lease dir>/<GPU UUID>.executor.lock without waiting, or raise ExecutorAlreadyRunning."""
    normalized = normalize_gpu_uuid(gpu_uuid)
    path = _check_lease_dir(lease_dir) / f"{normalized}{EXECUTOR_SUFFIX}"
    fd = _open_lock_file(path)
    try:
        _try_lock(fd)
    except OSError:
        os.close(fd)
        raise ExecutorAlreadyRunning(f"an executor for {normalized} is already running") from None
    return ExecutorLock(normalized, fd, path)


def resident_is_held(gpu_uuid: str, *, lease_dir: str) -> bool:
    """True while a resident server (e.g. ComfyUI) still holds this GPU's resident lock."""
    return _resident_held(resident_lock_path(gpu_uuid, lease_dir=lease_dir))


def acquire_gpu_lease(gpu_uuid: str, *, lease_dir: str, timeout_s: float = 0.0,
                      poll_s: float = 0.25) -> GpuLease:
    """Take the exclusive lease for one physical GPU, waiting at most timeout_s seconds."""
    normalized = normalize_gpu_uuid(gpu_uuid)
    if (type(timeout_s) not in (int, float) or not math.isfinite(timeout_s)
            or not 0 <= timeout_s <= MAX_TIMEOUT_SECONDS):
        raise GpuLeaseError("timeout must be a finite number of seconds in 0..3600")
    if type(poll_s) not in (int, float) or not math.isfinite(poll_s) or not 0.01 <= poll_s <= 5:
        raise GpuLeaseError("poll interval must be 0.01..5 seconds")
    directory = _check_lease_dir(lease_dir)
    path = directory / f"{normalized}.lock"
    resident = directory / f"{normalized}{RESIDENT_SUFFIX}"
    fd = _open_lock_file(path)
    deadline = time.monotonic() + timeout_s
    while True:
        reason = "is leased by another process"
        try:
            _try_lock(fd)
        except OSError:
            pass
        else:
            try:
                held = _resident_held(resident)
            except BaseException:
                _unlock(fd)
                os.close(fd)
                raise
            if not held:
                return GpuLease(normalized, fd, path)
            _unlock(fd)  # a resident server (an orphaned ComfyUI?) still occupies the GPU
            reason = "is still held by a resident process"
        if time.monotonic() >= deadline:
            os.close(fd)
            raise GpuBusy(f"{normalized} {reason}") from None
        time.sleep(poll_s)
