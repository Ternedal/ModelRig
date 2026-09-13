"""OS-backed watch-before-observe history monitor for ADR-DC-013.

This module does not decide campaign authority.  It supplies one monotonic
history signal for the exact local Git metadata that can change
``refs/heads/main`` on the supported files ref backend.  A mutation followed by
restoration is still a mutation.

Linux uses inotify.  Windows uses overlapped ReadDirectoryChangesW so polling a
path value can never be mistaken for continuous history.  Watch loss, queue
overflow, malformed OS events, unsupported ref storage, linked/common Git
metadata and symbolic ``main`` all fail closed.
"""
from __future__ import annotations

import ctypes
import os
import re
import stat
import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .trusted_git_runtime_model import _has_linkish_component


class GitMainFreezeWatcherError(ValueError):
    """Exact Git-main history monitoring could not be established or retained."""


_IN_ACCESS = 0x00000001
_IN_MODIFY = 0x00000002
_IN_ATTRIB = 0x00000004
_IN_CLOSE_WRITE = 0x00000008
_IN_MOVED_FROM = 0x00000040
_IN_MOVED_TO = 0x00000080
_IN_CREATE = 0x00000100
_IN_DELETE = 0x00000200
_IN_DELETE_SELF = 0x00000400
_IN_MOVE_SELF = 0x00000800
_IN_UNMOUNT = 0x00002000
_IN_Q_OVERFLOW = 0x00004000
_IN_IGNORED = 0x00008000
_INOTIFY_EVENT = struct.Struct("iIII")
_IN_PARENT_MASK = (
    _IN_MODIFY
    | _IN_ATTRIB
    | _IN_CLOSE_WRITE
    | _IN_MOVED_FROM
    | _IN_MOVED_TO
    | _IN_CREATE
    | _IN_DELETE
    | _IN_DELETE_SELF
    | _IN_MOVE_SELF
    | _IN_UNMOUNT
)
_IN_CHILD_MUTATION_MASK = (
    _IN_MODIFY
    | _IN_ATTRIB
    | _IN_CLOSE_WRITE
    | _IN_MOVED_FROM
    | _IN_MOVED_TO
    | _IN_CREATE
    | _IN_DELETE
)

_FILE_LIST_DIRECTORY = 0x0001
_FILE_SHARE_READ = 0x00000001
_FILE_SHARE_WRITE = 0x00000002
_FILE_SHARE_DELETE = 0x00000004
_OPEN_EXISTING = 3
_FILE_FLAG_BACKUP_SEMANTICS = 0x02000000
_FILE_FLAG_OVERLAPPED = 0x40000000
_FILE_NOTIFY_CHANGE_FILE_NAME = 0x00000001
_FILE_NOTIFY_CHANGE_DIR_NAME = 0x00000002
_FILE_NOTIFY_CHANGE_ATTRIBUTES = 0x00000004
_FILE_NOTIFY_CHANGE_SIZE = 0x00000008
_FILE_NOTIFY_CHANGE_LAST_WRITE = 0x00000010
_FILE_NOTIFY_CHANGE_CREATION = 0x00000040
_FILE_NOTIFY_CHANGE_SECURITY = 0x00000100
_WINDOWS_NOTIFY_FILTER = (
    _FILE_NOTIFY_CHANGE_FILE_NAME
    | _FILE_NOTIFY_CHANGE_DIR_NAME
    | _FILE_NOTIFY_CHANGE_ATTRIBUTES
    | _FILE_NOTIFY_CHANGE_SIZE
    | _FILE_NOTIFY_CHANGE_LAST_WRITE
    | _FILE_NOTIFY_CHANGE_CREATION
    | _FILE_NOTIFY_CHANGE_SECURITY
)
_WAIT_OBJECT_0 = 0
_WAIT_TIMEOUT = 258
_ERROR_IO_INCOMPLETE = 996
_ERROR_OPERATION_ABORTED = 995
_INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value
_MAX_NOTIFY_BYTES = 64 * 1024
_CONFIG_REF_STORAGE = re.compile(
    r"^\s*refStorage\s*=\s*(\S+)\s*$",
    re.IGNORECASE | re.MULTILINE,
)


@dataclass(frozen=True, slots=True)
class _WatchTarget:
    parent: Path
    name: str
    scope_label: str


def _path_identity(path: Path) -> tuple[int, int, int]:
    observed = path.lstat()
    kind = stat.S_IFMT(observed.st_mode)
    return int(observed.st_dev), int(observed.st_ino), int(kind)


