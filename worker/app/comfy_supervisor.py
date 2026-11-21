"""One supervised ComfyUI process that holds the GPU lease for its whole life.

ModelRig #2296 slice 2 (design 6493077060), default-off. ComfyUI is a
long-running server that keeps model weights in VRAM between jobs, so the GPU
lease cannot be per job: this supervisor takes the lease for one physical GPU
UUID before ComfyUI starts and gives it up only after ComfyUI has exited.

How "GPU in use" is tied to ComfyUI's own lifetime (both platforms):
  ComfyUI is started through comfy_resident_launcher, which takes the GPU's
  RESIDENT lock in ComfyUI's own process before ComfyUI's code runs.
  acquire_gpu_lease() treats a held resident lock as busy, so a supervisor
  that crashes or is killed cannot hand the GPU to another generator while an
  orphaned ComfyUI still occupies it. The supervisor declares ComfyUI ready
  only once that lock is observed held.
  POSIX additionally hands the main lease descriptor to the child (pass_fds):
  flock belongs to the open file description, so the main lease too stays
  held until both processes have exited.

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
- Windows: ComfyUI is started through the existing windows_job.spawn_in_job
  (suspended, then a Job Object with KILL_ON_JOB_CLOSE and a host-memory
  limit, then resumed), so it dies with the supervisor. The resident lock
  covers the gap while it is being killed: it is released only when
  ComfyUI's own process has gone. Remaining limit: within ComfyUI's own
  process teardown, Windows may close the lock handle before the driver has
  freed the VRAM; the next generator's VRAM admission is the second line.
  Rig check: not proven on the rig yet.

Nothing here imports torch, opens a non-loopback connection or downloads
anything. Nothing imports this module at worker start.
"""
from __future__ import annotations

import contextlib
import hmac
import http.client
import json
import math
import os
import re
import secrets
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from .gpu_lease import GpuLease, acquire_gpu_lease, normalize_gpu_uuid, resident_is_held, resident_lock_path
from .media_generation_contract import MediaWorkArea

RESIDENT_LAUNCHER = Path(__file__).resolve().with_name("comfy_resident_launcher.py")

_WINDOWS = os.name == "nt"
MAX_LOG_BYTES = 8 * 1024 * 1024
WARM_SLACK_BYTES = 512 * 1024 * 1024  # how much lower than its own idle reading a warm ComfyUI may read

LOOPBACK = "127.0.0.1"
MAX_RESPONSE_BYTES = 1024 * 1024
GIB = 1024 ** 3
_PROMPT_ID = re.compile(r"[A-Za-z0-9_-]{1,128}")

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
# TEMP/TMP/TMPDIR are NOT passed through: they are pointed at ComfyUI's own temp
# directory in the private work area (child_env), so no library inside ComfyUI
# can stage frames or partial media in the caller's temp folder, which other
# users of the machine may be able to read.
_PASSTHROUGH_ENV = ("PATH", "SYSTEMROOT", "HOME", "USERPROFILE", "LANG", "LC_ALL")
_TEMP_ENV = ("TEMP", "TMP", "TMPDIR")


class ComfySupervisorError(RuntimeError):
    """ComfyUI could not be started, verified or stopped safely."""


class ComfyVramShortage(ComfySupervisorError):
    """Not enough free VRAM right now (another process holds it). Transient: the executor
    re-queues the job instead of failing it (G4, Anders 5 Nov 2026)."""


class ComfyBusy(ComfySupervisorError):
    """This ComfyUI is already running a job (single tenant: one job at a time)."""


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

    @property
    def resolved_models_directory(self) -> Path:
        """Where ComfyUI loads model files from: always <main.py dir>/models. No flag can move it
        (--base-directory and --extra-model-paths-config are not allowlisted), so the directory the
        pinned weights are verified in (G3) is the one ComfyUI reads (#2296 6636684138)."""
        return Path(self.main_py).parent / "models"

    def argv(self, resident_lock: str) -> list[str]:
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
        lock = Path(resident_lock)
        if not lock.is_absolute() or not RESIDENT_LAUNCHER.is_file():
            raise ComfySupervisorError("resident lock path and launcher must be absolute and present")
        argv = [str(python), str(RESIDENT_LAUNCHER), "--resident-lock", str(lock), "--",
                str(main), "--listen", LOOPBACK, "--port", str(self.port)]
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
    comfyui_version: str | None = None  # system.comfyui_version, compared with the profile pin (G3)


def _get_json(port: int, path: str, timeout_s: float, *, method: str = "GET",
              payload: object | None = None) -> object:
    connection = http.client.HTTPConnection(LOOPBACK, port, timeout=timeout_s)
    try:
        body = json.dumps({} if payload is None else payload).encode() if method == "POST" else None
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


