"""Bounded stdout/stderr capture for the dormant Tier-A Windows launcher.

This module does not create processes. It wraps the already-authoritative
AppContainer Win32 API narrowly enough to supply three inherited standard
handles to the existing ``CreateProcessW`` call. Executable selection,
arguments, environment construction, AppContainer identity and Job Object
assignment remain owned by the existing launch substrate.

Both output pipes are drained concurrently until EOF so a child cannot block on
a full pipe. Every byte contributes to the stream hash and total byte count,
while only a deterministic prefix budget is retained in memory. The total
retained bytes can therefore never exceed the signed task output budget.
"""
from __future__ import annotations

import ctypes
import hashlib
import threading
from dataclasses import dataclass
from typing import Any

from .windows_job import WindowsIsolationError
from .windows_restricted import _STARTUPINFOW

ERROR_BROKEN_PIPE = 109
ERROR_INVALID_HANDLE = 6
HANDLE_FLAG_INHERIT = 0x00000001
STARTF_USESTDHANDLES = 0x00000100
GENERIC_READ = 0x80000000
FILE_SHARE_READ = 0x00000001
FILE_SHARE_WRITE = 0x00000002
OPEN_EXISTING = 3
FILE_ATTRIBUTE_NORMAL = 0x00000080
INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value
_READ_CHUNK_BYTES = 64 * 1024
_MAX_CAPTURE_BYTES = 100_000_000


class WindowsOutputCaptureError(WindowsIsolationError):
    """Native output handles could not be created, drained or closed safely."""


class _SECURITY_ATTRIBUTES(ctypes.Structure):
    _fields_ = [
        ("nLength", ctypes.c_uint32),
        ("lpSecurityDescriptor", ctypes.c_void_p),
        ("bInheritHandle", ctypes.c_int),
    ]


@dataclass(frozen=True, slots=True)
class CapturedStream:
    """One completely hashed stream with a bounded retained prefix."""

    captured: bytes
    sha256: str
    total_bytes: int
    truncated: bool

    def __post_init__(self) -> None:
        if not isinstance(self.captured, bytes):
            raise WindowsOutputCaptureError("captured stream prefix must be bytes")
        if (
            not isinstance(self.sha256, str)
            or len(self.sha256) != 64
            or any(character not in "0123456789abcdef" for character in self.sha256)
        ):
            raise WindowsOutputCaptureError("captured stream hash is invalid")
        if (
            isinstance(self.total_bytes, bool)
            or not isinstance(self.total_bytes, int)
            or self.total_bytes < len(self.captured)
        ):
            raise WindowsOutputCaptureError("captured stream byte count is invalid")
        if not isinstance(self.truncated, bool):
            raise WindowsOutputCaptureError("captured stream truncation flag is invalid")
        if self.truncated != (self.total_bytes > len(self.captured)):
            raise WindowsOutputCaptureError(
                "captured stream truncation flag does not match its byte counts"
            )
        if not self.truncated and hashlib.sha256(self.captured).hexdigest() != self.sha256:
            raise WindowsOutputCaptureError(
                "complete captured stream bytes do not match their hash"
            )


class _PipeReader:
    def __init__(self, native_api: Any, handle: int, limit: int, name: str) -> None:
        self._native_api = native_api
        self._handle = handle
        self._limit = limit
        self._name = name
        self._captured = bytearray()
        self._digest = hashlib.sha256()
        self._total = 0
        self._error: BaseException | None = None
        self._thread = threading.Thread(
            target=self._drain,
            name=f"kaliv-tier-a-{name}-drain",
            daemon=False,
        )

    def start(self) -> None:
        self._thread.start()

    def _drain(self) -> None:
        buffer = ctypes.create_string_buffer(_READ_CHUNK_BYTES)
        read = ctypes.c_uint32()
        try:
            while True:
                read.value = 0
                ok = self._native_api.kernel32.ReadFile(
                    ctypes.c_void_p(self._handle),
                    buffer,
                    len(buffer),
                    ctypes.byref(read),
                    None,
                )
                if not ok:
                    error = ctypes.get_last_error()
                    if error in {ERROR_BROKEN_PIPE, ERROR_INVALID_HANDLE}:
                        break
                    raise self._native_api.win_error(f"ReadFile({self._name})")
                if read.value == 0:
                    break
                chunk = bytes(buffer.raw[: read.value])
                self._digest.update(chunk)
                self._total += len(chunk)
                remaining = self._limit - len(self._captured)
                if remaining > 0:
                    self._captured.extend(chunk[:remaining])
        except BaseException as exc:  # retained and re-raised on the owner thread
            self._error = exc
        finally:
            handle = self._handle
            self._handle = 0
            if handle:
                try:
                    self._native_api.close_handle(handle)
                except BaseException as exc:
                    if self._error is None:
                        self._error = exc

    def finish(self, timeout_seconds: float) -> CapturedStream:
        self._thread.join(timeout_seconds)
        if self._thread.is_alive():
            raise WindowsOutputCaptureError(
                f"{self._name} capture did not reach EOF after process cleanup"
            )
        if self._error is not None:
            raise WindowsOutputCaptureError(
                f"{self._name} capture failed"
            ) from self._error
        captured = bytes(self._captured)
        return CapturedStream(
            captured=captured,
            sha256=self._digest.hexdigest(),
            total_bytes=self._total,
            truncated=self._total > len(captured),
        )