def _path_state(path: Path) -> tuple[bool, tuple[int, int, int] | None]:
    try:
        return True, _path_identity(path)
    except FileNotFoundError:
        return False, None
    except OSError as exc:
        raise GitMainFreezeWatcherError(
            "Git main-freeze watched path identity is unavailable"
        ) from exc


def _safe_existing_directory(path: Path, *, name: str) -> Path:
    candidate = Path(path)
    if (
        not candidate.is_absolute()
        or not candidate.is_dir()
        or _has_linkish_component(candidate)
    ):
        raise GitMainFreezeWatcherError(f"{name} must be an existing link-free directory")
    return candidate.resolve()


def _relative_scope(root: Path, path: Path) -> str:
    try:
        relative = path.relative_to(root)
        return "." if relative == Path(".") else relative.as_posix()
    except ValueError:
        depth = 0
        cursor = root.parent
        while cursor != cursor.parent:
            if path == cursor:
                return "<repo-parent>" if depth == 0 else f"<repo-ancestor-{depth}>"
            depth += 1
            cursor = cursor.parent
        if path == cursor:
            return f"<repo-ancestor-{depth}>"
        return "<host-path>"


def _watch_target(root: Path, path: Path) -> _WatchTarget:
    return _WatchTarget(
        parent=path.parent,
        name=path.name,
        scope_label=_relative_scope(root, path),
    )


def _read_small_text(path: Path, *, maximum: int = 64 * 1024) -> str:
    try:
        payload = path.read_bytes()
    except FileNotFoundError:
        return ""
    except OSError as exc:
        raise GitMainFreezeWatcherError(
            "Git main-freeze metadata could not be inspected"
        ) from exc
    if len(payload) > maximum:
        raise GitMainFreezeWatcherError(
            "Git main-freeze metadata exceeds inspection budget"
        )
    try:
        return payload.decode("utf-8", errors="strict")
    except UnicodeError as exc:
        raise GitMainFreezeWatcherError(
            "Git main-freeze metadata is not valid UTF-8"
        ) from exc


def _build_watch_plan(repository_root: Path) -> tuple[_WatchTarget, ...]:
    """Build exact files-backend watch targets without following alternate metadata."""

    root = _safe_existing_directory(repository_root, name="repository root")
    dotgit = root / ".git"
    if dotgit.is_file():
        raise GitMainFreezeWatcherError(
            "linked-worktree Git metadata is unsupported for continuous main freeze"
        )
    git_dir = _safe_existing_directory(dotgit, name="repository .git directory")

    if (git_dir / "commondir").exists() or (git_dir / "gitdir").exists():
        raise GitMainFreezeWatcherError(
            "common/linked Git metadata is unsupported for continuous main freeze"
        )
    if (git_dir / "reftable").exists():
        raise GitMainFreezeWatcherError(
            "reftable is unsupported for continuous main freeze"
        )
    config_text = _read_small_text(git_dir / "config")
    ref_storage = _CONFIG_REF_STORAGE.search(config_text)
    if ref_storage is not None and ref_storage.group(1).strip().lower() != "files":
        raise GitMainFreezeWatcherError(
            "non-files Git ref storage is unsupported for continuous main freeze"
        )

    refs = git_dir / "refs"
    heads = refs / "heads"
    _safe_existing_directory(refs, name="Git refs directory")
    _safe_existing_directory(heads, name="Git heads directory")

    main_ref = heads / "main"
    if main_ref.exists():
        if main_ref.is_symlink() or not main_ref.is_file():
            raise GitMainFreezeWatcherError(
                "loose main ref must be an ordinary file when present"
            )
        content = _read_small_text(main_ref, maximum=4096).strip()
        if content.startswith("ref:"):
            raise GitMainFreezeWatcherError(
                "symbolic main ref is unsupported for continuous main freeze"
            )

    targets: list[_WatchTarget] = []
    cursor = root
    while cursor.parent != cursor:
        targets.append(_watch_target(root, cursor))
        cursor = cursor.parent

    for path in (
        git_dir / "config",
        git_dir / "config.lock",
        git_dir / "refs",
        git_dir / "refs" / "heads",
        main_ref,
        heads / "main.lock",
        git_dir / "packed-refs",
        git_dir / "packed-refs.lock",
    ):
        targets.append(_watch_target(root, path))

    by_key: dict[tuple[str, str], _WatchTarget] = {}
    for target in targets:
        key = (os.path.normcase(os.fspath(target.parent)), target.name)
        by_key[key] = target
    return tuple(
        sorted(by_key.values(), key=lambda item: (item.scope_label, item.name))
    )


