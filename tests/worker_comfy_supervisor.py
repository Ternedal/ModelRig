#!/usr/bin/env python3
"""ComfyUI supervisor: the GPU lease lives exactly as long as ComfyUI (ModelRig #2296 slice 2).

Runs a fake ComfyUI (tests/support/fake_comfyui/main.py) as a real child
process. No GPU, no ComfyUI install, loopback only.

Run: PYTHONPATH=worker python3 tests/worker_comfy_supervisor.py
"""
from __future__ import annotations

import json
import os
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "worker"))

from app.comfy_supervisor import (  # noqa: E402
    ComfyLaunch, ComfySupervisor, ComfySupervisorError, ComfyVramShortage, parse_vram_budget, port_answers,
)
import app.comfy_supervisor as supervisor_module  # noqa: E402
from app.gpu_lease import GpuBusy, acquire_gpu_lease, resident_is_held  # noqa: E402

FAKE_MAIN = ROOT / "tests" / "support" / "fake_comfyui" / "main.py"
GPU = "GPU-6a7f0c2e-1b2d-4c3e-8f9a-0123456789ab"
GIB = 1024 ** 3


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class AnyExistingDirectory:
    """Test-only stand-in for the private work area (production: media_work_area.PrivateWorkArea):
    accepts any existing directory unless told that it is no longer verified."""

    def __init__(self):
        self.lost: set[str] = set()
        self.checked: list[str] = []

    def require(self, path: str) -> None:
        from app.media_generation_contract import ArtifactSinkUnavailable
        self.checked.append(path)
        if path in self.lost or "*" in self.lost or not os.path.isdir(path):
            raise ArtifactSinkUnavailable(f"{path} is not in the verified private work area")


class FakeSupervisor(ComfySupervisor):
    """Adds the test-only FAKE_COMFY_* channel on top of the real child env."""

    def __init__(self, *, fake_env: dict[str, str], work_area=None, **kwargs):
        super().__init__(work_area=work_area or AnyExistingDirectory(), **kwargs)
        self.fake_env = fake_env

    def child_env(self) -> dict[str, str]:
        env = super().child_env()
        env.update(self.fake_env)
        return env


def wait_gone(pid: int, seconds: float) -> bool:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        try:
            with open(f"/proc/{pid}/stat") as fh:
                if fh.read().split(") ", 1)[1].startswith("Z"):
                    return True  # zombie: exited, descriptors closed
        except FileNotFoundError:
            return True
        time.sleep(0.05)
    return False


