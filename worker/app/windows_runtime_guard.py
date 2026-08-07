"""Lifetime immutability guard for a staged Tier-A runtime closure.

The exact closure tree is locked only after staging verification and remains
read/execute-only until the complete Job Object has been closed.  The guard
combines two Windows controls:

* a protected DACL granting only read/execute to the current user and the exact
  AppContainer package SID; and
* open file/directory handles that allow read sharing but deny write/delete
  sharing, preventing overwrite, replacement, rename and deletion.

Original DACLs are retained through WRITE_DAC handles and restored after the
process tree has terminated.  This module does not launch processes and grants
no command, catalog or signing authority.
"""
from __future__ import annotations

import ctypes
import hashlib
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Sequence

from .windows_job import WindowsIsolationError
from .windows_restricted import AppContainerProfile, RestrictedLaunchPolicy

ERROR_INSUFFICIENT_BUFFER = 122
INVALID_FILE_ATTRIBUTES = 0xFFFFFFFF
FILE_ATTRIBUTE_REPARSE_POINT = 0x00000400
FILE_ATTRIBUTE_NORMAL = 0x00000080
FILE_FLAG_BACKUP_SEMANTICS = 0x02000000
FILE_FLAG_OPEN_REPARSE_POINT = 0x00200000
FILE_SHARE_READ = 0x00000001
OPEN_EXISTING = 3
GENERIC_READ = 0x80000000
READ_CONTROL = 0x00020000
WRITE_DAC = 0x00040000
TOKEN_QUERY = 0x0008
TOKEN_USER = 1
SE_FILE_OBJECT = 1
DACL_SECURITY_INFORMATION = 0x00000004
PROTECTED_DACL_SECURITY_INFORMATION = 0x80000000
UNPROTECTED_DACL_SECURITY_INFORMATION = 0x20000000
SE_DACL_PROTECTED = 0x1000
SET_ACCESS = 2
TRUSTEE_IS_SID = 0
TRUSTEE_IS_UNKNOWN = 0
SUB_CONTAINERS_AND_OBJECTS_INHERIT = 0x3
NO_INHERITANCE = 0
FILE_GENERIC_READ = 0x00120089
FILE_GENERIC_EXECUTE = 0x001200A0
RUNTIME_READ_EXECUTE_MASK = FILE_GENERIC_READ | FILE_GENERIC_EXECUTE
INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value
_HEX64 = re.compile(r"^[0-9a-f]{64}$")


class RuntimeLifetimeGuardError(WindowsIsolationError):
    """The staged closure could not be held immutable for process lifetime."""


class _SID_AND_ATTRIBUTES(ctypes.Structure):
    _fields_ = [("Sid", ctypes.c_void_p), ("Attributes", ctypes.c_uint32)]


class _TOKEN_USER(ctypes.Structure):
    _fields_ = [("User", _SID_AND_ATTRIBUTES)]


class _TRUSTEE_W(ctypes.Structure):
    _fields_ = [
        ("pMultipleTrustee", ctypes.c_void_p),
        ("MultipleTrusteeOperation", ctypes.c_int),
        ("TrusteeForm", ctypes.c_int),
        ("TrusteeType", ctypes.c_int),
        ("ptstrName", ctypes.c_void_p),
    ]


class _EXPLICIT_ACCESS_W(ctypes.Structure):
    _fields_ = [
        ("grfAccessPermissions", ctypes.c_uint32),
        ("grfAccessMode", ctypes.c_int),
        ("grfInheritance", ctypes.c_uint32),
        ("Trustee", _TRUSTEE_W),
    ]