class _WindowsOverlapped(ctypes.Structure):
    _fields_ = [
        ("Internal", ctypes.c_size_t),
        ("InternalHigh", ctypes.c_size_t),
        ("Offset", ctypes.c_uint32),
        ("OffsetHigh", ctypes.c_uint32),
        ("hEvent", ctypes.c_void_p),
    ]


class _WindowsPendingWatch:
    __slots__ = (
        "directory",
        "names",
        "handle",
        "event",
        "overlapped",
        "buffer",
        "closed",
    )

    def __init__(self, directory: Path, names: frozenset[str]) -> None:
        if os.name != "nt":
            raise GitMainFreezeWatcherError(
                "ReadDirectoryChangesW main-freeze watcher requires Windows"
            )
        self.directory = directory
        self.names = names
        self.handle: int | None = None
        self.event: int | None = None
        self.overlapped = _WindowsOverlapped()
        self.buffer = ctypes.create_string_buffer(_MAX_NOTIFY_BYTES)
        self.closed = False
        self._open_and_issue()

    @staticmethod
    def _kernel32():
        try:
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        except (AttributeError, OSError) as exc:
            raise GitMainFreezeWatcherError(
                "Windows change-notification API is unavailable"
            ) from exc
        return kernel32

    def _open_and_issue(self) -> None:
        kernel32 = self._kernel32()
        CreateFileW = kernel32.CreateFileW
        CreateFileW.argtypes = [
            ctypes.c_wchar_p,
            ctypes.c_uint32,
            ctypes.c_uint32,
            ctypes.c_void_p,
            ctypes.c_uint32,
            ctypes.c_uint32,
            ctypes.c_void_p,
        ]
        CreateFileW.restype = ctypes.c_void_p
        CreateEventW = kernel32.CreateEventW
        CreateEventW.argtypes = [
            ctypes.c_void_p,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_wchar_p,
        ]
        CreateEventW.restype = ctypes.c_void_p

        handle = CreateFileW(
            os.fspath(self.directory),
            _FILE_LIST_DIRECTORY,
            _FILE_SHARE_READ | _FILE_SHARE_WRITE | _FILE_SHARE_DELETE,
            None,
            _OPEN_EXISTING,
            _FILE_FLAG_BACKUP_SEMANTICS | _FILE_FLAG_OVERLAPPED,
            None,
        )
        if handle in (None, 0, _INVALID_HANDLE_VALUE):
            raise GitMainFreezeWatcherError(
                "Windows Git main-freeze directory could not be opened"
            )
        event = CreateEventW(None, 1, 0, None)
        if not event:
            kernel32.CloseHandle(ctypes.c_void_p(handle))
            raise GitMainFreezeWatcherError(
                "Windows Git main-freeze event could not be created"
            )
        self.handle = int(handle)
        self.event = int(event)
        self.overlapped = _WindowsOverlapped()
        self.overlapped.hEvent = ctypes.c_void_p(self.event)
        self._issue()

    def _issue(self) -> None:
        if self.handle is None:
            raise GitMainFreezeWatcherError("Windows main-freeze watch is closed")
        kernel32 = self._kernel32()
        ReadDirectoryChangesW = kernel32.ReadDirectoryChangesW
        ReadDirectoryChangesW.argtypes = [
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_uint32,
            ctypes.c_int,
            ctypes.c_uint32,
            ctypes.c_void_p,
            ctypes.POINTER(_WindowsOverlapped),
            ctypes.c_void_p,
        ]
        ReadDirectoryChangesW.restype = ctypes.c_int
        ok = ReadDirectoryChangesW(
            ctypes.c_void_p(self.handle),
            ctypes.byref(self.buffer),
            ctypes.sizeof(self.buffer),
            0,
            _WINDOWS_NOTIFY_FILTER,
            None,
            ctypes.byref(self.overlapped),
            None,
        )
        if not ok:
            raise GitMainFreezeWatcherError(
                "Windows Git main-freeze watch could not be armed"
            )

    def _parse(self, count: int) -> bool:
        if count <= 0 or count > ctypes.sizeof(self.buffer):
            return False
        payload = memoryview(self.buffer.raw)[:count]
        offset = 0
        while True:
            if count - offset < 12:
                return False
            next_offset, _action, name_bytes = struct.unpack_from("<III", payload, offset)
            start = offset + 12
            end = start + int(name_bytes)
            if name_bytes % 2 or end > count:
                return False
            try:
                name = bytes(payload[start:end]).decode("utf-16-le", errors="strict")
            except UnicodeError:
                return False
            if name.casefold() in {item.casefold() for item in self.names}:
                return False
            if next_offset == 0:
                return end == count
            if next_offset < 12 or offset + next_offset >= count:
                return False
            offset += int(next_offset)

    def clean(self) -> bool:
        if self.closed or self.handle is None or self.event is None:
            return False
        kernel32 = self._kernel32()
        WaitForSingleObject = kernel32.WaitForSingleObject
        WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
        WaitForSingleObject.restype = ctypes.c_uint32
        status = WaitForSingleObject(ctypes.c_void_p(self.event), 0)
        if status == _WAIT_TIMEOUT:
            return True
        if status != _WAIT_OBJECT_0:
            return False

        transferred = ctypes.c_uint32()
        GetOverlappedResult = kernel32.GetOverlappedResult
        GetOverlappedResult.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(_WindowsOverlapped),
            ctypes.POINTER(ctypes.c_uint32),
            ctypes.c_int,
        ]
        GetOverlappedResult.restype = ctypes.c_int
        if not GetOverlappedResult(
            ctypes.c_void_p(self.handle),
            ctypes.byref(self.overlapped),
            ctypes.byref(transferred),
            0,
        ):
            error = ctypes.get_last_error()
            if error in {_ERROR_IO_INCOMPLETE, _ERROR_OPERATION_ABORTED}:
                return False
            return False
        if not self._parse(int(transferred.value)):
            return False

        ResetEvent = kernel32.ResetEvent
        ResetEvent.argtypes = [ctypes.c_void_p]
        ResetEvent.restype = ctypes.c_int
        if not ResetEvent(ctypes.c_void_p(self.event)):
            return False
        self.overlapped = _WindowsOverlapped()
        self.overlapped.hEvent = ctypes.c_void_p(self.event)
        try:
            self._issue()
        except GitMainFreezeWatcherError:
            return False
        return True

    def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        kernel32 = self._kernel32()
        if self.handle is not None:
            CancelIoEx = getattr(kernel32, "CancelIoEx", None)
            if CancelIoEx is not None:
                CancelIoEx.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
                CancelIoEx.restype = ctypes.c_int
                CancelIoEx(ctypes.c_void_p(self.handle), None)
            kernel32.CloseHandle(ctypes.c_void_p(self.handle))
            self.handle = None
        if self.event is not None:
            kernel32.CloseHandle(ctypes.c_void_p(self.event))
            self.event = None