class _CaptureKernel32:
    """Delegate every Win32 call except the one standard-handle injection."""

    def __init__(self, owner: "WindowsOutputCapture", delegate: Any) -> None:
        self._owner = owner
        self._delegate = delegate

    def __getattr__(self, name: str) -> Any:
        return getattr(self._delegate, name)

    def CreateProcessW(self, *arguments: Any) -> int:
        if len(arguments) != 10:
            raise WindowsOutputCaptureError("unexpected CreateProcessW call shape")
        startup_pointer = arguments[8]
        startup = ctypes.cast(
            startup_pointer,
            ctypes.POINTER(_STARTUPINFOW),
        ).contents
        startup.dwFlags |= STARTF_USESTDHANDLES
        startup.hStdInput = ctypes.c_void_p(self._owner._stdin_read)
        startup.hStdOutput = ctypes.c_void_p(self._owner._stdout_write)
        startup.hStdError = ctypes.c_void_p(self._owner._stderr_write)
        forwarded = list(arguments)
        forwarded[4] = 1
        try:
            return int(self._delegate.CreateProcessW(*forwarded))
        finally:
            # These are child-side handles in the parent process. Closing them
            # immediately is required for deterministic EOF once the job exits.
            self._owner._close_child_ends()


class _CaptureApi:
    def __init__(self, owner: "WindowsOutputCapture", native_api: Any) -> None:
        self._native_api = native_api
        self.kernel32 = _CaptureKernel32(owner, native_api.kernel32)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._native_api, name)


