from __future__ import annotations

import ctypes
import os
import sys
import tempfile
import time
from pathlib import Path

from kaliv_dev_control.bounded_subprocess import run_bounded_subprocess

PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
SYNCHRONIZE = 0x00100000
STILL_ACTIVE = 259


def _pid_active(pid: int) -> bool:
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32]
    kernel32.OpenProcess.restype = ctypes.c_void_p
    kernel32.GetExitCodeProcess.argtypes = [
        ctypes.c_void_p,
        ctypes.POINTER(ctypes.c_uint32),
    ]
    kernel32.GetExitCodeProcess.restype = ctypes.c_int
    kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
    kernel32.CloseHandle.restype = ctypes.c_int

    handle = kernel32.OpenProcess(
        PROCESS_QUERY_LIMITED_INFORMATION | SYNCHRONIZE,
        0,
        pid,
    )
    if not handle:
        error = ctypes.get_last_error()
        if error == 87:  # ERROR_INVALID_PARAMETER: PID no longer exists.
            return False
        raise RuntimeError(f"OpenProcess({pid}) failed with WinError {error}")
    try:
        exit_code = ctypes.c_uint32()
        if not kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
            raise RuntimeError(
                f"GetExitCodeProcess({pid}) failed with WinError "
                f"{ctypes.get_last_error()}"
            )
        return exit_code.value == STILL_ACTIVE
    finally:
        if not kernel32.CloseHandle(handle):
            raise RuntimeError(
                f"CloseHandle({pid}) failed with WinError {ctypes.get_last_error()}"
            )


def _wait_gone(*pids: int) -> None:
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        if all(not _pid_active(pid) for pid in pids):
            return
        time.sleep(0.05)
    raise AssertionError(f"Windows process tree remained active: {pids}")


def _tree_script(*, flood: bool) -> str:
    child = (
        "import os,time,sys; "
        "open(sys.argv[1], 'w').write(str(os.getpid())); "
        "time.sleep(60)"
    )
    tail = (
        "while True:\n"
        "    sys.stdout.buffer.write(b'z' * 65536)\n"
        "    sys.stdout.buffer.flush()\n"
        if flood
        else "time.sleep(60)\n"
    )
    return f"""
import os, subprocess, sys, time
from pathlib import Path
root = Path(sys.argv[1])
(root / "parent.pid").write_text(str(os.getpid()))
subprocess.Popen([
    sys.executable,
    "-c",
    {child!r},
    str(root / "child.pid"),
])
for _ in range(400):
    if (root / "child.pid").exists():
        break
    time.sleep(0.005)
{tail}
"""


def _read_pids(root: Path) -> tuple[int, int]:
    if not (root / "parent.pid").is_file() or not (root / "child.pid").is_file():
        raise AssertionError("Windows process-tree fixture did not publish both PIDs")
    return (
        int((root / "parent.pid").read_text()),
        int((root / "child.pid").read_text()),
    )


def main() -> int:
    if os.name != "nt":
        raise RuntimeError("Windows bounded subprocess contract requires Windows")

    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory).resolve()
        result = run_bounded_subprocess(
            (sys.executable, "-c", _tree_script(flood=True), str(root)),
            cwd=root,
            env=os.environ.copy(),
            timeout_seconds=15,
            max_output_bytes=100_000,
            stdout_prefix_bytes=4096,
            stderr_prefix_bytes=4096,
        )
        parent_pid, child_pid = _read_pids(root)
        _wait_gone(parent_pid, child_pid)
        if (
            not result.output_limit_exceeded
            or result.timed_out
            or not result.process_tree_terminated
            or len(result.stdout.prefix) != 4096
        ):
            raise AssertionError("Windows output-limit evidence is inconsistent")

    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory).resolve()
        result = run_bounded_subprocess(
            (sys.executable, "-c", _tree_script(flood=False), str(root)),
            cwd=root,
            env=os.environ.copy(),
            timeout_seconds=1,
            max_output_bytes=4096,
        )
        parent_pid, child_pid = _read_pids(root)
        _wait_gone(parent_pid, child_pid)
        if (
            not result.timed_out
            or result.output_limit_exceeded
            or not result.process_tree_terminated
        ):
            raise AssertionError("Windows timeout evidence is inconsistent")

    print("Windows streaming output and Job Object tree termination: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
