"""Windows Job Object enforcement for isolated ToolHost children.

This module is deliberately dormant unless ``ProcessExecutor`` is selected and
an individual tool declares ``isolate=True``.  It closes the Windows process-
tree race that existed in the portable I0a substrate: the child is created
suspended, assigned to a kill-on-close Job Object with memory/process limits,
and only then resumed.

It does *not* claim the rest of I0b.  Restricted-token launch, an OS-enforced
workspace ACL, and network denial remain separate controls and physical gates.
"""
from __future__ import annotations

import ctypes
import os
import subprocess
from dataclasses import dataclass
from typing import Any


JOB_OBJECT_LIMIT_ACTIVE_PROCESS = 0x00000008
JOB_OBJECT_LIMIT_PROCESS_MEMORY = 0x00000100
JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000

JOB_OBJECT_UILIMIT_HANDLES = 0x00000001
JOB_OBJECT_UILIMIT_READCLIPBOARD = 0x00000002
JOB_OBJECT_UILIMIT_WRITECLIPBOARD = 0x00000004
JOB_OBJECT_UILIMIT_SYSTEMPARAMETERS = 0x00000008
JOB_OBJECT_UILIMIT_DISPLAYSETTINGS = 0x00000010
JOB_OBJECT_UILIMIT_GLOBALATOMS = 0x00000020
JOB_OBJECT_UILIMIT_DESKTOP = 0x00000040
JOB_OBJECT_UILIMIT_EXITWINDOWS = 0x00000080
DEFAULT_UI_RESTRICTIONS = (
    JOB_OBJECT_UILIMIT_HANDLES
    | JOB_OBJECT_UILIMIT_READCLIPBOARD
    | JOB_OBJECT_UILIMIT_WRITECLIPBOARD
    | JOB_OBJECT_UILIMIT_SYSTEMPARAMETERS
    | JOB_OBJECT_UILIMIT_DISPLAYSETTINGS
    | JOB_OBJECT_UILIMIT_GLOBALATOMS
    | JOB_OBJECT_UILIMIT_DESKTOP
    | JOB_OBJECT_UILIMIT_EXITWINDOWS
)

JOB_OBJECT_BASIC_UI_RESTRICTIONS = 4
JOB_OBJECT_EXTENDED_LIMIT_INFORMATION = 9
MIN_PROCESS_MEMORY_BYTES = 64 * 1024 * 1024
MAX_PROCESS_MEMORY_BYTES = 64 * 1024 * 1024 * 1024


class WindowsIsolationError(RuntimeError):
    """The native Windows isolation boundary could not be established."""


@dataclass(frozen=True, slots=True)
class JobLimits:
    """Immutable limits applied before the child receives a CPU timeslice."""

    process_memory_bytes: int = 512 * 1024 * 1024
    active_process_limit: int = 8
    ui_restrictions: int = DEFAULT_UI_RESTRICTIONS

    def __post_init__(self) -> None:
        memory = self.process_memory_bytes
        processes = self.active_process_limit
        ui = self.ui_restrictions
        if (
            isinstance(memory, bool)
            or not isinstance(memory, int)
            or not MIN_PROCESS_MEMORY_BYTES <= memory <= MAX_PROCESS_MEMORY_BYTES
        ):
            raise WindowsIsolationError("process memory limit must be 64 MiB..64 GiB")
        if (
            isinstance(processes, bool)
            or not isinstance(processes, int)
            or not 1 <= processes <= 64
        ):
            raise WindowsIsolationError("active process limit must be 1..64")
        if isinstance(ui, bool) or not isinstance(ui, int) or not 0 <= ui <= 0xFF:
            raise WindowsIsolationError("UI restriction mask is invalid")


class _IO_COUNTERS(ctypes.Structure):
    _fields_ = [
        ("ReadOperationCount", ctypes.c_ulonglong),
        ("WriteOperationCount", ctypes.c_ulonglong),
        ("OtherOperationCount", ctypes.c_ulonglong),
        ("ReadTransferCount", ctypes.c_ulonglong),
        ("WriteTransferCount", ctypes.c_ulonglong),
        ("OtherTransferCount", ctypes.c_ulonglong),
    ]


class _JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("PerProcessUserTimeLimit", ctypes.c_longlong),
        ("PerJobUserTimeLimit", ctypes.c_longlong),
        ("LimitFlags", ctypes.c_uint32),
        ("MinimumWorkingSetSize", ctypes.c_size_t),
        ("MaximumWorkingSetSize", ctypes.c_size_t),
        ("ActiveProcessLimit", ctypes.c_uint32),
        ("Affinity", ctypes.c_size_t),
        ("PriorityClass", ctypes.c_uint32),
        ("SchedulingClass", ctypes.c_uint32),
    ]


