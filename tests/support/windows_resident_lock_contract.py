"""Native contract: the resident lock lives exactly as long as the ComfyUI process (#2296 slice 2).

Required test (5) of #2296 6496114257: prove on real Windows (msvcrt locks,
Job Objects) what the POSIX tests prove with flock. Wired into the Windows
isolation gate:
``PYTHONPATH=worker python tests/support/windows_resident_lock_contract.py``.
It also runs on POSIX (plain Popen instead of a Job Object), so the same
assertions are exercised on every platform; the Job-Object cases are
Windows-only and say so.

No GPU, no ComfyUI: a stand-in main.py writes a marker and sleeps.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "worker"))

from app.gpu_lease import (ExecutorAlreadyRunning, GpuBusy, acquire_executor_lock, acquire_gpu_lease,  # noqa: E402
                          resident_is_held, resident_lock_path)

LAUNCHER = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "worker", "app",
                                        "comfy_resident_launcher.py"))
GPU = "GPU-6a7f0c2e-1b2d-4c3e-8f9a-0123456789ab"
TOKEN = "5e" * 16
WINDOWS = os.name == "nt"

passed = failed = 0


def check(cond, msg):
    global passed, failed
    if cond:
        passed += 1
        print(f"  PASS: {msg}")
    else:
        failed += 1
        print(f"  FAIL: {msg}")


def wait_until(predicate, seconds):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.05)
    return predicate()


def _executor_lock_free(lease_dir):
    try:
        lock = acquire_executor_lock(GPU, lease_dir=lease_dir)
    except ExecutorAlreadyRunning:
        return False
    os.close(lock._fd)
    return True


def lease_is_busy(lease_dir):
    try:
        acquire_gpu_lease(GPU, lease_dir=lease_dir).release()
        return False
    except GpuBusy:
        return True


lease_dir = tempfile.mkdtemp()
if not WINDOWS:
    os.chmod(lease_dir, 0o700)
work = tempfile.mkdtemp()
main_py = os.path.join(work, "main.py")
with open(main_py, "w", encoding="utf-8") as fh:
    fh.write("import sys, time\nopen(sys.argv[1], 'w').close()\ntime.sleep(float(sys.argv[2]))\n")
lock = str(resident_lock_path(GPU, lease_dir=lease_dir))
env = dict(os.environ, KALIV_RESIDENT_TOKEN=TOKEN)


def launcher_argv(marker, seconds):
    return [sys.executable, LAUNCHER, "--resident-lock", lock, "--", main_py, marker, str(seconds)]


def spawn(marker, seconds=60):
    argv = launcher_argv(marker, seconds)
    if WINDOWS:
        from app.windows_job import JobLimits, spawn_in_job
        return spawn_in_job(argv, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                            stderr=subprocess.PIPE, env=env, limits=JobLimits(active_process_limit=4))
    return subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                            stderr=subprocess.PIPE, env=env)


# 1. While the launched process runs, it -- and only it -- holds the resident lock.
marker = os.path.join(work, "started-1")
proc = spawn(marker)
check(wait_until(lambda: os.path.exists(marker), 30), "stand-in ComfyUI started under the launcher")
check(resident_is_held(GPU, lease_dir=lease_dir), "resident lock held while the process runs")
check(lease_is_busy(lease_dir), "acquire_gpu_lease refuses while the resident process runs")
try:
    proof = json.load(open(lock + ".proof", encoding="ascii"))
except (OSError, ValueError):
    proof = {}
check(proof == {"token": TOKEN, "pid": proc.pid}, f"proof names the launched process ({proof} vs pid {proc.pid})")

# 2. A second launcher on the same GPU refuses to start.
second = subprocess.run(launcher_argv(os.path.join(work, "started-2"), 1), env=env,
                        capture_output=True, timeout=30)
check(second.returncode == 75, f"a second launcher exits 75 (got {second.returncode})")
check(not os.path.exists(os.path.join(work, "started-2")), "the second ComfyUI never ran")

# 3. Killing the process frees the lock (on Windows: closing the Job Object kills it).
if WINDOWS:
    from app.windows_job import close_attached_job
    close_attached_job(proc)
else:
    proc.kill()
proc.wait(timeout=30)
check(wait_until(lambda: not resident_is_held(GPU, lease_dir=lease_dir), 10),
      "resident lock released once the process has gone")
check(not lease_is_busy(lease_dir), "the GPU lease is available again")

# 4. Windows only: a supervisor that dies without cleanup still takes ComfyUI (and the lock) with it,
#    because the OS closes its Job Object handle and KILL_ON_JOB_CLOSE reaps the child.
if WINDOWS:
    marker = os.path.join(work, "started-4")
    pid_file = os.path.join(work, "child.pid")
    supervisor = (
        "import os, subprocess, sys, time\n"
        f"sys.path.insert(0, {os.path.join(os.path.dirname(__file__), '..', '..', 'worker')!r})\n"
        "from app.windows_job import JobLimits, spawn_in_job\n"
        f"p = spawn_in_job({launcher_argv(marker, 60)!r}, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,\n"
        f"                 stderr=subprocess.DEVNULL, env={env!r}, limits=JobLimits(active_process_limit=4))\n"
        f"open({pid_file!r}, 'w').write(str(p.pid))\n"
        f"while not os.path.exists({marker!r}): time.sleep(0.05)\n"
        "os._exit(0)  # dies without closing the job\n"
    )
    sup = subprocess.run([sys.executable, "-c", supervisor], timeout=60, capture_output=True)
    check(sup.returncode == 0, f"helper supervisor spawned the launcher and died ({sup.stderr[-160:]!r})")
    check(wait_until(lambda: not resident_is_held(GPU, lease_dir=lease_dir), 15),
          "kill-on-close reaped the orphan: resident lock released after the supervisor died")
    check(not lease_is_busy(lease_dir), "the GPU lease is available after the orphan was reaped")
else:
    print("  SKIP: Job Object kill-on-close case is Windows-only (POSIX keeps the orphan; tested in worker_comfy_supervisor)")

# 5. The executor lock (G2, #2296): held by a live process, a second process is refused; once the
#    holder is killed, the OS releases it and the next executor gets it. Same primitive as the lease.
holder = subprocess.Popen(
    [sys.executable, "-c",
     "import sys, time\n"
     f"sys.path.insert(0, {os.path.join(os.path.dirname(__file__), '..', '..', 'worker')!r})\n"
     "from app.gpu_lease import acquire_executor_lock\n"
     f"lock = acquire_executor_lock({GPU!r}, lease_dir={lease_dir!r})\n"
     "print('HELD', flush=True)\n"
     "time.sleep(60)\n"],
    stdout=subprocess.PIPE, text=True)
try:
    check(holder.stdout.readline().strip() == "HELD", "a live executor process holds the executor lock")
    try:
        acquire_executor_lock(GPU, lease_dir=lease_dir)
        check(False, "a second executor must be refused while the first is alive")
    except ExecutorAlreadyRunning:
        check(True, "a second executor is refused while the first is alive")
    check(not lease_is_busy(lease_dir), "the executor lock is independent of the GPU lease")
finally:
    holder.kill()
    holder.wait()
    holder.stdout.close()
check(wait_until(lambda: _executor_lock_free(lease_dir), 15), "the OS released the executor lock when its holder was killed")

print(f"\n===== RESIDENT LOCK CONTRACT ({'windows' if WINDOWS else 'posix'}): {passed} passed, {failed} failed =====")
raise SystemExit(1 if failed else 0)
