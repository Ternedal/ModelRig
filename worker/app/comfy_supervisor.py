"""One supervised ComfyUI process that holds the GPU lease for its whole life.

ModelRig #2296 slice 2 (design 6493077060), default-off. ComfyUI is a
long-running server that keeps model weights in VRAM between jobs, so the GPU
lease cannot be per job: this supervisor takes the lease for one physical GPU
UUID before ComfyUI starts and gives it up only after ComfyUI has exited.

How the lease is tied to the child's lifetime (POSIX):
  The locked lease descriptor is handed to ComfyUI with pass_fds. flock
  belongs to the open file description, so the GPU stays leased until BOTH
  processes have closed it. A supervisor that crashes or is SIGKILLed cannot
  free a GPU that an orphaned ComfyUI still occupies; the next start then fails
  closed (GpuBusy, and the port still answers) until an operator stops it.

Other rules:
- ComfyUI only sees the leased GPU: CUDA_VISIBLE_DEVICES=<GPU UUID>. CUDA
  accepts UUIDs there (NVIDIA CUDA env-var docs). Whether a pinned ComfyUI
  version leaves that variable alone when --cuda-device is omitted is a RIG
  check, not proven here.
- Loopback only, fixed argv, no shell, explicit environment, stdin closed.
- Refuses to start when the port already answers: a stray ComfyUI must not be
  silently shared.
- /system_stats is polled with a deadline. It reports the device ComfyUI uses;
  it is a sanity and VRAM-budget check, not proof that no other GPU is
  visible (that proof is CUDA_VISIBLE_DEVICES).
- Windows: descriptor inheritance does not carry an msvcrt lock, so ComfyUI
  is started through the existing windows_job.spawn_in_job (suspended, then
  assigned to a Job Object with KILL_ON_JOB_CLOSE and a host-memory limit,
  then resumed). If the supervisor dies, Windows closes the job handle and
  kills ComfyUI. Stated limit: Windows closes the lease handle and kills the
  job during the same process teardown, so another generator may take the
  lease while ComfyUI's VRAM is still being freed; its own VRAM admission is
  the second line. Rig check: not proven on the rig yet.

Nothing here imports torch, opens a non-loopback connection or downloads
anything. Nothing imports this module at worker start.
"""
from __future__ import annotations

import http.client
import json
import math
import os
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from .gpu_lease import GpuLease, acquire_gpu_lease, normalize_gpu_uuid

_WINDOWS = os.name == "nt"

LOOPBACK = "127.0.0.1"
MAX_RESPONSE_BYTES = 1024 * 1024
GIB = 1024 ** 3

# Flags the supervisor may pass. Anything else is refused, so a profile cannot
# smuggle --listen 0.0.0.0, --enable-cors-header, --enable-manager, etc.
ALLOWED_FLAGS = frozenset({
    "--disable-auto-launch",
    "--disable-metadata",
    "--disable-all-custom-nodes",
})
_DIRECTORY_FLAGS = ("--input-directory", "--output-directory", "--temp-directory", "--user-directory")

# Variables the child gets from the caller's environment; everything else is
# dropped so no CUDA_*/proxy/token variable leaks in by accident.
_PASSTHROUGH_ENV = ("PATH", "SYSTEMROOT", "HOME", "USERPROFILE", "TEMP", "TMP", "LANG", "LC_ALL")


class ComfySupervisorError(RuntimeError):
    """ComfyUI could not be started, verified or stopped safely."""


@dataclass(frozen=True)
class ComfyLaunch:
    python_executable: str
    main_py: str
    port: int
    input_directory: str
    output_directory: str
    temp_directory: str
    user_directory: str
    flags: tuple[str, ...] = ("--disable-auto-launch", "--disable-metadata")

    def argv(self) -> list[str]:
        python = Path(self.python_executable)
        main = Path(self.main_py)
        if not python.is_absolute() or not python.is_file():
            raise ComfySupervisorError("python executable must be an absolute existing file")
        if not main.is_absolute() or not main.is_file() or main.name != "main.py":
            raise ComfySupervisorError("ComfyUI main.py must be an absolute existing file")
        if type(self.port) is not int or not 1024 <= self.port <= 65535:
            raise ComfySupervisorError("port must be 1024..65535")
        if len(set(self.flags)) != len(self.flags) or not set(self.flags) <= ALLOWED_FLAGS:
            raise ComfySupervisorError("ComfyUI flags must come from the allowlist")
        argv = [str(python), str(main), "--listen", LOOPBACK, "--port", str(self.port)]
        for flag, value in zip(_DIRECTORY_FLAGS, (self.input_directory, self.output_directory,
                                                   self.temp_directory, self.user_directory)):
            directory = Path(value)
            if not directory.is_absolute() or directory.is_symlink() or not directory.is_dir():
                raise ComfySupervisorError(f"{flag} must be an existing absolute non-symlink directory")
            argv += [flag, str(directory)]
        return argv + list(self.flags)