class _JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("BasicLimitInformation", _JOBOBJECT_BASIC_LIMIT_INFORMATION),
        ("IoInfo", _IO_COUNTERS),
        ("ProcessMemoryLimit", ctypes.c_size_t),
        ("JobMemoryLimit", ctypes.c_size_t),
        ("PeakProcessMemoryUsed", ctypes.c_size_t),
        ("PeakJobMemoryUsed", ctypes.c_size_t),
    ]


class _JOBOBJECT_BASIC_UI_RESTRICTIONS(ctypes.Structure):
    _fields_ = [("UIRestrictionsClass", ctypes.c_uint32)]


def _extended_limits(limits: JobLimits) -> _JOBOBJECT_EXTENDED_LIMIT_INFORMATION:
    info = _JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
    info.BasicLimitInformation.LimitFlags = (
        JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        | JOB_OBJECT_LIMIT_ACTIVE_PROCESS
        | JOB_OBJECT_LIMIT_PROCESS_MEMORY
    )
    info.BasicLimitInformation.ActiveProcessLimit = limits.active_process_limit
    info.ProcessMemoryLimit = limits.process_memory_bytes
    return info


class NativeWindowsJobApi:
    """Small injectable wrapper around the Win32 calls used by the boundary."""

    def __init__(self) -> None:
        if os.name != "nt":
            raise WindowsIsolationError("Windows Job Objects are only available on Windows")
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        ntdll = ctypes.WinDLL("ntdll", use_last_error=True)

        kernel32.CreateJobObjectW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p]
        kernel32.CreateJobObjectW.restype = ctypes.c_void_p
        kernel32.SetInformationJobObject.argtypes = [
            ctypes.c_void_p,
            ctypes.c_int,
            ctypes.c_void_p,
            ctypes.c_uint32,
        ]
        kernel32.SetInformationJobObject.restype = ctypes.c_int
        kernel32.AssignProcessToJobObject.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        kernel32.AssignProcessToJobObject.restype = ctypes.c_int
        kernel32.TerminateJobObject.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
        kernel32.TerminateJobObject.restype = ctypes.c_int
        kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
        kernel32.CloseHandle.restype = ctypes.c_int
        ntdll.NtResumeProcess.argtypes = [ctypes.c_void_p]
        ntdll.NtResumeProcess.restype = ctypes.c_long

        self._kernel32 = kernel32
        self._ntdll = ntdll

    @staticmethod
    def _last_error(action: str) -> WindowsIsolationError:
        code = ctypes.get_last_error()
        return WindowsIsolationError(f"{action} failed with WinError {code}")

    def create_job(self) -> int:
        handle = self._kernel32.CreateJobObjectW(None, None)
        if not handle:
            raise self._last_error("CreateJobObjectW")
        return int(handle)

    def configure_job(self, handle: int, limits: JobLimits) -> None:
        extended = _extended_limits(limits)
        ok = self._kernel32.SetInformationJobObject(
            ctypes.c_void_p(handle),
            JOB_OBJECT_EXTENDED_LIMIT_INFORMATION,
            ctypes.byref(extended),
            ctypes.sizeof(extended),
        )
        if not ok:
            raise self._last_error("SetInformationJobObject(extended limits)")
        if limits.ui_restrictions:
            ui = _JOBOBJECT_BASIC_UI_RESTRICTIONS(limits.ui_restrictions)
            ok = self._kernel32.SetInformationJobObject(
                ctypes.c_void_p(handle),
                JOB_OBJECT_BASIC_UI_RESTRICTIONS,
                ctypes.byref(ui),
                ctypes.sizeof(ui),
            )
            if not ok:
                raise self._last_error("SetInformationJobObject(UI restrictions)")

    def assign_process(self, job_handle: int, process_handle: int) -> None:
        if not self._kernel32.AssignProcessToJobObject(
            ctypes.c_void_p(job_handle), ctypes.c_void_p(process_handle)
        ):
            raise self._last_error("AssignProcessToJobObject")

    def resume_process(self, process_handle: int) -> None:
        status = int(self._ntdll.NtResumeProcess(ctypes.c_void_p(process_handle)))
        if status != 0:
            raise WindowsIsolationError(
                f"NtResumeProcess failed with NTSTATUS 0x{status & 0xFFFFFFFF:08x}"
            )

    def terminate_job(self, handle: int, exit_code: int) -> None:
        if not self._kernel32.TerminateJobObject(
            ctypes.c_void_p(handle), ctypes.c_uint32(exit_code)
        ):
            raise self._last_error("TerminateJobObject")

    def close_handle(self, handle: int) -> None:
        if not self._kernel32.CloseHandle(ctypes.c_void_p(handle)):
            raise self._last_error("CloseHandle")