@unittest.skipIf(os.name == "nt", "POSIX descriptor-inheritance path")
class SupervisorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.lease_dir = tempfile.mkdtemp(dir=self.tmp)
        os.chmod(self.lease_dir, 0o700)
        self.state = tempfile.mkdtemp(dir=self.tmp)
        self.dirs = {}
        for name in ("input", "output", "temp", "user"):
            self.dirs[name] = os.path.join(self.tmp, name)
            os.mkdir(self.dirs[name])
        self.port = free_port()
        self.supervisors: list[ComfySupervisor] = []
        # Keep a reference to every lease the supervisor takes: otherwise
        # GpuLease.__del__ releases a leaked lease and hides the leak.
        self.taken = []
        real = supervisor_module.acquire_gpu_lease

        def recording(*args, **kwargs):
            lease = real(*args, **kwargs)
            self.taken.append(lease)
            return lease
        supervisor_module.acquire_gpu_lease = recording
        self.addCleanup(setattr, supervisor_module, "acquire_gpu_lease", real)

    def tearDown(self):
        for sup in self.supervisors:
            try:
                sup.stop()
            except ComfySupervisorError:
                pass
        pid_file = Path(self.state, "pid")
        if pid_file.exists():
            try:
                os.kill(int(pid_file.read_text()), signal.SIGKILL)
            except (ProcessLookupError, ValueError):
                pass

    def launch(self, **overrides) -> ComfyLaunch:
        values = dict(python_executable=sys.executable, main_py=str(FAKE_MAIN), port=self.port,
                      input_directory=self.dirs["input"], output_directory=self.dirs["output"],
                      temp_directory=self.dirs["temp"], user_directory=self.dirs["user"])
        values.update(overrides)
        return ComfyLaunch(**values)

    def supervisor(self, fake=None, launch=None, **kwargs) -> FakeSupervisor:
        env = {"FAKE_COMFY_STATE_DIR": self.state}
        env.update(fake or {})
        values = dict(gpu_uuid=GPU, lease_dir=self.lease_dir, launch=launch or self.launch(),
                      reserve_gib=2, min_usable_gib=8, ready_timeout_s=15, stop_timeout_s=5,
                      poll_s=0.05, base_env={"PATH": os.environ.get("PATH", ""),
                                             "KALIV_SECRET_TOKEN": "must-not-leak",
                                             "CUDA_VISIBLE_DEVICES": "0,1",
                                             "HTTPS_PROXY": "http://proxy.invalid"})
        values.update(kwargs)
        sup = FakeSupervisor(fake_env=env, **values)
        self.supervisors.append(sup)
        return sup

    def lease_is_free(self) -> bool:
        if any(lease.held for lease in self.taken if not self._owned_by_live(lease)):
            return False
        try:
            acquire_gpu_lease(GPU, lease_dir=self.lease_dir).release()
            return True
        except GpuBusy:
            return False

    def _owned_by_live(self, lease) -> bool:
        return any(sup._lease is lease for sup in self.supervisors)

    # --- happy path -----------------------------------------------------
    def test_child_temp_files_land_on_the_verified_volume_not_the_callers_temp(self):
        internal = tempfile.mkdtemp()  # stands in for C:\Users\admin\AppData\Local\Temp
        sup = self.supervisor(base_env={"PATH": os.environ.get("PATH", ""), "TEMP": internal, "TMP": internal,
                                        "TMPDIR": internal})
        sup.start()
        seen = json.loads(Path(self.state, "env.json").read_text())
        for key in ("TEMP", "TMP", "TMPDIR"):
            self.assertEqual(seen["env"][key], self.dirs["temp"], f"{key} points at ComfyUI's temp dir")
        self.assertEqual(os.path.realpath(seen["tempdir"]), os.path.realpath(self.dirs["temp"]),
                         "Python's tempfile inside ComfyUI stages on the verified volume")
        sup.stop()
        os.rmdir(internal)


    def test_start_holds_lease_and_binds_child_to_the_leased_gpu(self):
        sup = self.supervisor()
        budget = sup.start()
        self.assertEqual(budget.free_bytes, 20 * GIB)
        self.assertEqual(budget.usable_bytes, 18 * GIB)
        self.assertTrue(sup.running)
        self.assertFalse(self.lease_is_free(), "lease must be held while ComfyUI runs")
        seen = json.loads(Path(self.state, "env.json").read_text())
        env, argv = seen["env"], seen["argv"]
        self.assertEqual(env["CUDA_VISIBLE_DEVICES"], GPU, "child sees only the leased GPU")
        self.assertEqual(env["CUDA_DEVICE_ORDER"], "PCI_BUS_ID")
        for key in ("HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE"):
            self.assertEqual(env[key], "1")
        self.assertNotIn("KALIV_SECRET_TOKEN", env, "caller env must not leak into ComfyUI")
        self.assertNotIn("HTTPS_PROXY", env)
        self.assertEqual(argv[:4], ["--listen", "127.0.0.1", "--port", str(self.port)])
        self.assertIn("--disable-metadata", argv)
        self.assertIn("--disable-auto-launch", argv)
        self.assertTrue(resident_is_held(GPU, lease_dir=self.lease_dir), "ComfyUI's own process holds the resident lock")
        sup.stop()
        self.assertFalse(sup.running)
        self.assertFalse(resident_is_held(GPU, lease_dir=self.lease_dir))
        self.assertTrue(self.lease_is_free(), "lease must be free after stop")

    def test_check_budget_rereads_and_requires_running(self):
        sup = self.supervisor()
        sup.start()
        self.assertEqual(sup.check_budget().free_bytes, 20 * GIB)
        sup.stop()
        with self.assertRaises(ComfySupervisorError):
            sup.check_budget()

    # --- the core claim: lease outlives a dead supervisor ----------------
    def _run_supervisor_in_child(self, drop_pass_fds: bool, before_ready: bool = False) -> subprocess.Popen:
        ready = Path(self.state, "pid") if before_ready else Path(self.state, "supervisor_ready")
        delay = "30" if before_ready else "0"
        code = f"""
import os, subprocess, sys, time
sys.path.insert(0, {str(ROOT / 'worker')!r}); sys.path.insert(0, {str(ROOT / 'tests')!r})
if {drop_pass_fds!r}:
    real = subprocess.Popen
    def popen(*a, **k):
        k['pass_fds'] = ()
        return real(*a, **k)
    subprocess.Popen = popen
from worker_comfy_supervisor import FakeSupervisor
from app.comfy_supervisor import ComfyLaunch
launch = ComfyLaunch(python_executable=sys.executable, main_py={str(FAKE_MAIN)!r}, port={self.port},
    input_directory={self.dirs['input']!r}, output_directory={self.dirs['output']!r},
    temp_directory={self.dirs['temp']!r}, user_directory={self.dirs['user']!r})
sup = FakeSupervisor(fake_env={{'FAKE_COMFY_STATE_DIR': {self.state!r}, 'FAKE_COMFY_STARTUP_DELAY': {delay!r}}},
    gpu_uuid={GPU!r}, lease_dir={self.lease_dir!r}, launch=launch, reserve_gib=2, min_usable_gib=8,
    ready_timeout_s=60, poll_s=0.05, base_env={{'PATH': os.environ.get('PATH', '')}})
sup.start()
open({str(Path(self.state, "supervisor_ready"))!r}, 'w').close()
time.sleep(120)
"""
        child = subprocess.Popen([sys.executable, "-c", code])
        deadline = time.monotonic() + 30
        while not ready.exists():
            if child.poll() is not None or time.monotonic() > deadline:
                child.kill()
                self.fail("supervisor child did not start")
            time.sleep(0.05)
        return child

    def test_lease_outlives_a_sigkilled_supervisor_while_comfyui_runs(self):
        child = self._run_supervisor_in_child(drop_pass_fds=False)
        comfy_pid = int(Path(self.state, "pid").read_text())
        child.send_signal(signal.SIGKILL)
        child.wait(10)
        self.assertTrue(port_answers(self.port), "orphaned ComfyUI is still running")
        self.assertFalse(self.lease_is_free(), "a dead supervisor must not free a GPU ComfyUI still uses")
        # A new supervisor refuses: lease busy (checked before the port).
        with self.assertRaises(GpuBusy):
            self.supervisor().start()
        os.kill(comfy_pid, signal.SIGKILL)
        self.assertTrue(wait_gone(comfy_pid, 10))
        lease = acquire_gpu_lease(GPU, lease_dir=self.lease_dir, timeout_s=10, poll_s=0.05)
        lease.release()

    def test_without_descriptor_inheritance_the_resident_lock_alone_keeps_the_gpu(self):
        """The Windows situation: no pass_fds. The main lease is freed, the resident lock still blocks."""
        import fcntl
        child = self._run_supervisor_in_child(drop_pass_fds=True)
        comfy_pid = int(Path(self.state, "pid").read_text())
        child.send_signal(signal.SIGKILL)
        child.wait(10)
        self.assertTrue(port_answers(self.port), "orphaned ComfyUI is still running")
        main_lock = os.open(os.path.join(self.lease_dir, f"{GPU}.lock"), os.O_RDWR)
        try:
            fcntl.flock(main_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)  # control: the main lease really is free
            fcntl.flock(main_lock, fcntl.LOCK_UN)
        finally:
            os.close(main_lock)
        self.assertTrue(resident_is_held(GPU, lease_dir=self.lease_dir))
        with self.assertRaisesRegex(GpuBusy, "resident"):
            acquire_gpu_lease(GPU, lease_dir=self.lease_dir)
        os.kill(comfy_pid, signal.SIGKILL)
        self.assertTrue(wait_gone(comfy_pid, 10))
        acquire_gpu_lease(GPU, lease_dir=self.lease_dir, timeout_s=10, poll_s=0.05).release()

    # --- refusals ---------------------------------------------------------
    def test_refuses_when_port_already_answers_and_releases_lease(self):
        server = ThreadingHTTPServer(("127.0.0.1", self.port), BaseHTTPRequestHandler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            sup = self.supervisor()
            with self.assertRaisesRegex(ComfySupervisorError, "port already answers"):
                sup.start()
            self.assertFalse(Path(self.state, "pid").exists(), "no ComfyUI may be spawned")
            self.assertTrue(self.lease_is_free())
        finally:
            server.shutdown()
            server.server_close()

    def test_refuses_when_lease_is_held_elsewhere_without_spawning(self):
        other = acquire_gpu_lease(GPU, lease_dir=self.lease_dir)
        try:
            with self.assertRaises(GpuBusy):
                self.supervisor().start()
            self.assertFalse(Path(self.state, "pid").exists())
        finally:
            other.release()

    def _assert_start_fails_and_cleans_up(self, sup, pattern):
        with self.assertRaisesRegex(ComfySupervisorError, pattern):
            sup.start()
        self.assertFalse(sup.running)
        if Path(self.state, "pid").exists():
            self.assertTrue(wait_gone(int(Path(self.state, "pid").read_text()), 10), "ComfyUI must be stopped")
        self.assertTrue(self.lease_is_free(), "lease must be released after a failed start")

    def test_insufficient_vram_stops_comfyui(self):
        self._assert_start_fails_and_cleans_up(
            self.supervisor(fake={"FAKE_COMFY_VRAM_FREE_GIB": "9"}), "insufficient free VRAM")

    def test_insufficient_vram_is_the_transient_shortage_type(self):
        # G4: the executor re-queues on ComfyVramShortage; other start failures are not waits.
        from app.comfy_supervisor import ComfyVramShortage
        with self.assertRaises(ComfyVramShortage):
            self.supervisor(fake={"FAKE_COMFY_VRAM_FREE_GIB": "9"}).start()
        self.assertTrue(self.lease_is_free())
        with self.assertRaises(ComfySupervisorError) as caught:
            self.supervisor(fake={"FAKE_COMFY_DEVICES": "2"}).start()
        self.assertNotIsInstance(caught.exception, ComfyVramShortage)

    def test_two_devices_refused(self):
        self._assert_start_fails_and_cleans_up(
            self.supervisor(fake={"FAKE_COMFY_DEVICES": "2"}), "exactly one device")

    def test_cpu_device_refused(self):
        self._assert_start_fails_and_cleans_up(
            self.supervisor(fake={"FAKE_COMFY_DEVICE_TYPE": "cpu"}), "not running on CUDA")

    def test_child_exiting_during_startup(self):
        self._assert_start_fails_and_cleans_up(
            self.supervisor(fake={"FAKE_COMFY_EXIT_EARLY": "1"}), "exited during startup")

    def test_comfyui_output_goes_to_the_log_and_the_log_is_bounded(self):
        # Rig 21/11: ComfyUI's output went to DEVNULL; a start that was refused left nothing to read.
        log = Path(self.tmp, "comfyui.log")
        sup = self.supervisor(log_path=str(log))
        sup.start()
        sup.stop()
        first = log.stat().st_size
        self.assertTrue(log.is_file(), "the child's stdout and stderr have a file")
        sup = self.supervisor(log_path=str(log))
        sup.start()
        sup.stop()
        self.assertGreaterEqual(log.stat().st_size, first, "a second start appends")
        log.write_bytes(b"x" * (supervisor_module.MAX_LOG_BYTES + 1))
        sup = self.supervisor(log_path=str(log))
        sup.start()
        sup.stop()
        self.assertEqual(Path(str(log) + ".1").stat().st_size, supervisor_module.MAX_LOG_BYTES + 1, "one earlier file is kept")
        self.assertLessEqual(log.stat().st_size, supervisor_module.MAX_LOG_BYTES)
        if hasattr(os, "symlink"):
            log.unlink()
            os.symlink(Path(self.tmp, "elsewhere"), log)
            self._assert_start_fails_and_cleans_up(self.supervisor(log_path=str(log)), "symlink")

    def test_a_refused_start_names_its_reason_as_a_code(self):
        # The executor's event keeps the part before the colon (media_executor._event_code).
        from app.media_executor import _event_code
        sup = self.supervisor(fake={"FAKE_COMFY_STARTUP_DELAY": "30"}, ready_timeout_s=1)
        with self.assertRaises(ComfySupervisorError) as caught:
            sup.start()
        self.assertEqual(_event_code(caught.exception), "comfy_not_ready")
        self._forging_launcher('"pid": os.getpid()}', '"pid": os.getpid() + 1}')
        with self.assertRaises(ComfySupervisorError) as caught:
            self.supervisor().start()
        self.assertEqual(_event_code(caught.exception), "resident_proof_mismatch")

    def test_the_idle_reading_is_taken_after_a_job_and_dropped_with_the_process(self):
        COST = 832 * 480 * 33
        sup = self.supervisor()  # reserve 2 GiB, min usable 8 GiB
        sup.start()
        self.assertIsNone(sup._idle_free_bytes)
        sup.note_idle()  # no size: nothing was proven
        self.assertIsNone(sup._idle_free_bytes)
        sup.note_idle(COST)
        self.assertEqual((sup._idle_free_bytes, sup._idle_job_cost), (20 * GIB, COST), "what the fake reports free")
        Path(self.state, "vram_free_gib").write_text("5")
        sup.note_idle(COST)
        sup.check_budget(COST)  # 5 GiB free is a shortage at a start, not after a job this size succeeded at 5
        sup.check_budget(COST - 1)  # a smaller job leans on the same proof
        # a larger job, or a caller that does not say how large, gets the strict check
        for cost in (COST + 1, None, 0, -1, True, float(COST)):
            with self.subTest(cost=cost), self.assertRaisesRegex(ComfySupervisorError, "insufficient"):
                sup.check_budget(cost)
        Path(self.state, "vram_free_gib").write_text("4")
        with self.assertRaisesRegex(ComfySupervisorError, "insufficient"):
            sup.check_budget(COST)  # 1 GiB lower than its own idle reading: somebody took it
        sup.stop()
        self.assertEqual((sup._idle_free_bytes, sup._idle_job_cost), (None, 0), "a stopped ComfyUI has proven nothing")
        sup.note_idle(COST)  # not running: no reading, no error
        self.assertIsNone(sup._idle_free_bytes)

    def test_a_warm_reading_never_admits_a_job_into_the_reserve(self):
        # #2462 review (ChatGPT, P2): a baseline of 0.5 GiB must not admit the next job at 0.5 GiB.
        COST = 832 * 480 * 33
        sup = self.supervisor()  # reserve 2 GiB
        sup.start()
        for free in ("0.5", "1.9"):
            Path(self.state, "vram_free_gib").write_text(free)
            sup.note_idle(COST)
            with self.subTest(free=free), self.assertRaisesRegex(ComfySupervisorError, "insufficient"):
                sup.check_budget(COST)
        Path(self.state, "vram_free_gib").write_text("2")
        sup.note_idle(COST)
        sup.check_budget(COST)  # the reserve is free in full: the earlier job is the proof for the rest
        # competing load: the reading fell after the baseline was taken
        Path(self.state, "vram_free_gib").write_text("6")
        sup.note_idle(COST)
        Path(self.state, "vram_free_gib").write_text("5.5")
        with self.assertRaisesRegex(ComfySupervisorError, "insufficient"):
            sup.check_budget(COST)  # 0.5 GiB went to somebody else: more than the 256 MiB slack
        Path(self.state, "vram_free_gib").write_text("5.8")
        sup.check_budget(COST)  # within the slack
        sup.stop()

    def test_ready_deadline(self):
        self._assert_start_fails_and_cleans_up(
            self.supervisor(fake={"FAKE_COMFY_STARTUP_DELAY": "30"}, ready_timeout_s=1), "deadline")

    def test_stop_kills_a_child_that_ignores_sigterm(self):
        sup = self.supervisor(fake={"FAKE_COMFY_IGNORE_TERM": "1"}, stop_timeout_s=1)
        sup.start()
        pid = sup.pid
        started = time.monotonic()
        sup.stop()
        self.assertGreaterEqual(time.monotonic() - started, 0.9, "terminate was tried first")
        self.assertTrue(wait_gone(pid, 5))
        self.assertTrue(self.lease_is_free())

    def test_lease_is_kept_until_the_child_has_actually_exited(self):
        sup = self.supervisor(fake={"FAKE_COMFY_IGNORE_TERM": "1"}, stop_timeout_s=2)
        sup.start()
        stopper = threading.Thread(target=sup.stop)
        stopper.start()
        time.sleep(0.5)  # SIGTERM sent and ignored; SIGKILL not yet
        self.assertTrue(port_answers(self.port), "child still alive mid-stop")
        self.assertFalse(self.lease_is_free(), "lease must not be released while ComfyUI is alive")
        stopper.join(15)
        self.assertTrue(self.lease_is_free())

    def test_windows_path_spawns_in_a_job_object_with_limits(self):
        """Wiring only: the real Job Object is covered by windows_job contracts on the Windows runner."""
        import app.windows_job as windows_job
        spawned, closed = [], []

        def fake_spawn(command, *, stdin, stdout, stderr, env, limits, **extra):
            self.assertEqual(extra, {}, "no extra Popen options on the Windows path")
            spawned.append((command, env, limits))
            return subprocess.Popen(command, stdin=stdin, stdout=stdout, stderr=stderr, env=env)

        for target, name, value in ((supervisor_module, "_WINDOWS", True),
                                    (windows_job, "spawn_in_job", fake_spawn),
                                    (windows_job, "close_attached_job", lambda proc: closed.append(proc) or True)):
            self.addCleanup(setattr, target, name, getattr(target, name))
            setattr(target, name, value)
        sup = self.supervisor(host_memory_gib=40)
        sup.start()
        command, env, limits = spawned[0]
        self.assertEqual(env["CUDA_VISIBLE_DEVICES"], GPU)
        self.assertEqual(command[2:5:2], ["--resident-lock", "--"])
        self.assertEqual(command[6:8], ["--listen", "127.0.0.1"])
        self.assertEqual(limits.process_memory_bytes, 40 * GIB)
        self.assertEqual(limits.active_process_limit, 4)
        self.assertFalse(self.lease_is_free())
        sup.stop()
        self.assertEqual(len(closed), 1, "the job handle is closed after the child exits")
        self.assertTrue(self.lease_is_free())

    def test_comfyui_without_the_resident_lock_is_refused(self):
        """If whatever answers on the port did not take the resident lock, do not call it ready."""
        no_lock = Path(self.tmp, "no_lock_launcher.py")
        no_lock.write_text("import runpy, sys, os\n"
                           "main = sys.argv[4]; sys.argv = [main] + sys.argv[5:]\n"
                           "sys.path.insert(0, os.path.dirname(main)); runpy.run_path(main, run_name='__main__')\n")
        self.addCleanup(setattr, supervisor_module, "RESIDENT_LAUNCHER", supervisor_module.RESIDENT_LAUNCHER)
        supervisor_module.RESIDENT_LAUNCHER = no_lock
        self._assert_start_fails_and_cleans_up(self.supervisor(), "does not hold the resident lock")

    # --- identity: the LAUNCHED CHILD holds the resident lock (#2296 6496114257) ----------------
    def _forging_launcher(self, old: str, new: str) -> Path:
        source = supervisor_module.RESIDENT_LAUNCHER.read_text()
        self.assertEqual(source.count(old), 1)
        forged = Path(self.tmp, "forged_launcher.py")
        forged.write_text(source.replace(old, new))
        self.addCleanup(setattr, supervisor_module, "RESIDENT_LAUNCHER", supervisor_module.RESIDENT_LAUNCHER)
        supervisor_module.RESIDENT_LAUNCHER = forged
        return forged

    def test_a_proof_with_another_token_is_refused(self):
        self._forging_launcher('json.dump({"token": token,', 'json.dump({"token": "cd" * 16,')
        self._assert_start_fails_and_cleans_up(self.supervisor(), "not proven")

    def test_a_proof_naming_another_pid_is_refused(self):
        self._forging_launcher('"pid": os.getpid()}', '"pid": os.getpid() + 1}')
        self._assert_start_fails_and_cleans_up(self.supervisor(), "not proven")

    def test_on_windows_a_process_in_the_childs_job_proves_identity(self):
        # Rig 21/11: ComfyUI's venv python.exe is a starter; the interpreter that takes the lock is
        # its child (proof pid 1904, spawned pid 5372) and every start was refused.
        from app import windows_job

        class Api:
            ids = [5372, 1904]
            def create_job(self): return 7
            def configure_job(self, handle, limits): pass
            def close_handle(self, handle): pass
            def process_ids(self, handle): return self.ids

        class Proc:
            pid = 5372

        sup = self.supervisor()
        proc, api = Proc(), Api()
        proc._kaliv_windows_job = windows_job.WindowsJob(windows_job.JobLimits(), api=api)
        sup._proc = proc
        proof = Path(self.tmp, "proof.json")

        def proves(pid, token=None):
            proof.write_text(json.dumps({"token": token or sup._token, "pid": pid}))
            return sup._proves_identity(proof)

        was = supervisor_module._WINDOWS
        try:
            self.assertTrue(proves(5372), "the spawned pid still proves itself")
            self.assertFalse(proves(1904), "off Windows the job is never consulted")
            supervisor_module._WINDOWS = True
            self.assertEqual(sup._launched_pids(), frozenset({5372, 1904}))
            self.assertTrue(proves(1904), "a process in the launched child's job is the launched child")
            self.assertFalse(proves(4242), "a pid outside the job is refused")
            self.assertFalse(proves(1904, token="cd" * 16), "membership does not replace the token")
            api.ids = [0]
            self.assertFalse(proves(1904), "an unreadable job list falls back to the spawned pid only")
            self.assertTrue(proves(5372))
        finally:  # tearDown stops every supervisor: leave it as it was built
            supervisor_module._WINDOWS, sup._proc = was, None

    def test_a_locked_child_without_a_proof_is_refused(self):
        self._forging_launcher("    os.replace(staging, proof)\n", "    os.unlink(staging)\n")
        self._assert_start_fails_and_cleans_up(self.supervisor(), "not proven")

    def test_a_stale_proof_from_an_earlier_run_proves_nothing(self):
        sup = self.supervisor()
        sup.start()
        proof = Path(self.lease_dir, f"{GPU}.resident.lock.proof")
        stale = proof.read_text()
        sup.stop()
        self._forging_launcher("    os.replace(staging, proof)\n", "    os.unlink(staging)\n")
        proof.write_text(stale)  # left over from the run before: right shape, old token and pid
        self._assert_start_fails_and_cleans_up(self.supervisor(), "not proven")

    # --- #2296 6496114257 required fail-closed cases -------------------------------------------
    def test_supervisor_killed_after_spawn_before_readiness_keeps_the_gpu(self):
        child = self._run_supervisor_in_child(drop_pass_fds=True, before_ready=True)
        comfy_pid = int(Path(self.state, "pid").read_text())
        deadline = time.monotonic() + 10
        while not resident_is_held(GPU, lease_dir=self.lease_dir) and time.monotonic() < deadline:
            time.sleep(0.02)
        child.send_signal(signal.SIGKILL)
        child.wait(10)
        self.assertFalse(Path(self.state, "supervisor_ready").exists(), "it was killed before readiness")
        self.assertFalse(port_answers(self.port), "ComfyUI is still starting up")
        with self.assertRaisesRegex(GpuBusy, "resident"):
            acquire_gpu_lease(GPU, lease_dir=self.lease_dir)
        with self.assertRaises(GpuBusy):
            self.supervisor().start()
        os.kill(comfy_pid, signal.SIGKILL)
        self.assertTrue(wait_gone(comfy_pid, 10))
        acquire_gpu_lease(GPU, lease_dir=self.lease_dir, timeout_s=10, poll_s=0.05).release()

    def test_dropping_and_collecting_the_supervisor_does_not_free_a_running_comfyui(self):
        import gc
        sup = self.supervisor()
        sup.start()
        comfy_pid = sup.pid
        self.supervisors.remove(sup)
        self.taken.clear()
        del sup
        gc.collect()  # supervisor, Popen and its GpuLease object are gone
        with self.assertRaisesRegex(GpuBusy, "resident"):
            acquire_gpu_lease(GPU, lease_dir=self.lease_dir)
        os.kill(comfy_pid, signal.SIGKILL)
        self.assertTrue(wait_gone(comfy_pid, 10))
        acquire_gpu_lease(GPU, lease_dir=self.lease_dir, timeout_s=10, poll_s=0.05).release()

    def test_an_unrelated_resident_holder_is_refused_without_touching_its_port(self):
        import fcntl
        hits = []

        class Counting(BaseHTTPRequestHandler):
            def do_GET(self):
                hits.append(self.path)
                self.send_response(200)
                self.end_headers()

            def log_message(self, *_):
                pass

        server = ThreadingHTTPServer(("127.0.0.1", self.port), Counting)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        holder = os.open(os.path.join(self.lease_dir, f"{GPU}.resident.lock"), os.O_RDWR | os.O_CREAT, 0o600)
        try:
            fcntl.flock(holder, fcntl.LOCK_EX)
            with self.assertRaisesRegex(GpuBusy, "resident"):
                self.supervisor().start()
            self.assertEqual(hits, [], "it never attached to the unrelated process's port")
            self.assertFalse(Path(self.state, "pid").exists(), "nothing was spawned")
        finally:
            os.close(holder)
            server.shutdown()
            server.server_close()

    def test_an_unsafe_lease_directory_is_refused_before_spawning(self):
        from app.gpu_lease import GpuLeaseError
        os.chmod(self.lease_dir, 0o777)
        with self.assertRaises(GpuLeaseError):
            self.supervisor().start()
        os.chmod(self.lease_dir, 0o700)
        link = os.path.join(self.tmp, "lease-link")
        os.symlink(self.lease_dir, link)
        with self.assertRaises(GpuLeaseError):
            self.supervisor(lease_dir=link).start()
        self.assertFalse(Path(self.state, "pid").exists())

    def test_double_start_refused(self):
        sup = self.supervisor()
        sup.start()
        with self.assertRaisesRegex(ComfySupervisorError, "already started"):
            sup.start()

    # --- launch validation: refused before any lease is taken ------------
    def test_launch_validation(self):
        link = os.path.join(self.tmp, "out-link")
        os.symlink(self.dirs["output"], link)
        not_main = os.path.join(self.tmp, "server.py")
        Path(not_main).write_text("")
        cases = {
            "relative python": self.launch(python_executable="python3"),
            "not main.py": self.launch(main_py=not_main),
            "privileged port": self.launch(port=80),
            "bool port": self.launch(port=True),
            "flag not allowlisted": self.launch(flags=("--enable-cors-header",)),
            "listen smuggled as flag": self.launch(flags=("--listen",)),
            "duplicate flag": self.launch(flags=("--disable-metadata", "--disable-metadata")),
            "symlinked output dir": self.launch(output_directory=link),
            "relative input dir": self.launch(input_directory="input"),
        }
        for label, launch in cases.items():
            with self.subTest(label):
                with self.assertRaises(ComfySupervisorError):
                    launch.argv(os.path.join(self.lease_dir, "resident.lock"))
                with self.assertRaises(ComfySupervisorError):
                    self.supervisor(launch=launch).start()
                self.assertTrue(self.lease_is_free(), "validation happens before the lease")
                self.assertFalse(Path(self.state, "pid").exists())

    def test_constructor_bounds(self):
        for kwargs in ({"reserve_gib": float("nan")}, {"min_usable_gib": 0}, {"ready_timeout_s": 0},
                       {"stop_timeout_s": True}, {"poll_s": 10}, {"gpu_uuid": "cuda:0"},
                       {"host_memory_gib": 65}, {"host_memory_gib": 0.5}):
            with self.subTest(kwargs):
                with self.assertRaises((ComfySupervisorError, ValueError, RuntimeError)):
                    self.supervisor(**kwargs)


class VramParsingTests(unittest.TestCase):
    def stats(self, **device):
        base = {"type": "cuda", "name": "cuda:0 X", "vram_total": 24 * GIB, "vram_free": 20 * GIB}
        base.update(device)
        return {"devices": [base]}

    def test_ok(self):
        budget = parse_vram_budget(self.stats(), reserve_gib=2, min_usable_gib=8)
        self.assertEqual(budget.usable_bytes, 18 * GIB)

    def test_refusals(self):
        cases = {
            "not a dict": [],
            "no devices": {},
            "empty devices": {"devices": []},
            "device not dict": {"devices": ["cuda"]},
            "free above total": self.stats(vram_free=25 * GIB),
            "negative free": self.stats(vram_free=-1),
            "bool total": self.stats(vram_total=True),
            "float free": self.stats(vram_free=20.0 * GIB),
            "bool free": self.stats(vram_free=True),
            "zero total": self.stats(vram_total=0, vram_free=0),
            "mps": self.stats(type="mps"),
            "exactly at the edge minus one byte": self.stats(vram_free=10 * GIB - 1),
        }
        for label, stats in cases.items():
            with self.subTest(label):
                with self.assertRaises(ComfySupervisorError):
                    parse_vram_budget(stats, reserve_gib=2, min_usable_gib=8)
        for label in ("bool total", "bool free", "float free"):
            with self.subTest(label):
                with self.assertRaisesRegex(ComfySupervisorError, "unusable VRAM"):
                    parse_vram_budget(cases[label], reserve_gib=2, min_usable_gib=8)

    def test_a_warm_comfyui_is_measured_against_its_own_idle_reading(self):
        # Rig 21/11: idle after a clip ComfyUI reported 5.2 GiB free of 12 (its models are not in
        # torch_vram_total either), so the next job read as a shortage and ComfyUI was restarted.
        MIB = 1024 * 1024
        warm = self.stats(vram_free=5205 * MIB, vram_total=12288 * MIB, torch_vram_total=64 * MIB)
        with self.assertRaisesRegex(ComfyVramShortage, "insufficient"):
            parse_vram_budget(warm, reserve_gib=1, min_usable_gib=8)  # a start: nothing may be held
        budget = parse_vram_budget(warm, reserve_gib=1, min_usable_gib=8, idle_free_bytes=5205 * MIB)
        self.assertEqual(budget.free_bytes, 5205 * MIB, "accepted, and the figures are reported as read")
        parse_vram_budget(warm, reserve_gib=1, min_usable_gib=8, idle_free_bytes=5205 * MIB + supervisor_module.WARM_SLACK_BYTES)
        # somebody else took memory since: lower than its own idle reading by more than the slack
        with self.assertRaisesRegex(ComfyVramShortage, "insufficient"):
            parse_vram_budget(warm, reserve_gib=1, min_usable_gib=8, idle_free_bytes=5205 * MIB + supervisor_module.WARM_SLACK_BYTES + 1)
        # a baseline that is no reading at all changes nothing
        for bad in (None, 0, -1, True, 5205.0 * MIB, 12289 * MIB, "5205"):
            with self.subTest(bad=bad), self.assertRaisesRegex(ComfyVramShortage, "insufficient"):
                parse_vram_budget(warm, reserve_gib=1, min_usable_gib=8, idle_free_bytes=bad)
        # the reserve is never part of the warm path (#2462 review): equal to its baseline is not enough
        for free_mib, reserve in ((512, 1), (1023, 1), (5205, 6)):
            low = self.stats(vram_free=free_mib * MIB, vram_total=12288 * MIB)
            with self.subTest(free_mib=free_mib, reserve=reserve), self.assertRaisesRegex(ComfyVramShortage, "insufficient"):
                parse_vram_budget(low, reserve_gib=reserve, min_usable_gib=8, idle_free_bytes=free_mib * MIB)
        exactly = self.stats(vram_free=1024 * MIB, vram_total=12288 * MIB)
        parse_vram_budget(exactly, reserve_gib=1, min_usable_gib=8, idle_free_bytes=1024 * MIB)  # the reserve, in full
        self.assertEqual(supervisor_module.WARM_SLACK_BYTES, 256 * MIB)

    def test_edge_exactly_enough(self):
        self.assertEqual(parse_vram_budget(self.stats(vram_free=10 * GIB), reserve_gib=2,
                                           min_usable_gib=8).usable_bytes, 8 * GIB)


if __name__ == "__main__":
    unittest.main(verbosity=2)
