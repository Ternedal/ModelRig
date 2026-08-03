"""Contract and real-Windows tests for the I0b Job Object substrate.

Run everywhere: ``PYTHONPATH=worker python3 tests/worker_windows_job.py``.
The deterministic API-contract tests run on Linux CI; the native tests run only
on the dedicated Windows runner and prove the actual kernel primitive.
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "worker"))

from app.windows_job import (  # noqa: E402
    DEFAULT_UI_RESTRICTIONS,
    JOB_OBJECT_LIMIT_ACTIVE_PROCESS,
    JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE,
    JOB_OBJECT_LIMIT_PROCESS_MEMORY,
    JobLimits,
    WindowsIsolationError,
    WindowsJob,
    _extended_limits,
    close_attached_job,
    spawn_in_job,
    terminate_attached_job,
    windows_creationflags,
)

passed = failed = 0


def check(cond, msg):
    global passed, failed
    if cond:
        passed += 1
        print(f"  PASS: {msg}")
    else:
        failed += 1
        print(f"  FAIL: {msg}")


def rejects(fn, text, msg):
    try:
        fn()
    except WindowsIsolationError as exc:
        check(text in str(exc), msg)
    else:
        check(False, msg)


# --- 1. immutable policy bounds ---------------------------------------------
limits = JobLimits(process_memory_bytes=256 * 1024 * 1024, active_process_limit=4)
check(limits.ui_restrictions == DEFAULT_UI_RESTRICTIONS,
      "Tier A receives the complete UI-restriction mask by default")
rejects(lambda: JobLimits(process_memory_bytes=True), "memory", "bool is not a memory limit")
rejects(lambda: JobLimits(process_memory_bytes=32 * 1024 * 1024), "64 MiB", "too-small memory limit is rejected")
rejects(lambda: JobLimits(active_process_limit=0), "1..64", "zero-process job is rejected")
rejects(lambda: JobLimits(ui_restrictions=0x100), "mask", "unknown UI restriction bits are rejected")

native = _extended_limits(limits)
flags = native.BasicLimitInformation.LimitFlags
check(flags & JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE,
      "kill-on-close is structural, not a caller option")
check(flags & JOB_OBJECT_LIMIT_ACTIVE_PROCESS,
      "active-process limit is structural")
check(flags & JOB_OBJECT_LIMIT_PROCESS_MEMORY,
      "per-process memory limit is structural")
check(native.BasicLimitInformation.ActiveProcessLimit == 4,
      "active-process count reaches the native structure")
check(native.ProcessMemoryLimit == 256 * 1024 * 1024,
      "memory bound reaches the native structure")

# --- 2. native call ordering is fail-closed ---------------------------------
class FakeApi:
    def __init__(self, fail_at=None):
        self.calls = []
        self.fail_at = fail_at

    def _call(self, name, *args):
        self.calls.append((name, *args))
        if self.fail_at == name:
            raise WindowsIsolationError(f"forced {name} failure")

    def create_job(self):
        self._call("create")
        return 101

    def configure_job(self, handle, configured):
        self._call("configure", handle, configured)

    def assign_process(self, job, process):
        self._call("assign", job, process)

    def resume_process(self, process):
        self._call("resume", process)

    def terminate_job(self, handle, code):
        self._call("terminate", handle, code)

    def close_handle(self, handle):
        self._call("close", handle)


class FakeProc:
    def __init__(self):
        self._handle = 202
        self.killed = 0
        self.waited = 0

    def kill(self):
        self.killed += 1

    def wait(self, timeout=None):
        self.waited += 1
        return 0


api = FakeApi()
job = WindowsJob(limits, api=api)
proc = FakeProc()
job.assign_and_resume(proc)
check([call[0] for call in api.calls] == ["create", "configure", "assign", "resume"],
      "process is configured and assigned before it is resumed")
job.terminate(9)
job.close()
check([call[0] for call in api.calls][-2:] == ["terminate", "close"],
      "termination precedes handle close")
job.close()
check([call[0] for call in api.calls].count("close") == 1,
      "Job Object close is idempotent")

created = []

def fake_popen(command, **kwargs):
    created.append((command, kwargs))
    return FakeProc()

api = FakeApi()
proc = spawn_in_job(
    ["python", "child.py"],
    stdin=subprocess.PIPE,
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE,
    env={"PATH": "x"},
    limits=limits,
    popen_factory=fake_popen,
    api=api,
)
check(created[0][1]["creationflags"] & getattr(subprocess, "CREATE_SUSPENDED", 0x4),
      "child is born suspended")
check(getattr(proc, "_kaliv_windows_job", None) is not None,
      "successful spawn retains the Job Object until output is consumed")
check(terminate_attached_job(proc, 7), "attached tree can be terminated as one unit")
check(getattr(proc, "_kaliv_windows_job", None) is None,
      "terminated Job Object cannot be reused accidentally")
check(not terminate_attached_job(proc), "second termination is a harmless no-op")

api = FakeApi(fail_at="resume")
bad = FakeProc()
try:
    spawn_in_job(
        ["python", "child.py"], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, env={}, limits=limits,
        popen_factory=lambda *a, **kw: bad, api=api,
    )
    check(False, "resume failure must abort spawn")
except WindowsIsolationError:
    check(bad.killed == 1 and bad.waited == 1,
          "resume failure kills and reaps the still-suspended process")
    check("terminate" in [c[0] for c in api.calls] and "close" in [c[0] for c in api.calls],
          "resume failure also destroys the Job Object")

rejects(lambda: windows_creationflags(True), "flags", "boolean creation flags are rejected")

# --- 3. real kernel proofs on the dedicated Windows runner ------------------
if os.name != "nt":
    check(True, "native Job Object probes are reserved for the Windows CI runner")
else:
    def native_spawn(code: str, native_limits: JobLimits):
        return spawn_in_job(
            [sys.executable, "-c", code],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=os.environ.copy(),
            limits=native_limits,
        )

    # A normal child starts only after assignment and can exit cleanly.
    p = native_spawn("print('native-ok')", JobLimits())
    out, err = p.communicate(timeout=15)
    close_attached_job(p)
    check(p.returncode == 0 and out.decode().strip() == "native-ok",
          f"real suspended/assign/resume path works ({err.decode()[-120:]!r})")

    # The per-process memory limit is enforced by the kernel. Catching
    # MemoryError keeps the result deterministic instead of depending on an
    # arbitrary Windows termination code.
    code = (
        "import sys\n"
        "try:\n"
        "    x=bytearray(160*1024*1024)\n"
        "    print('memory-escaped')\n"
        "except MemoryError:\n"
        "    print('memory-denied')\n"
    )
    p = native_spawn(code, JobLimits(process_memory_bytes=96 * 1024 * 1024))
    out, _ = p.communicate(timeout=20)
    close_attached_job(p)
    check("memory-denied" in out.decode("utf-8", "replace"),
          "real Job Object enforces the process-memory ceiling")

    # With a one-process job the child cannot create a helper that escapes the
    # active-process count.
    code = (
        "import subprocess,sys\n"
        "try:\n"
        "    p=subprocess.Popen([sys.executable,'-c','print(1)'])\n"
        "    p.wait()\n"
        "    print('process-limit-escaped')\n"
        "except OSError as e:\n"
        "    print('process-limit-denied', e.winerror)\n"
    )
    p = native_spawn(code, JobLimits(active_process_limit=1))
    out, _ = p.communicate(timeout=20)
    close_attached_job(p)
    check("process-limit-denied" in out.decode("utf-8", "replace"),
          "real Job Object enforces the active-process ceiling")

    # Closing the last Job Object handle kills the child and its grandchild.
    folder = tempfile.mkdtemp(prefix="kaliv-job-close-")
    marker = os.path.join(folder, "grandchild-alive")
    grandchild_code = (
        "from pathlib import Path\n"
        f"marker=Path({marker!r})\n"
        "import time\n"
        "while True:\n"
        "    marker.touch()\n"
        "    time.sleep(0.05)\n"
    )
    child = (
        "import subprocess,sys,time\n"
        f"subprocess.Popen([sys.executable,'-c',{grandchild_code!r}])\n"
        "time.sleep(300)\n"
    )
    p = native_spawn(child, JobLimits(active_process_limit=8))
    deadline = time.time() + 15
    while not os.path.exists(marker) and time.time() < deadline:
        time.sleep(0.05)
    parent_state = p.poll()
    parent_error = ""
    if parent_state is not None and p.stderr is not None:
        parent_error = p.stderr.read().decode("utf-8", "replace")[-160:]
    check(
        os.path.exists(marker),
        f"grandchild started inside the real Job Object "
        f"(parent={parent_state}, stderr={parent_error!r})",
    )
    close_attached_job(p)
    p.wait(timeout=10)
    try:
        os.remove(marker)
    except FileNotFoundError:
        pass
    time.sleep(0.8)
    check(not os.path.exists(marker),
          "kill-on-close reaps the grandchild, not only the direct child")

print(f"\n===== WINDOWS JOB OBJECT: {passed} passed, {failed} failed =====")
raise SystemExit(1 if failed else 0)