@dataclass(frozen=True, slots=True)
class RuntimeClosureLifetimeReceipt:
    root: str
    appcontainer_sid: str
    tree_sha256: str
    files_locked: int
    directories_locked: int
    handles_locked: int
    access_mask: int = RUNTIME_READ_EXECUTE_MASK

    def __post_init__(self) -> None:
        if not os.path.isabs(self.root):
            raise RuntimeLifetimeGuardError("runtime guard receipt root is invalid")
        if not self.appcontainer_sid.startswith("S-"):
            raise RuntimeLifetimeGuardError("runtime guard receipt SID is invalid")
        if _HEX64.fullmatch(self.tree_sha256) is None:
            raise RuntimeLifetimeGuardError("runtime guard receipt hash is invalid")
        for name, value in (
            ("files_locked", self.files_locked),
            ("directories_locked", self.directories_locked),
            ("handles_locked", self.handles_locked),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise RuntimeLifetimeGuardError(
                    f"runtime guard receipt {name} is invalid"
                )
        if self.handles_locked != self.files_locked + self.directories_locked:
            raise RuntimeLifetimeGuardError(
                "runtime guard receipt handle count is inconsistent"
            )
        if self.access_mask != RUNTIME_READ_EXECUTE_MASK:
            raise RuntimeLifetimeGuardError("runtime guard receipt access changed")


@dataclass(slots=True)
class _GuardedObject:
    path: str
    is_directory: bool
    handle: int
    descriptor: int
    original_dacl: int | None
    dacl_was_protected: bool
    locked: bool = False


class NativeWindowsRuntimeGuardApi:
    """Injectable Win32 calls used by the runtime lifetime guard."""

    def __init__(self) -> None:
        if os.name != "nt":
            raise RuntimeLifetimeGuardError(
                "runtime lifetime guard requires Windows"
            )
        self.kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self.advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)

        k32 = self.kernel32
        advapi = self.advapi32

        k32.CreateFileW.argtypes = [
            ctypes.c_wchar_p,
            ctypes.c_uint32,
            ctypes.c_uint32,
            ctypes.c_void_p,
            ctypes.c_uint32,
            ctypes.c_uint32,
            ctypes.c_void_p,
        ]
        k32.CreateFileW.restype = ctypes.c_void_p
        k32.CloseHandle.argtypes = [ctypes.c_void_p]
        k32.CloseHandle.restype = ctypes.c_int
        k32.GetCurrentProcess.argtypes = []
        k32.GetCurrentProcess.restype = ctypes.c_void_p
        k32.GetFileAttributesW.argtypes = [ctypes.c_wchar_p]
        k32.GetFileAttributesW.restype = ctypes.c_uint32
        k32.LocalFree.argtypes = [ctypes.c_void_p]
        k32.LocalFree.restype = ctypes.c_void_p

        advapi.OpenProcessToken.argtypes = [
            ctypes.c_void_p,
            ctypes.c_uint32,
            ctypes.POINTER(ctypes.c_void_p),
        ]
        advapi.OpenProcessToken.restype = ctypes.c_int
        advapi.GetTokenInformation.argtypes = [
            ctypes.c_void_p,
            ctypes.c_int,
            ctypes.c_void_p,
            ctypes.c_uint32,
            ctypes.POINTER(ctypes.c_uint32),
        ]
        advapi.GetTokenInformation.restype = ctypes.c_int
        advapi.GetSecurityInfo.argtypes = [
            ctypes.c_void_p,
            ctypes.c_int,
            ctypes.c_uint32,
            ctypes.POINTER(ctypes.c_void_p),
            ctypes.POINTER(ctypes.c_void_p),
            ctypes.POINTER(ctypes.c_void_p),
            ctypes.POINTER(ctypes.c_void_p),
            ctypes.POINTER(ctypes.c_void_p),
        ]
        advapi.GetSecurityInfo.restype = ctypes.c_uint32
        advapi.GetSecurityDescriptorControl.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_ushort),
            ctypes.POINTER(ctypes.c_uint32),
        ]
        advapi.GetSecurityDescriptorControl.restype = ctypes.c_int
        advapi.SetEntriesInAclW.argtypes = [
            ctypes.c_uint32,
            ctypes.POINTER(_EXPLICIT_ACCESS_W),
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_void_p),
        ]
        advapi.SetEntriesInAclW.restype = ctypes.c_uint32
        advapi.SetSecurityInfo.argtypes = [
            ctypes.c_void_p,
            ctypes.c_int,
            ctypes.c_uint32,
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_void_p,
        ]
        advapi.SetSecurityInfo.restype = ctypes.c_uint32

    @staticmethod
    def win_error(action: str) -> RuntimeLifetimeGuardError:
        return RuntimeLifetimeGuardError(
            f"{action} failed with WinError {ctypes.get_last_error()}"
        )

    def close_handle(self, handle: int) -> None:
        if handle and not self.kernel32.CloseHandle(ctypes.c_void_p(handle)):
            raise self.win_error("CloseHandle")

    def local_free(self, pointer: int | None) -> None:
        if pointer:
            self.kernel32.LocalFree(ctypes.c_void_p(pointer))

    def is_reparse(self, path: str) -> bool:
        attributes = int(self.kernel32.GetFileAttributesW(path))
        if attributes == INVALID_FILE_ATTRIBUTES:
            raise self.win_error("GetFileAttributesW")
        return bool(attributes & FILE_ATTRIBUTE_REPARSE_POINT)

    def current_user_sid(self) -> tuple[ctypes.Array[Any], int]:
        token = ctypes.c_void_p()
        if not self.advapi32.OpenProcessToken(
            self.kernel32.GetCurrentProcess(), TOKEN_QUERY, ctypes.byref(token)
        ):
            raise self.win_error("OpenProcessToken")
        try:
            needed = ctypes.c_uint32()
            self.advapi32.GetTokenInformation(
                token, TOKEN_USER, None, 0, ctypes.byref(needed)
            )
            if ctypes.get_last_error() != ERROR_INSUFFICIENT_BUFFER or not needed.value:
                raise self.win_error("GetTokenInformation(size)")
            storage = ctypes.create_string_buffer(needed.value)
            if not self.advapi32.GetTokenInformation(
                token,
                TOKEN_USER,
                storage,
                needed.value,
                ctypes.byref(needed),
            ):
                raise self.win_error("GetTokenInformation")
            token_user = ctypes.cast(storage, ctypes.POINTER(_TOKEN_USER)).contents
            if not token_user.User.Sid:
                raise RuntimeLifetimeGuardError("current token returned no user SID")
            return storage, int(token_user.User.Sid)
        finally:
            self.close_handle(int(token.value) if token.value else 0)

    def open_guard_handle(self, path: str, *, is_directory: bool) -> int:
        flags = FILE_FLAG_OPEN_REPARSE_POINT
        if is_directory:
            flags |= FILE_FLAG_BACKUP_SEMANTICS
        else:
            flags |= FILE_ATTRIBUTE_NORMAL
        handle = self.kernel32.CreateFileW(
            path,
            GENERIC_READ | READ_CONTROL | WRITE_DAC,
            FILE_SHARE_READ,
            None,
            OPEN_EXISTING,
            flags,
            None,
        )
        value = ctypes.cast(handle, ctypes.c_void_p).value
        if not value or value == INVALID_HANDLE_VALUE:
            raise self.win_error("CreateFileW(runtime guard)")
        return int(value)

    def snapshot_dacl(
        self, path: str, handle: int, *, is_directory: bool
    ) -> _GuardedObject:
        dacl = ctypes.c_void_p()
        descriptor = ctypes.c_void_p()
        code = int(
            self.advapi32.GetSecurityInfo(
                ctypes.c_void_p(handle),
                SE_FILE_OBJECT,
                DACL_SECURITY_INFORMATION,
                None,
                None,
                ctypes.byref(dacl),
                None,
                ctypes.byref(descriptor),
            )
        )
        if code:
            raise RuntimeLifetimeGuardError(
                f"GetSecurityInfo failed with WinError {code}"
            )
        control = ctypes.c_ushort()
        revision = ctypes.c_uint32()
        if not self.advapi32.GetSecurityDescriptorControl(
            descriptor, ctypes.byref(control), ctypes.byref(revision)
        ):
            self.local_free(int(descriptor.value) if descriptor.value else None)
            raise self.win_error("GetSecurityDescriptorControl")
        return _GuardedObject(
            path=path,
            is_directory=is_directory,
            handle=handle,
            descriptor=int(descriptor.value) if descriptor.value else 0,
            original_dacl=int(dacl.value) if dacl.value else None,
            dacl_was_protected=bool(control.value & SE_DACL_PROTECTED),
        )

    @staticmethod
    def _trustee(sid_pointer: int) -> _TRUSTEE_W:
        return _TRUSTEE_W(
            None,
            0,
            TRUSTEE_IS_SID,
            TRUSTEE_IS_UNKNOWN,
            ctypes.c_void_p(sid_pointer),
        )

    def lock_dacl(
        self,
        guarded: _GuardedObject,
        *,
        current_user_sid: int,
        appcontainer_sid: int,
    ) -> None:
        inheritance = (
            SUB_CONTAINERS_AND_OBJECTS_INHERIT
            if guarded.is_directory
            else NO_INHERITANCE
        )
        entries = (_EXPLICIT_ACCESS_W * 2)(
            _EXPLICIT_ACCESS_W(
                RUNTIME_READ_EXECUTE_MASK,
                SET_ACCESS,
                inheritance,
                self._trustee(current_user_sid),
            ),
            _EXPLICIT_ACCESS_W(
                RUNTIME_READ_EXECUTE_MASK,
                SET_ACCESS,
                inheritance,
                self._trustee(appcontainer_sid),
            ),
        )
        new_acl = ctypes.c_void_p()
        code = int(
            self.advapi32.SetEntriesInAclW(
                2, entries, None, ctypes.byref(new_acl)
            )
        )
        if code:
            raise RuntimeLifetimeGuardError(
                f"SetEntriesInAclW(runtime guard) failed with WinError {code}"
            )
        try:
            code = int(
                self.advapi32.SetSecurityInfo(
                    ctypes.c_void_p(guarded.handle),
                    SE_FILE_OBJECT,
                    DACL_SECURITY_INFORMATION
                    | PROTECTED_DACL_SECURITY_INFORMATION,
                    None,
                    None,
                    new_acl,
                    None,
                )
            )
            if code:
                raise RuntimeLifetimeGuardError(
                    f"SetSecurityInfo(runtime guard) failed with WinError {code}"
                )
            guarded.locked = True
        finally:
            self.local_free(int(new_acl.value) if new_acl.value else None)

    def restore_dacl(self, guarded: _GuardedObject) -> None:
        protection = (
            PROTECTED_DACL_SECURITY_INFORMATION
            if guarded.dacl_was_protected
            else UNPROTECTED_DACL_SECURITY_INFORMATION
        )
        code = int(
            self.advapi32.SetSecurityInfo(
                ctypes.c_void_p(guarded.handle),
                SE_FILE_OBJECT,
                DACL_SECURITY_INFORMATION | protection,
                None,
                None,
                ctypes.c_void_p(guarded.original_dacl)
                if guarded.original_dacl
                else None,
                None,
            )
        )
        if code:
            raise RuntimeLifetimeGuardError(
                f"SetSecurityInfo(restore runtime DACL) failed with WinError {code}"
            )
        guarded.locked = False