class WindowsJob:
    """Own one configured Job Object and its kill-on-close lifetime."""

    def __init__(self, limits: JobLimits, *, api: Any | None = None) -> None:
        if not isinstance(limits, JobLimits):
            raise WindowsIsolationError("WindowsJob requires validated JobLimits")
        self.limits = limits
        self._api = api or NativeWindowsJobApi()
        self._handle: int | None = None
        self._terminated = False
        handle = self._api.create_job()
        try:
            self._api.configure_job(handle, limits)
        except Exception:
            try:
                self._api.close_handle(handle)
            except Exception:
                pass
            raise
        self._handle = handle

    @property
    def closed(self) -> bool:
        return self._handle is None

    def assign_and_resume(self, process: Any) -> None:
        if self._handle is None:
            raise WindowsIsolationError("cannot assign a process to a closed Job Object")
        process_handle = getattr(process, "_handle", None)
        if isinstance(process_handle, bool) or not isinstance(process_handle, int) or process_handle <= 0:
            raise WindowsIsolationError("spawned process exposes no valid Windows handle")
        self._api.assign_process(self._handle, process_handle)
        self._api.resume_process(process_handle)

    def terminate(self, exit_code: int = 1) -> None:
        if self._handle is None or self._terminated:
            return
        if isinstance(exit_code, bool) or not isinstance(exit_code, int) or not 0 <= exit_code <= 0xFFFFFFFF:
            raise WindowsIsolationError("job termination exit code is invalid")
        self._api.terminate_job(self._handle, exit_code)
        self._terminated = True

    def close(self) -> None:
        handle = self._handle
        if handle is None:
            return
        self._handle = None
        self._api.close_handle(handle)

    def __enter__(self) -> "WindowsJob":
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.close()

    def __del__(self) -> None:  # pragma: no cover - last-resort safety net
        try:
            self.close()
        except Exception:
            pass


def windows_creationflags(base: int = 0) -> int:
    """Create a non-running child so assignment happens before first execution."""

    if isinstance(base, bool) or not isinstance(base, int) or base < 0:
        raise WindowsIsolationError("Windows creation flags are invalid")
    suspended = getattr(subprocess, "CREATE_SUSPENDED", 0x00000004)
    process_group = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200)
    return base | suspended | process_group


def spawn_in_job(
    command: list[str],
    *,
    stdin: Any,
    stdout: Any,
    stderr: Any,
    env: dict[str, str],
    limits: JobLimits,
    popen_factory: Any = subprocess.Popen,
    api: Any | None = None,
    creationflags: int = 0,
) -> subprocess.Popen:
    """Create suspended, assign limits, then resume; any failure stays closed."""

    if os.name != "nt" and api is None:
        raise WindowsIsolationError("spawn_in_job requires Windows")
    proc = popen_factory(
        command,
        stdin=stdin,
        stdout=stdout,
        stderr=stderr,
        env=env,
        creationflags=windows_creationflags(creationflags),
    )
    job: WindowsJob | None = None
    try:
        job = WindowsJob(limits, api=api)
        job.assign_and_resume(proc)
        setattr(proc, "_kaliv_windows_job", job)
        return proc
    except Exception:
        if job is not None:
            try:
                job.terminate()
            except Exception:
                pass
            try:
                job.close()
            except Exception:
                pass
        try:
            proc.kill()
        except Exception:
            pass
        try:
            proc.wait(timeout=5)
        except Exception:
            pass
        raise


def terminate_attached_job(process: Any, exit_code: int = 1) -> bool:
    job = getattr(process, "_kaliv_windows_job", None)
    if not isinstance(job, WindowsJob):
        return False
    try:
        job.terminate(exit_code)
    finally:
        job.close()
        setattr(process, "_kaliv_windows_job", None)
    return True


def close_attached_job(process: Any) -> bool:
    job = getattr(process, "_kaliv_windows_job", None)
    if not isinstance(job, WindowsJob):
        return False
    job.close()
    setattr(process, "_kaliv_windows_job", None)
    return True