@dataclass(frozen=True)
class VramBudget:
    device_name: str
    total_bytes: int
    free_bytes: int
    usable_bytes: int


def _get_json(port: int, path: str, timeout_s: float, *, method: str = "GET") -> object:
    connection = http.client.HTTPConnection(LOOPBACK, port, timeout=timeout_s)
    try:
        body = b"{}" if method == "POST" else None
        connection.request(method, path, body=body, headers={"Content-Type": "application/json"})
        response = connection.getresponse()
        raw = response.read(MAX_RESPONSE_BYTES + 1)
        if response.status != 200:
            raise ComfySupervisorError(f"ComfyUI {path} returned HTTP {response.status}")
        if len(raw) > MAX_RESPONSE_BYTES:
            raise ComfySupervisorError(f"ComfyUI {path} response too large")
        return json.loads(raw) if raw else {}
    finally:
        connection.close()


def port_answers(port: int, timeout_s: float = 0.5) -> bool:
    connection = http.client.HTTPConnection(LOOPBACK, port, timeout=timeout_s)
    try:
        connection.connect()
        return True
    except OSError:
        return False
    finally:
        connection.close()


def parse_vram_budget(stats: object, *, reserve_gib: float, min_usable_gib: float) -> VramBudget:
    """Fail-closed reading of /system_stats: one CUDA device with enough free VRAM."""
    devices = stats.get("devices") if isinstance(stats, dict) else None
    if not isinstance(devices, list) or len(devices) != 1 or not isinstance(devices[0], dict):
        raise ComfySupervisorError("ComfyUI must report exactly one device")
    device = devices[0]
    if device.get("type") != "cuda":
        raise ComfySupervisorError("ComfyUI is not running on CUDA")
    total, free = device.get("vram_total"), device.get("vram_free")
    if type(total) is not int or type(free) is not int or not 0 <= free <= total or total == 0:
        raise ComfySupervisorError("ComfyUI reported unusable VRAM figures")
    usable = max(0, free - int(reserve_gib * GIB))
    if usable < int(min_usable_gib * GIB):
        raise ComfySupervisorError("insufficient free VRAM after reservation")
    name = device.get("name")
    return VramBudget(name if isinstance(name, str) else "", total, free, usable)


def _bounded(value: object, low: float, high: float, name: str) -> float:
    if type(value) not in (int, float) or not math.isfinite(value) or not low <= value <= high:
        raise ComfySupervisorError(f"{name} must be a finite number in {low}..{high}")
    return float(value)