class WindowsOutputCapture:
    """Own two concurrent pipe drains and one inherited NUL stdin handle."""

    def __init__(self, native_api: Any, max_output_bytes: int) -> None:
        if native_api is None or not hasattr(native_api, "kernel32"):
            raise WindowsOutputCaptureError("capture requires the launcher's native API")
        if (
            isinstance(max_output_bytes, bool)
            or not isinstance(max_output_bytes, int)
            or not 1_024 <= max_output_bytes <= _MAX_CAPTURE_BYTES
        ):
            raise WindowsOutputCaptureError(
                "capture budget must be 1024..100000000 bytes"
            )
        self.native_api = native_api
        self.max_output_bytes = max_output_bytes
        self.stdout_limit = (max_output_bytes + 1) // 2
        self.stderr_limit = max_output_bytes // 2
        self._started = False
        self._finished = False
        self._child_ends_closed = False
        self._configure_api()
        self._stdout_read, self._stdout_write = self._create_pipe("stdout")
        try:
            self._stderr_read, self._stderr_write = self._create_pipe("stderr")
        except Exception:
            self._close_handle(self._stdout_read)
            self._close_handle(self._stdout_write)
            raise
        try:
            self._stdin_read = self._open_nul_stdin()
        except Exception:
            self._close_handle(self._stdout_read)
            self._close_handle(self._stdout_write)
            self._close_handle(self._stderr_read)
            self._close_handle(self._stderr_write)
            raise
        self._stdout_reader = _PipeReader(
            native_api,
            self._stdout_read,
            self.stdout_limit,
            "stdout",
        )
        self._stderr_reader = _PipeReader(
            native_api,
            self._stderr_read,
            self.stderr_limit,
            "stderr",
        )
        self.api = _CaptureApi(self, native_api)

    def _configure_api(self) -> None:
        kernel32 = self.native_api.kernel32
        kernel32.CreatePipe.argtypes = [
            ctypes.POINTER(ctypes.c_void_p),
            ctypes.POINTER(ctypes.c_void_p),
            ctypes.POINTER(_SECURITY_ATTRIBUTES),
            ctypes.c_uint32,
        ]
        kernel32.CreatePipe.restype = ctypes.c_int
        kernel32.SetHandleInformation.argtypes = [
            ctypes.c_void_p,
            ctypes.c_uint32,
            ctypes.c_uint32,
        ]
        kernel32.SetHandleInformation.restype = ctypes.c_int
        kernel32.ReadFile.argtypes = [
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_uint32,
            ctypes.POINTER(ctypes.c_uint32),
            ctypes.c_void_p,
        ]
        kernel32.ReadFile.restype = ctypes.c_int
        kernel32.CreateFileW.argtypes = [
            ctypes.c_wchar_p,
            ctypes.c_uint32,
            ctypes.c_uint32,
            ctypes.POINTER(_SECURITY_ATTRIBUTES),
            ctypes.c_uint32,
            ctypes.c_uint32,
            ctypes.c_void_p,
        ]
        kernel32.CreateFileW.restype = ctypes.c_void_p

    @staticmethod
    def _security_attributes() -> _SECURITY_ATTRIBUTES:
        return _SECURITY_ATTRIBUTES(ctypes.sizeof(_SECURITY_ATTRIBUTES), None, 1)

    def _create_pipe(self, name: str) -> tuple[int, int]:
        read = ctypes.c_void_p()
        write = ctypes.c_void_p()
        security = self._security_attributes()
        if not self.native_api.kernel32.CreatePipe(
            ctypes.byref(read),
            ctypes.byref(write),
            ctypes.byref(security),
            0,
        ):
            raise self.native_api.win_error(f"CreatePipe({name})")
        read_handle = int(read.value or 0)
        write_handle = int(write.value or 0)
        if not read_handle or not write_handle:
            self._close_handle(read_handle)
            self._close_handle(write_handle)
            raise WindowsOutputCaptureError(f"CreatePipe({name}) returned no handles")
        if not self.native_api.kernel32.SetHandleInformation(
            ctypes.c_void_p(read_handle),
            HANDLE_FLAG_INHERIT,
            0,
        ):
            self._close_handle(read_handle)
            self._close_handle(write_handle)
            raise self.native_api.win_error(f"SetHandleInformation({name})")
        return read_handle, write_handle

    def _open_nul_stdin(self) -> int:
        security = self._security_attributes()
        handle = self.native_api.kernel32.CreateFileW(
            "NUL",
            GENERIC_READ,
            FILE_SHARE_READ | FILE_SHARE_WRITE,
            ctypes.byref(security),
            OPEN_EXISTING,
            FILE_ATTRIBUTE_NORMAL,
            None,
        )
        value = int(handle or 0)
        if not value or value == INVALID_HANDLE_VALUE:
            raise self.native_api.win_error("CreateFileW(NUL)")
        return value

    def _close_handle(self, handle: int) -> None:
        if handle:
            self.native_api.close_handle(handle)

    def _close_child_ends(self) -> None:
        if self._child_ends_closed:
            return
        errors: list[BaseException] = []
        for attribute in ("_stdin_read", "_stdout_write", "_stderr_write"):
            handle = getattr(self, attribute, 0)
            setattr(self, attribute, 0)
            if handle:
                try:
                    self._close_handle(handle)
                except BaseException as exc:
                    errors.append(exc)
        self._child_ends_closed = True
        if errors:
            raise WindowsOutputCaptureError(
                "child-side capture handles could not be closed"
            ) from errors[0]

    def start(self) -> None:
        if self._started or self._finished:
            raise WindowsOutputCaptureError("capture can only be started once")
        self._started = True
        self._stdout_reader.start()
        self._stderr_reader.start()

    def finish(self, timeout_seconds: float = 10.0) -> tuple[CapturedStream, CapturedStream]:
        if not self._started or self._finished:
            raise WindowsOutputCaptureError("capture is not in a finishable state")
        if timeout_seconds <= 0:
            raise WindowsOutputCaptureError("capture finish timeout must be positive")
        self._close_child_ends()
        stdout = self._stdout_reader.finish(timeout_seconds)
        stderr = self._stderr_reader.finish(timeout_seconds)
        self._finished = True
        if len(stdout.captured) + len(stderr.captured) > self.max_output_bytes:
            raise WindowsOutputCaptureError("capture exceeded its retained-byte budget")
        return stdout, stderr

    def abort(self) -> None:
        if self._finished:
            return
        try:
            self._close_child_ends()
        except Exception:
            pass
        if self._started:
            try:
                self._stdout_reader.finish(10.0)
            except Exception:
                pass
            try:
                self._stderr_reader.finish(10.0)
            except Exception:
                pass
        else:
            for attribute in ("_stdout_read", "_stderr_read"):
                handle = getattr(self, attribute, 0)
                setattr(self, attribute, 0)
                if handle:
                    try:
                        self._close_handle(handle)
                    except Exception:
                        pass
        self._finished = True