class WindowsRuntimeClosureLifetimeGuard:
    """Own protected DACLs and deny-write handles for one exact closure tree."""

    def __init__(
        self,
        *,
        receipt: RuntimeClosureLifetimeReceipt,
        guarded: list[_GuardedObject],
        api: Any,
    ) -> None:
        self.receipt = receipt
        self._guarded = guarded
        self._api = api
        self._closed = False

    @staticmethod
    def _relative_path(value: Any, *, name: str) -> str:
        if (
            not isinstance(value, str)
            or not value
            or value.startswith("/")
            or "\\" in value
            or "\0" in value
        ):
            raise RuntimeLifetimeGuardError(f"{name} is invalid")
        parsed = PurePosixPath(value)
        if any(part in {"", ".", ".."} for part in parsed.parts):
            raise RuntimeLifetimeGuardError(f"{name} is invalid")
        return parsed.as_posix()

    @staticmethod
    def _file_entries(
        files: Sequence[tuple[str, str, int]],
    ) -> tuple[tuple[str, str, int], ...]:
        normalized: list[tuple[str, str, int]] = []
        for value in files:
            if not isinstance(value, tuple) or len(value) != 3:
                raise RuntimeLifetimeGuardError(
                    "runtime guard file entry is invalid"
                )
            relative = WindowsRuntimeClosureLifetimeGuard._relative_path(
                value[0], name="runtime guard file path"
            )
            sha256 = value[1]
            size = value[2]
            if not isinstance(sha256, str) or _HEX64.fullmatch(sha256) is None:
                raise RuntimeLifetimeGuardError("runtime guard file hash is invalid")
            if isinstance(size, bool) or not isinstance(size, int) or size < 1:
                raise RuntimeLifetimeGuardError("runtime guard file size is invalid")
            normalized.append((relative, sha256, size))
        result = tuple(sorted(normalized))
        paths = tuple(item[0] for item in result)
        if not result or len(paths) != len(set(paths)):
            raise RuntimeLifetimeGuardError(
                "runtime guard files must be non-empty and unique"
            )
        return result

    @staticmethod
    def _tree_sha256(entries: tuple[tuple[str, str, int], ...]) -> str:
        payload = json.dumps(
            [
                {"relative_path": path, "sha256": sha256, "size_bytes": size}
                for path, sha256, size in entries
            ],
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(b"kaliv-runtime-lifetime-tree/v1\0" + payload).hexdigest()

    @staticmethod
    def _hash_file(path: Path, expected_size: int) -> str:
        digest = hashlib.sha256()
        size = 0
        with path.open("rb") as handle:
            while chunk := handle.read(1024 * 1024):
                size += len(chunk)
                if size > expected_size:
                    raise RuntimeLifetimeGuardError(
                        "runtime closure file exceeds its signed size"
                    )
                digest.update(chunk)
        if size != expected_size:
            raise RuntimeLifetimeGuardError(
                "runtime closure file size changed during lifetime locking"
            )
        return digest.hexdigest()

    @classmethod
    def _verify_tree(
        cls,
        root: Path,
        entries: tuple[tuple[str, str, int], ...],
        api: Any,
    ) -> tuple[tuple[Path, ...], tuple[Path, ...]]:
        if not root.is_dir() or root.is_symlink() or api.is_reparse(os.fspath(root)):
            raise RuntimeLifetimeGuardError("runtime closure root is unsafe")
        expected_files = {path for path, _, _ in entries}
        expected_directories: set[str] = set()
        for relative in expected_files:
            parts = PurePosixPath(relative).parts
            for index in range(1, len(parts)):
                expected_directories.add(PurePosixPath(*parts[:index]).as_posix())

        observed_files: set[str] = set()
        observed_directories: set[str] = set()
        for current, directories, files in os.walk(root, topdown=True, followlinks=False):
            directories.sort()
            files.sort()
            current_path = Path(current)
            for name in directories:
                path = current_path / name
                if path.is_symlink() or api.is_reparse(os.fspath(path)):
                    raise RuntimeLifetimeGuardError(
                        "runtime closure contains a linked directory"
                    )
                observed_directories.add(path.relative_to(root).as_posix())
            for name in files:
                path = current_path / name
                if path.is_symlink() or api.is_reparse(os.fspath(path)):
                    raise RuntimeLifetimeGuardError(
                        "runtime closure contains a linked file"
                    )
                if not path.is_file() or path.stat().st_nlink != 1:
                    raise RuntimeLifetimeGuardError(
                        "runtime closure contains a non-file or hardlink"
                    )
                observed_files.add(path.relative_to(root).as_posix())
        if observed_files != expected_files or observed_directories != expected_directories:
            raise RuntimeLifetimeGuardError(
                "runtime closure tree changed before lifetime locking"
            )
        for relative, sha256, size in entries:
            path = root.joinpath(*PurePosixPath(relative).parts)
            if cls._hash_file(path, size) != sha256:
                raise RuntimeLifetimeGuardError(
                    f"runtime closure bytes changed: {relative}"
                )
        directory_paths = (root,) + tuple(
            root.joinpath(*PurePosixPath(relative).parts)
            for relative in sorted(
                expected_directories,
                key=lambda value: (len(PurePosixPath(value).parts), value),
            )
        )
        file_paths = tuple(
            root.joinpath(*PurePosixPath(relative).parts)
            for relative in sorted(expected_files)
        )
        return directory_paths, file_paths

    @classmethod
    def acquire(
        cls,
        policy: RestrictedLaunchPolicy,
        profile: AppContainerProfile,
        *,
        staged_root_relative_path: str,
        files: Sequence[tuple[str, str, int]],
        api: Any | None = None,
    ) -> "WindowsRuntimeClosureLifetimeGuard":
        if not isinstance(policy, RestrictedLaunchPolicy):
            raise RuntimeLifetimeGuardError(
                "runtime guard requires a validated launch policy"
            )
        if not isinstance(profile, AppContainerProfile) or profile.closed:
            raise RuntimeLifetimeGuardError(
                "runtime guard requires an open AppContainer profile"
            )
        if profile.policy != policy:
            raise RuntimeLifetimeGuardError(
                "runtime guard profile and policy do not match"
            )
        native = api or NativeWindowsRuntimeGuardApi()
        relative_root = cls._relative_path(
            staged_root_relative_path, name="runtime guard staged root"
        )
        workspace = Path(policy.workspace_root)
        root = workspace.joinpath(*PurePosixPath(relative_root).parts)
        canonical = Path(os.path.realpath(os.path.abspath(root)))
        try:
            canonical.relative_to(workspace)
        except ValueError as exc:
            raise RuntimeLifetimeGuardError(
                "runtime guard root escaped the workspace"
            ) from exc
        entries = cls._file_entries(files)
        directories, file_paths = cls._verify_tree(canonical, entries, native)

        guarded: list[_GuardedObject] = []
        current_user_storage: ctypes.Array[Any] | None = None
        try:
            for path in (*directories, *file_paths):
                is_directory = path in directories
                handle = native.open_guard_handle(
                    os.fspath(path), is_directory=is_directory
                )
                try:
                    guarded.append(
                        native.snapshot_dacl(
                            os.fspath(path), handle, is_directory=is_directory
                        )
                    )
                except Exception:
                    native.close_handle(handle)
                    raise

            current_user_storage, current_user_sid = native.current_user_sid()
            for item in guarded:
                native.lock_dacl(
                    item,
                    current_user_sid=current_user_sid,
                    appcontainer_sid=profile.sid,
                )
            cls._verify_tree(canonical, entries, native)
            receipt = RuntimeClosureLifetimeReceipt(
                root=os.path.normcase(os.fspath(canonical)),
                appcontainer_sid=profile.sid_string,
                tree_sha256=cls._tree_sha256(entries),
                files_locked=len(file_paths),
                directories_locked=len(directories),
                handles_locked=len(guarded),
            )
            return cls(receipt=receipt, guarded=guarded, api=native)
        except Exception as exc:
            cls._cleanup(guarded, native)
            if isinstance(exc, RuntimeLifetimeGuardError):
                raise
            raise RuntimeLifetimeGuardError(
                "runtime lifetime guard failed closed"
            ) from exc
        finally:
            # Keep the token buffer alive until every ACL has copied its SID.
            current_user_storage = None

    @staticmethod
    def _cleanup(guarded: list[_GuardedObject], api: Any) -> None:
        for item in reversed(guarded):
            if item.locked:
                try:
                    api.restore_dacl(item)
                except Exception:
                    pass
            try:
                api.local_free(item.descriptor)
            except Exception:
                pass
            try:
                api.close_handle(item.handle)
            except Exception:
                pass
        guarded.clear()

    @property
    def closed(self) -> bool:
        return self._closed

    def close(self) -> None:
        if self._closed:
            return
        first_error: Exception | None = None
        for item in reversed(self._guarded):
            if item.locked:
                try:
                    self._api.restore_dacl(item)
                except Exception as exc:
                    if first_error is None:
                        first_error = exc
            try:
                self._api.local_free(item.descriptor)
            except Exception as exc:
                if first_error is None:
                    first_error = exc
            try:
                self._api.close_handle(item.handle)
            except Exception as exc:
                if first_error is None:
                    first_error = exc
        self._guarded.clear()
        self._closed = True
        if first_error is not None:
            raise RuntimeLifetimeGuardError(
                "runtime lifetime guard cleanup failed"
            ) from first_error

    def __enter__(self) -> "WindowsRuntimeClosureLifetimeGuard":
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.close()

    def __del__(self) -> None:  # pragma: no cover
        try:
            self.close()
        except Exception:
            pass