def parse_vram_budget(stats: object, *, reserve_gib: float, min_usable_gib: float,
                      idle_free_bytes: int | None = None) -> VramBudget:
    """Fail-closed reading of /system_stats: one CUDA device with enough free VRAM.

    idle_free_bytes: what this same ComfyUI reported free when its last job had finished. A warm
    ComfyUI keeps its models, so its own reading is low without anybody else having taken
    anything. Rig 21/11: idle after a clip it reported 5.2 GiB free of 12 (torch_vram_total 64 MiB:
    the models are not in torch's own figure), every second job read as a shortage, and ComfyUI
    was closed and started again for every clip. If the reading is no lower than it was then
    (within WARM_SLACK_BYTES), nothing outside has taken memory since a job last ran in it, and
    that is enough. Lower than that is a shortage as before.
    """
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
        warm = type(idle_free_bytes) is int and 0 < idle_free_bytes <= total
        if not warm or free + WARM_SLACK_BYTES < idle_free_bytes:
            raise ComfyVramShortage("insufficient free VRAM after reservation")
    name = device.get("name")
    system = stats.get("system")
    version = system.get("comfyui_version") if isinstance(system, dict) else None
    return VramBudget(name if isinstance(name, str) else "", total, free, usable,
                      version if isinstance(version, str) else None)


def _bounded(value: object, low: float, high: float, name: str) -> float:
    if type(value) not in (int, float) or not math.isfinite(value) or not low <= value <= high:
        raise ComfySupervisorError(f"{name} must be a finite number in {low}..{high}")
    return float(value)