class ComfySupervisor:
    def __init__(self, *, gpu_uuid: str, lease_dir: str, launch: ComfyLaunch,
                 reserve_gib: float, min_usable_gib: float, ready_timeout_s: float = 180.0,
                 stop_timeout_s: float = 30.0, poll_s: float = 0.5, log_path: str | None = None,
                 base_env: Mapping[str, str] | None = None, host_memory_gib: float = 48.0):
        self.gpu_uuid = normalize_gpu_uuid(gpu_uuid)
        self.lease_dir = lease_dir
        self.launch = launch
        self.reserve_gib = _bounded(reserve_gib, 0, 64, "reserve_gib")
        self.min_usable_gib = _bounded(min_usable_gib, 0.5, 256, "min_usable_gib")
        self.ready_timeout_s = _bounded(ready_timeout_s, 1, 1800, "ready_timeout_s")
        self.stop_timeout_s = _bounded(stop_timeout_s, 1, 300, "stop_timeout_s")
        self.poll_s = _bounded(poll_s, 0.05, 5, "poll_s")
        self.host_memory_gib = _bounded(host_memory_gib, 1, 64, "host_memory_gib")
        self.log_path = log_path
        self.base_env = dict(os.environ if base_env is None else base_env)
        self._lease: GpuLease | None = None
        self._proc: subprocess.Popen | None = None

    @property
    def port(self) -> int:
        return self.launch.port

    @property
    def pid(self) -> int | None:
        return self._proc.pid if self._proc is not None else None

    @property
    def running(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def child_env(self) -> dict[str, str]:
        env = {key: self.base_env[key] for key in _PASSTHROUGH_ENV if key in self.base_env}
        env.update({
            "CUDA_DEVICE_ORDER": "PCI_BUS_ID",
            "CUDA_VISIBLE_DEVICES": self.gpu_uuid,
            "HF_HUB_OFFLINE": "1",
            "TRANSFORMERS_OFFLINE": "1",
            "HF_HUB_DISABLE_TELEMETRY": "1",
            "DO_NOT_TRACK": "1",
            "PYTHONNOUSERSITE": "1",
            "PYTHONUNBUFFERED": "1",
        })
        return env

    def start(self) -> VramBudget:
        if self._proc is not None:
            raise ComfySupervisorError("supervisor already started")
        argv = self.launch.argv()
        lease = acquire_gpu_lease(self.gpu_uuid, lease_dir=self.lease_dir)
        log = None
        try:
            if port_answers(self.port):
                raise ComfySupervisorError("port already answers: refusing to share a ComfyUI")
            log = open(self.log_path, "ab") if self.log_path else subprocess.DEVNULL
            proc = self._spawn(argv, self.child_env(), log, lease)
        except BaseException:
            lease.release()
            raise
        finally:
            if log not in (None, subprocess.DEVNULL):
                log.close()
        self._lease, self._proc = lease, proc
        try:
            return self._wait_ready()
        except BaseException:
            self.stop()
            raise

    def _spawn(self, argv: list[str], env: dict[str, str], log, lease: GpuLease) -> subprocess.Popen:
        if _WINDOWS:
            from .windows_job import JobLimits, spawn_in_job
            limits = JobLimits(process_memory_bytes=int(self.host_memory_gib * GIB), active_process_limit=4)
            return spawn_in_job(argv, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
                                env=env, limits=limits)
        return subprocess.Popen(
            argv, env=env, stdin=subprocess.DEVNULL, stdout=log,
            stderr=subprocess.STDOUT, close_fds=True, pass_fds=(lease.fileno(),),
        )

    def _wait_ready(self) -> VramBudget:
        deadline = time.monotonic() + self.ready_timeout_s
        while True:
            if self._proc is None or self._proc.poll() is not None:
                raise ComfySupervisorError("ComfyUI exited during startup")
            try:
                stats = _get_json(self.port, "/system_stats", timeout_s=2.0)
            except (OSError, ValueError):
                stats = None
            if stats is not None:
                return parse_vram_budget(stats, reserve_gib=self.reserve_gib,
                                         min_usable_gib=self.min_usable_gib)
            if time.monotonic() >= deadline:
                raise ComfySupervisorError("ComfyUI did not become ready before the deadline")
            time.sleep(self.poll_s)

    def check_budget(self) -> VramBudget:
        """Re-read VRAM before each job: processes outside the lease may have taken VRAM."""
        if not self.running:
            raise ComfySupervisorError("ComfyUI is not running")
        try:
            stats = _get_json(self.port, "/system_stats", timeout_s=5.0)
        except (OSError, ValueError) as exc:
            raise ComfySupervisorError("ComfyUI /system_stats unavailable") from exc
        return parse_vram_budget(stats, reserve_gib=self.reserve_gib, min_usable_gib=self.min_usable_gib)

    def stop(self) -> None:
        """Interrupt, terminate, kill. The lease is released only after ComfyUI has exited."""
        proc = self._proc
        if proc is not None and proc.poll() is None:
            try:
                _get_json(self.port, "/interrupt", timeout_s=2.0, method="POST")
            except (OSError, ValueError, ComfySupervisorError):
                pass
            proc.terminate()
            try:
                proc.wait(timeout=self.stop_timeout_s)
            except subprocess.TimeoutExpired:
                proc.kill()
                try:
                    proc.wait(timeout=self.stop_timeout_s)
                except subprocess.TimeoutExpired:
                    # Keep the lease: the GPU may still be in use.
                    raise ComfySupervisorError("ComfyUI did not exit; GPU lease kept") from None
        if proc is not None and _WINDOWS:
            from .windows_job import close_attached_job
            close_attached_job(proc)
        self._proc = None
        if self._lease is not None:
            self._lease.release()
            self._lease = None