class GitMainFreezeWatcher:
    """Watch exact Git files-ref history for one live physical campaign."""

    def __init__(self, repository_root: Path) -> None:
        self._root = _safe_existing_directory(repository_root, name="repository root")
        self._plan = _build_watch_plan(self._root)
        self._initial: dict[tuple[str, str], tuple[bool, tuple[int, int, int] | None]] = {}
        self._backend = ""
        self._inotify_fd: int | None = None
        self._inotify_expected: dict[int, frozenset[bytes]] | None = None
        self._windows_watches: list[_WindowsPendingWatch] = []
        self._armed = False
        self._closed = False
        self._revoked = False

    @property
    def backend(self) -> str:
        return self._backend

    @property
    def scope(self) -> tuple[str, ...]:
        return tuple(sorted({item.scope_label for item in self._plan}))

    def _capture_state(self) -> None:
        self._initial = {
            (os.path.normcase(os.fspath(item.parent)), item.name): _path_state(
                item.parent / item.name
            )
            for item in self._plan
        }

    def _state_matches(self) -> bool:
        try:
            for item in self._plan:
                key = (os.path.normcase(os.fspath(item.parent)), item.name)
                if _path_state(item.parent / item.name) != self._initial.get(key):
                    return False
            return True
        except GitMainFreezeWatcherError:
            return False

    def _arm_linux(self) -> None:
        libc = ctypes.CDLL(None, use_errno=True)
        init1 = getattr(libc, "inotify_init1", None)
        add_watch = getattr(libc, "inotify_add_watch", None)
        if init1 is None or add_watch is None:
            raise GitMainFreezeWatcherError(
                "Linux inotify main-freeze monitoring is unavailable"
            )
        init1.argtypes = [ctypes.c_int]
        init1.restype = ctypes.c_int
        add_watch.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_uint32]
        add_watch.restype = ctypes.c_int
        fd = init1(os.O_NONBLOCK | getattr(os, "O_CLOEXEC", 0))
        if fd < 0:
            raise GitMainFreezeWatcherError(
                "Linux inotify main-freeze monitor could not be opened"
            )
        expected: dict[int, set[bytes]] = {}
        try:
            grouped: dict[Path, set[str]] = {}
            for item in self._plan:
                grouped.setdefault(item.parent, set()).add(item.name)
            for directory, names in grouped.items():
                watch = add_watch(
                    fd,
                    os.fsencode(os.fspath(directory)),
                    _IN_PARENT_MASK,
                )
                if watch < 0:
                    raise GitMainFreezeWatcherError(
                        "Git main-freeze directory could not be inotify-watched"
                    )
                expected.setdefault(watch, set()).update(
                    os.fsencode(name) for name in names
                )
            self._inotify_fd = fd
            self._inotify_expected = {
                watch: frozenset(names) for watch, names in expected.items()
            }
            self._backend = "inotify"
        except BaseException:
            os.close(fd)
            raise

    def _arm_windows(self) -> None:
        grouped: dict[Path, set[str]] = {}
        for item in self._plan:
            grouped.setdefault(item.parent, set()).add(item.name)
        watches: list[_WindowsPendingWatch] = []
        try:
            for directory, names in grouped.items():
                watches.append(
                    _WindowsPendingWatch(directory, frozenset(names))
                )
            self._windows_watches = watches
            self._backend = "ReadDirectoryChangesW"
        except BaseException:
            for watch in watches:
                try:
                    watch.close()
                except Exception:
                    pass
            raise

    def arm(self) -> None:
        if self._armed or self._closed:
            raise GitMainFreezeWatcherError("main-freeze watcher lifecycle is invalid")
        self._capture_state()
        if os.name == "posix" and hasattr(os, "uname") and os.uname().sysname == "Linux":
            self._arm_linux()
        elif os.name == "nt":
            self._arm_windows()
        else:
            raise GitMainFreezeWatcherError(
                "continuous Git main history monitoring is unsupported on this platform"
            )
        self._armed = True
        if not self._state_matches() or not self._history_clean():
            self._revoked = True
            raise GitMainFreezeWatcherError(
                "Git main-freeze metadata changed while watcher was armed"
            )

    def _linux_clean(self) -> bool:
        if self._inotify_fd is None or self._inotify_expected is None:
            return False
        while True:
            try:
                payload = os.read(self._inotify_fd, _MAX_NOTIFY_BYTES)
            except BlockingIOError:
                return True
            except OSError:
                return False
            if not payload:
                return False
            offset = 0
            while offset < len(payload):
                if len(payload) - offset < _INOTIFY_EVENT.size:
                    return False
                watch, mask, _cookie, name_length = _INOTIFY_EVENT.unpack_from(
                    payload, offset
                )
                end = offset + _INOTIFY_EVENT.size + int(name_length)
                if end > len(payload):
                    return False
                raw_name = payload[offset + _INOTIFY_EVENT.size : end]
                name = raw_name.split(b"\x00", 1)[0]
                if mask & _IN_Q_OVERFLOW:
                    return False
                expected = self._inotify_expected.get(watch)
                if expected is None:
                    return False
                if mask & (_IN_DELETE_SELF | _IN_MOVE_SELF | _IN_UNMOUNT | _IN_IGNORED):
                    return False
                if name in expected and mask & _IN_CHILD_MUTATION_MASK:
                    return False
                offset = end

    def _history_clean(self) -> bool:
        if self._backend == "inotify":
            return self._linux_clean()
        if self._backend == "ReadDirectoryChangesW":
            return all(watch.clean() for watch in self._windows_watches)
        return False

    def clean(self) -> bool:
        if self._revoked or not self._armed or self._closed:
            return False
        if not self._history_clean():
            self._revoked = True
            return False
        if not self._state_matches():
            self._revoked = True
            return False
        if not self._history_clean():
            self._revoked = True
            return False
        return True

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._revoked = True
        if self._inotify_fd is not None:
            try:
                os.close(self._inotify_fd)
            except OSError:
                pass
            self._inotify_fd = None
            self._inotify_expected = None
        for watch in self._windows_watches:
            try:
                watch.close()
            except Exception:
                pass
        self._windows_watches = []


__all__: list[str] = []