class ComfySupervisor:
    def __init__(self, *, gpu_uuid: str, lease_dir: str, launch: ComfyLaunch, work_area: MediaWorkArea,
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
        if not isinstance(work_area, MediaWorkArea):
            raise ComfySupervisorError("a verified private work area is required (no default folder)")
        self.work_area = work_area
        self._lease: GpuLease | None = None
        self._idle_free_bytes: int | None = None  # see note_idle(); cleared with every start and stop
        self._proc: subprocess.Popen | None = None
        self._token = secrets.token_hex(16)
        self._job_lock = threading.Lock()

    @property
    def port(self) -> int:
        return self.launch.port

    @property
    def pid(self) -> int | None:
        return self._proc.pid if self._proc is not None else None

    @property
    def running(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def _proves_identity(self, proof_path: Path) -> bool:
        """The launched child itself holds the resident lock: its token, its pid."""
        try:
            raw = proof_path.read_bytes()
            proof = json.loads(raw) if len(raw) <= 512 else None
        except (OSError, ValueError):
            return False
        if not isinstance(proof, dict) or set(proof) != {"token", "pid"}:
            return False
        token, pid = proof["token"], proof["pid"]
        return (isinstance(token, str) and hmac.compare_digest(token, self._token)
                and type(pid) is int and self._proc is not None and pid in self._launched_pids())

    def _launched_pids(self) -> frozenset[int]:
        """The pids that are provably the launched child: the one spawned, and on Windows every
        process in the Job Object it was started in.

        Rig 21/11: with ComfyUI's own venv, ``Scripts\\python.exe`` is a starter and the interpreter
        that takes the resident lock is its child (proof pid 1904, spawned pid 5372), so every
        start was refused. A process is in the job only by being created inside it; nothing
        outside the launched tree can be on this list."""
        pids = {self._proc.pid} if self._proc is not None else set()
        if self._proc is not None and _WINDOWS:
            from .windows_job import attached_job_process_ids
            pids |= attached_job_process_ids(self._proc)
        return frozenset(pids)

    def require_work_area(self) -> None:
        """Every ComfyUI directory must be in the verified private work area, now (Anders, 6 Nov)."""
        for directory in (self.launch.input_directory, self.launch.output_directory,
                          self.launch.temp_directory, self.launch.user_directory):
            self.work_area.require(directory)  # raises ArtifactSinkUnavailable

    @contextlib.contextmanager
    def job_slot(self):
        """One job at a time on this ComfyUI: refuse (do not queue) a second one."""
        if not self._job_lock.acquire(blocking=False):
            raise ComfyBusy("a job is already running on this ComfyUI")
        try:
            yield
        finally:
            self._job_lock.release()

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
            "KALIV_RESIDENT_TOKEN": self._token,
        })
        env.update({key: str(self.launch.temp_directory) for key in _TEMP_ENV})  # in the private work area
        return env

    def start(self) -> VramBudget:
        if self._proc is not None:
            raise ComfySupervisorError("supervisor already started")
        resident = resident_lock_path(self.gpu_uuid, lease_dir=self.lease_dir)
        argv = self.launch.argv(str(resident))
        self.require_work_area()  # before the lease: no ComfyUI outside the private work area
        self._idle_free_bytes = None
        self._token = secrets.token_hex(16)  # fresh per start
        self._proof = Path(str(resident) + ".proof")
        lease = acquire_gpu_lease(self.gpu_uuid, lease_dir=self.lease_dir)
        log = None
        try:
            if port_answers(self.port):
                raise ComfySupervisorError("comfy_port_in_use: the port already answers, refusing to share a ComfyUI")
            if self._proof.is_symlink():
                raise ComfySupervisorError("resident proof must not be a symlink")
            self._proof.unlink(missing_ok=True)  # a stale proof from an earlier run proves nothing
            log = self._open_log() if self.log_path else subprocess.DEVNULL
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

    def _open_log(self):
        """ComfyUI's stdout and stderr, appended across starts; one earlier file is kept once the
        log passes MAX_LOG_BYTES, so it cannot grow without bound. Never a link."""
        path = str(self.log_path)
        if os.path.islink(path):
            raise ComfySupervisorError("ComfyUI log must not be a symlink")
        try:
            if os.path.getsize(path) > MAX_LOG_BYTES:
                os.replace(path, path + ".1")
        except OSError:
            pass  # no log yet
        return open(path, "ab")

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
                raise ComfySupervisorError("comfy_exited_at_start: ComfyUI exited during startup")
            try:
                stats = _get_json(self.port, "/system_stats", timeout_s=2.0)
            except (OSError, ValueError):
                stats = None
            if stats is not None:
                # ComfyUI answers from inside the launcher, which took the
                # resident lock first: refuse if that cannot be observed.
                if not resident_is_held(self.gpu_uuid, lease_dir=self.lease_dir):
                    raise ComfySupervisorError("resident_lock_not_held: ComfyUI answers but does not hold the resident lock")
                if not self._proves_identity(self._proof):
                    raise ComfySupervisorError("resident_proof_mismatch: the resident lock is not proven to be held by the launched child")
                return parse_vram_budget(stats, reserve_gib=self.reserve_gib,
                                         min_usable_gib=self.min_usable_gib)
            if time.monotonic() >= deadline:
                raise ComfySupervisorError("comfy_not_ready: ComfyUI did not become ready before the deadline")
            time.sleep(self.poll_s)

    def check_budget(self) -> VramBudget:
        """Re-read VRAM before each job: processes outside the lease may have taken VRAM."""
        if not self.running:
            raise ComfySupervisorError("ComfyUI is not running")
        try:
            stats = _get_json(self.port, "/system_stats", timeout_s=5.0)
        except (OSError, ValueError) as exc:
            raise ComfySupervisorError("ComfyUI /system_stats unavailable") from exc
        return parse_vram_budget(stats, reserve_gib=self.reserve_gib, min_usable_gib=self.min_usable_gib,
                                 idle_free_bytes=self._idle_free_bytes)

    def note_idle(self) -> None:
        """Called when a job has finished: remember what this ComfyUI reports free while it keeps
        its models, for the check before the next job. Never raises; an unreadable figure leaves
        the strict check in place."""
        self._idle_free_bytes = None
        if not self.running:
            return
        try:
            stats = _get_json(self.port, "/system_stats", timeout_s=5.0)
            free = stats["devices"][0]["vram_free"]
        except (OSError, ValueError, ComfySupervisorError, KeyError, IndexError, TypeError):
            return
        if type(free) is int and free > 0:
            self._idle_free_bytes = free

    # --- the ComfyUI API the adapter needs; HTTP stays in this module -------
    def _api(self, path: str, *, method: str = "GET", payload: object | None = None,
             timeout_s: float = 10.0) -> dict:
        if not self.running:
            raise ComfySupervisorError("ComfyUI is not running")
        try:
            result = _get_json(self.port, path, timeout_s, method=method, payload=payload)
        except (OSError, ValueError) as exc:
            raise ComfySupervisorError(f"ComfyUI {path} unavailable") from exc
        if not isinstance(result, dict):
            raise ComfySupervisorError(f"ComfyUI {path} returned a non-object")
        return result

    def queue_is_empty(self) -> bool:
        """Single-tenant proof before a submit: nothing running, nothing pending."""
        queue = self._api("/queue")
        running, pending = queue.get("queue_running"), queue.get("queue_pending")
        if not isinstance(running, list) or not isinstance(pending, list):
            raise ComfySupervisorError("ComfyUI /queue is malformed")
        return not running and not pending

    def submit(self, graph: dict) -> str:
        """Submit a server-owned, bound template graph. Never forward a client graph."""
        if not isinstance(graph, dict) or not graph:
            raise ComfySupervisorError("a bound workflow graph is required")
        prompt_id = self._api("/prompt", method="POST", payload={"prompt": graph}).get("prompt_id")
        if not isinstance(prompt_id, str) or not _PROMPT_ID.fullmatch(prompt_id):
            raise ComfySupervisorError("ComfyUI returned no valid prompt id")
        return prompt_id

    def history(self, prompt_id: str) -> dict | None:
        """The finished record for prompt_id, None while it is pending."""
        if not isinstance(prompt_id, str) or not _PROMPT_ID.fullmatch(prompt_id):
            raise ComfySupervisorError("invalid prompt id")
        record = self._api(f"/history/{prompt_id}").get(prompt_id)
        return record if isinstance(record, dict) else None

    def interrupt(self) -> None:
        self._api("/interrupt", method="POST")

    def stop(self) -> None:
        """Interrupt, terminate, kill. The lease is released only after ComfyUI has exited."""
        self._idle_free_bytes = None
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
