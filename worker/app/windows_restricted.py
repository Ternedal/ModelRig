"""Windows restricted-token and workspace-SID boundary for Tier-A tools.

Dormant unless a caller explicitly supplies ``RestrictedLaunchPolicy``. The
boundary combines four independent Windows controls:

* ``CreateRestrictedToken(DISABLE_MAX_PRIVILEGE)`` removes privileges;
* the well-known Restricted Code SID keeps the process able to load Windows
  runtime resources intended for restricted code;
* a deterministic workspace-specific restricting SID is granted only on the
  approved workspace tree;
* a private desktop lease grants that same SID only the window-station and
  desktop rights needed for process initialization, then restores both DACLs.

Windows performs the ordinary token access check and a second check against
restricting SIDs, so both must pass. The module never guesses or silently
provisions workspace ACLs during execution. ``provision_workspace_acl`` is a
separate operator action; launch verifies the exact canonical root/SID policy
and otherwise fails closed.
"""
from __future__ import annotations

import contextlib
import ctypes
import hashlib
import os
import pathlib
import secrets
import subprocess
import threading
from dataclasses import dataclass
from typing import Any, Iterator, Mapping, Sequence

from .windows_job import JobLimits, WindowsIsolationError, WindowsJob

RESTRICTED_CODE_SID = "S-1-5-12"
_SID_NAMESPACE = b"kaliv-workspace-restriction/v1\0"
_DESKTOP_LEASE_LOCK = threading.RLock()

DISABLE_MAX_PRIVILEGE = 0x00000001
TOKEN_ASSIGN_PRIMARY = 0x0001
TOKEN_DUPLICATE = 0x0002
TOKEN_QUERY = 0x0008
TOKEN_ADJUST_DEFAULT = 0x0080
TOKEN_ADJUST_SESSIONID = 0x0100
TOKEN_RIGHTS = (
    TOKEN_ASSIGN_PRIMARY
    | TOKEN_DUPLICATE
    | TOKEN_QUERY
    | TOKEN_ADJUST_DEFAULT
    | TOKEN_ADJUST_SESSIONID
)

CREATE_SUSPENDED = 0x00000004
CREATE_UNICODE_ENVIRONMENT = 0x00000400
CREATE_NEW_PROCESS_GROUP = 0x00000200
CREATE_NO_WINDOW = 0x08000000
WAIT_OBJECT_0 = 0x00000000
WAIT_TIMEOUT = 0x00000102
INFINITE = 0xFFFFFFFF
STILL_ACTIVE = 259

SE_FILE_OBJECT = 1
SE_WINDOW_OBJECT = 7
DACL_SECURITY_INFORMATION = 0x00000004
SET_ACCESS = 2
TRUSTEE_IS_SID = 0
TRUSTEE_IS_UNKNOWN = 0
SUB_CONTAINERS_AND_OBJECTS_INHERIT = 0x3
NO_INHERITANCE = 0
FILE_ATTRIBUTE_REPARSE_POINT = 0x00000400
INVALID_FILE_ATTRIBUTES = 0xFFFFFFFF
FILE_GENERIC_READ = 0x00120089
FILE_GENERIC_WRITE = 0x00120116
FILE_GENERIC_EXECUTE = 0x001200A0
DELETE = 0x00010000
WORKSPACE_ACCESS_MASK = (
    FILE_GENERIC_READ | FILE_GENERIC_WRITE | FILE_GENERIC_EXECUTE | DELETE
)

UOI_NAME = 2
READ_CONTROL = 0x00020000
WRITE_DAC = 0x00040000
WINSTA_ENUMDESKTOPS = 0x0001
WINSTA_READATTRIBUTES = 0x0002
WINSTA_ACCESSGLOBALATOMS = 0x0020
WINSTA_ENUMERATE = 0x0100
WINDOW_STATION_CHILD_ACCESS = (
    WINSTA_ENUMDESKTOPS
    | WINSTA_READATTRIBUTES
    | WINSTA_ACCESSGLOBALATOMS
    | WINSTA_ENUMERATE
)
DESKTOP_READOBJECTS = 0x0001
DESKTOP_CREATEWINDOW = 0x0002
DESKTOP_CREATEMENU = 0x0004
DESKTOP_ENUMERATE = 0x0040
DESKTOP_WRITEOBJECTS = 0x0080
DESKTOP_CHILD_ACCESS = (
    DESKTOP_READOBJECTS
    | DESKTOP_CREATEWINDOW
    | DESKTOP_CREATEMENU
    | DESKTOP_ENUMERATE
    | DESKTOP_WRITEOBJECTS
)
DESKTOP_CREATOR_ACCESS = DESKTOP_CHILD_ACCESS | READ_CONTROL | WRITE_DAC
WINDOW_STATION_SECURITY_ACCESS = READ_CONTROL | WRITE_DAC


class RestrictedLaunchError(WindowsIsolationError):
    """The restricted-token or workspace boundary could not be established."""


def _canonical_root(path: os.PathLike[str] | str, *, must_exist: bool = True) -> str:
    raw = os.fspath(path)
    if not raw or not os.path.isabs(raw):
        raise RestrictedLaunchError("workspace root must be an absolute path")
    canonical = os.path.normcase(os.path.realpath(os.path.abspath(raw)))
    if must_exist and not os.path.isdir(canonical):
        raise RestrictedLaunchError("workspace root must be an existing directory")
    return canonical


def derive_workspace_sid(path: os.PathLike[str] | str) -> str:
    """Derive a stable non-account SID from the canonical workspace path."""

    canonical = _canonical_root(path, must_exist=False)
    digest = hashlib.sha256(
        _SID_NAMESPACE + canonical.encode("utf-8", "surrogatepass")
    ).digest()
    parts = [
        int.from_bytes(digest[index : index + 4], "little") or 1
        for index in range(0, 16, 4)
    ]
    return "S-1-5-21-" + "-".join(str(part) for part in parts)


@dataclass(frozen=True, slots=True)
class RestrictedLaunchPolicy:
    """Exact workspace authority used for one restricted child launch."""

    workspace_root: str
    workspace_sid: str | None = None

    def __post_init__(self) -> None:
        root = _canonical_root(self.workspace_root)
        expected = derive_workspace_sid(root)
        sid = self.workspace_sid or expected
        if sid != expected:
            raise RestrictedLaunchError(
                "workspace SID does not match the canonical workspace root"
            )
        object.__setattr__(self, "workspace_root", root)
        object.__setattr__(self, "workspace_sid", sid)

    @property
    def restricting_sids(self) -> tuple[str, str]:
        return (RESTRICTED_CODE_SID, str(self.workspace_sid))


@dataclass(frozen=True, slots=True)
class WorkspaceAclReceipt:
    root: str
    workspace_sid: str
    access_mask: int
    paths_updated: int


class _SID_AND_ATTRIBUTES(ctypes.Structure):
    _fields_ = [("Sid", ctypes.c_void_p), ("Attributes", ctypes.c_uint32)]


class _STARTUPINFOW(ctypes.Structure):
    _fields_ = [
        ("cb", ctypes.c_uint32),
        ("lpReserved", ctypes.c_wchar_p),
        ("lpDesktop", ctypes.c_wchar_p),
        ("lpTitle", ctypes.c_wchar_p),
        ("dwX", ctypes.c_uint32),
        ("dwY", ctypes.c_uint32),
        ("dwXSize", ctypes.c_uint32),
        ("dwYSize", ctypes.c_uint32),
        ("dwXCountChars", ctypes.c_uint32),
        ("dwYCountChars", ctypes.c_uint32),
        ("dwFillAttribute", ctypes.c_uint32),
        ("dwFlags", ctypes.c_uint32),
        ("wShowWindow", ctypes.c_ushort),
        ("cbReserved2", ctypes.c_ushort),
        ("lpReserved2", ctypes.POINTER(ctypes.c_ubyte)),
        ("hStdInput", ctypes.c_void_p),
        ("hStdOutput", ctypes.c_void_p),
        ("hStdError", ctypes.c_void_p),
    ]


class _PROCESS_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("hProcess", ctypes.c_void_p),
        ("hThread", ctypes.c_void_p),
        ("dwProcessId", ctypes.c_uint32),
        ("dwThreadId", ctypes.c_uint32),
    ]


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


class _WindowsSecurityApi:
    """Injectable wrapper around the Win32 calls used by the boundary."""

    def __init__(self) -> None:
        if os.name != "nt":
            raise RestrictedLaunchError("restricted Windows launch requires Windows")
        self.kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self.advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
        self.user32 = ctypes.WinDLL("user32", use_last_error=True)

        kernel32 = self.kernel32
        advapi32 = self.advapi32
        user32 = self.user32

        kernel32.GetCurrentProcess.argtypes = []
        kernel32.GetCurrentProcess.restype = ctypes.c_void_p
        kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
        kernel32.CloseHandle.restype = ctypes.c_int
        kernel32.LocalFree.argtypes = [ctypes.c_void_p]
        kernel32.LocalFree.restype = ctypes.c_void_p
        kernel32.GetExitCodeProcess.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_uint32),
        ]
        kernel32.GetExitCodeProcess.restype = ctypes.c_int
        kernel32.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
        kernel32.WaitForSingleObject.restype = ctypes.c_uint32
        kernel32.TerminateProcess.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
        kernel32.TerminateProcess.restype = ctypes.c_int
        kernel32.GetFileAttributesW.argtypes = [ctypes.c_wchar_p]
        kernel32.GetFileAttributesW.restype = ctypes.c_uint32

        advapi32.OpenProcessToken.argtypes = [
            ctypes.c_void_p,
            ctypes.c_uint32,
            ctypes.POINTER(ctypes.c_void_p),
        ]
        advapi32.OpenProcessToken.restype = ctypes.c_int
        advapi32.CreateRestrictedToken.argtypes = [
            ctypes.c_void_p,
            ctypes.c_uint32,
            ctypes.c_uint32,
            ctypes.POINTER(_SID_AND_ATTRIBUTES),
            ctypes.c_uint32,
            ctypes.c_void_p,
            ctypes.c_uint32,
            ctypes.POINTER(_SID_AND_ATTRIBUTES),
            ctypes.POINTER(ctypes.c_void_p),
        ]
        advapi32.CreateRestrictedToken.restype = ctypes.c_int
        advapi32.IsTokenRestricted.argtypes = [ctypes.c_void_p]
        advapi32.IsTokenRestricted.restype = ctypes.c_int
        advapi32.ConvertStringSidToSidW.argtypes = [
            ctypes.c_wchar_p,
            ctypes.POINTER(ctypes.c_void_p),
        ]
        advapi32.ConvertStringSidToSidW.restype = ctypes.c_int
        advapi32.ImpersonateLoggedOnUser.argtypes = [ctypes.c_void_p]
        advapi32.ImpersonateLoggedOnUser.restype = ctypes.c_int
        advapi32.RevertToSelf.argtypes = []
        advapi32.RevertToSelf.restype = ctypes.c_int
        advapi32.CreateProcessAsUserW.argtypes = [
            ctypes.c_void_p,
            ctypes.c_wchar_p,
            ctypes.c_wchar_p,
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_int,
            ctypes.c_uint32,
            ctypes.c_void_p,
            ctypes.c_wchar_p,
            ctypes.POINTER(_STARTUPINFOW),
            ctypes.POINTER(_PROCESS_INFORMATION),
        ]
        advapi32.CreateProcessAsUserW.restype = ctypes.c_int
        advapi32.GetNamedSecurityInfoW.argtypes = [
            ctypes.c_wchar_p,
            ctypes.c_int,
            ctypes.c_uint32,
            ctypes.POINTER(ctypes.c_void_p),
            ctypes.POINTER(ctypes.c_void_p),
            ctypes.POINTER(ctypes.c_void_p),
            ctypes.POINTER(ctypes.c_void_p),
            ctypes.POINTER(ctypes.c_void_p),
        ]
        advapi32.GetNamedSecurityInfoW.restype = ctypes.c_uint32
        advapi32.SetEntriesInAclW.argtypes = [
            ctypes.c_uint32,
            ctypes.POINTER(_EXPLICIT_ACCESS_W),
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_void_p),
        ]
        advapi32.SetEntriesInAclW.restype = ctypes.c_uint32
        advapi32.SetNamedSecurityInfoW.argtypes = [
            ctypes.c_wchar_p,
            ctypes.c_int,
            ctypes.c_uint32,
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_void_p,
        ]
        advapi32.SetNamedSecurityInfoW.restype = ctypes.c_uint32
        advapi32.GetSecurityInfo.argtypes = [
            ctypes.c_void_p,
            ctypes.c_int,
            ctypes.c_uint32,
            ctypes.POINTER(ctypes.c_void_p),
            ctypes.POINTER(ctypes.c_void_p),
            ctypes.POINTER(ctypes.c_void_p),
            ctypes.POINTER(ctypes.c_void_p),
            ctypes.POINTER(ctypes.c_void_p),
        ]
        advapi32.GetSecurityInfo.restype = ctypes.c_uint32
        advapi32.SetSecurityInfo.argtypes = [
            ctypes.c_void_p,
            ctypes.c_int,
            ctypes.c_uint32,
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_void_p,
        ]
        advapi32.SetSecurityInfo.restype = ctypes.c_uint32

        user32.GetProcessWindowStation.argtypes = []
        user32.GetProcessWindowStation.restype = ctypes.c_void_p
        user32.GetUserObjectInformationW.argtypes = [
            ctypes.c_void_p,
            ctypes.c_int,
            ctypes.c_void_p,
            ctypes.c_uint32,
            ctypes.POINTER(ctypes.c_uint32),
        ]
        user32.GetUserObjectInformationW.restype = ctypes.c_int
        user32.OpenWindowStationW.argtypes = [
            ctypes.c_wchar_p,
            ctypes.c_int,
            ctypes.c_uint32,
        ]
        user32.OpenWindowStationW.restype = ctypes.c_void_p
        user32.CloseWindowStation.argtypes = [ctypes.c_void_p]
        user32.CloseWindowStation.restype = ctypes.c_int
        user32.CreateDesktopW.argtypes = [
            ctypes.c_wchar_p,
            ctypes.c_wchar_p,
            ctypes.c_void_p,
            ctypes.c_uint32,
            ctypes.c_uint32,
            ctypes.c_void_p,
        ]
        user32.CreateDesktopW.restype = ctypes.c_void_p
        user32.CloseDesktop.argtypes = [ctypes.c_void_p]
        user32.CloseDesktop.restype = ctypes.c_int

    @staticmethod
    def error(action: str) -> RestrictedLaunchError:
        return RestrictedLaunchError(
            f"{action} failed with WinError {ctypes.get_last_error()}"
        )

    def close_handle(self, handle: int) -> None:
        if handle and not self.kernel32.CloseHandle(ctypes.c_void_p(handle)):
            raise self.error("CloseHandle")

    def close_window_station(self, handle: int) -> None:
        if handle and not self.user32.CloseWindowStation(ctypes.c_void_p(handle)):
            raise self.error("CloseWindowStation")

    def close_desktop(self, handle: int) -> None:
        if handle and not self.user32.CloseDesktop(ctypes.c_void_p(handle)):
            raise self.error("CloseDesktop")

    def local_free(self, pointer: int | None) -> None:
        if pointer:
            self.kernel32.LocalFree(ctypes.c_void_p(pointer))

    def sid(self, sid_string: str) -> int:
        pointer = ctypes.c_void_p()
        if not self.advapi32.ConvertStringSidToSidW(
            sid_string, ctypes.byref(pointer)
        ):
            raise self.error("ConvertStringSidToSidW")
        return int(pointer.value)

    def is_reparse(self, path: str) -> bool:
        attributes = int(self.kernel32.GetFileAttributesW(path))
        if attributes == INVALID_FILE_ATTRIBUTES:
            raise self.error("GetFileAttributesW")
        return bool(attributes & FILE_ATTRIBUTE_REPARSE_POINT)

    def user_object_name(self, handle: int) -> str:
        needed = ctypes.c_uint32()
        self.user32.GetUserObjectInformationW(
            ctypes.c_void_p(handle), UOI_NAME, None, 0, ctypes.byref(needed)
        )
        if needed.value <= ctypes.sizeof(ctypes.c_wchar):
            raise self.error("GetUserObjectInformationW(size)")
        chars = needed.value // ctypes.sizeof(ctypes.c_wchar) + 1
        buffer = ctypes.create_unicode_buffer(chars)
        if not self.user32.GetUserObjectInformationW(
            ctypes.c_void_p(handle),
            UOI_NAME,
            buffer,
            ctypes.sizeof(buffer),
            ctypes.byref(needed),
        ):
            raise self.error("GetUserObjectInformationW(name)")
        name = buffer.value
        if not name or "\\" in name or "\0" in name:
            raise RestrictedLaunchError("current window-station name is invalid")
        return name

    def open_window_station_security(self, name: str) -> int:
        handle = self.user32.OpenWindowStationW(
            name, 0, WINDOW_STATION_SECURITY_ACCESS
        )
        if not handle:
            raise self.error("OpenWindowStationW")
        return int(handle)

    def create_private_desktop(self, name: str) -> int:
        handle = self.user32.CreateDesktopW(
            name, None, None, 0, DESKTOP_CREATOR_ACCESS, None
        )
        if not handle:
            raise self.error("CreateDesktopW")
        return int(handle)


class RestrictedToken:
    """Own a primary token with removed privileges and restricting SIDs."""

    def __init__(self, policy: RestrictedLaunchPolicy, *, api: Any | None = None) -> None:
        if not isinstance(policy, RestrictedLaunchPolicy):
            raise RestrictedLaunchError("restricted token requires a validated policy")
        self.policy = policy
        self._api = api or _WindowsSecurityApi()
        self._handle: int | None = None
        sid_handles: list[int] = []
        source = ctypes.c_void_p()
        if not self._api.advapi32.OpenProcessToken(
            self._api.kernel32.GetCurrentProcess(), TOKEN_RIGHTS, ctypes.byref(source)
        ):
            raise self._api.error("OpenProcessToken")
        try:
            for value in policy.restricting_sids:
                sid_handles.append(self._api.sid(value))
            array_type = _SID_AND_ATTRIBUTES * len(sid_handles)
            restricted = array_type(
                *(
                    _SID_AND_ATTRIBUTES(ctypes.c_void_p(sid), 0)
                    for sid in sid_handles
                )
            )
            result = ctypes.c_void_p()
            if not self._api.advapi32.CreateRestrictedToken(
                source,
                DISABLE_MAX_PRIVILEGE,
                0,
                None,
                0,
                None,
                len(sid_handles),
                restricted,
                ctypes.byref(result),
            ):
                raise self._api.error("CreateRestrictedToken")
            if not self._api.advapi32.IsTokenRestricted(result):
                self._api.close_handle(int(result.value))
                raise RestrictedLaunchError(
                    "CreateRestrictedToken returned a token without restricting SIDs"
                )
            self._handle = int(result.value)
        finally:
            self._api.close_handle(int(source.value))
            for sid in sid_handles:
                self._api.local_free(sid)

    @property
    def handle(self) -> int:
        if self._handle is None:
            raise RestrictedLaunchError("restricted token is closed")
        return self._handle

    @property
    def closed(self) -> bool:
        return self._handle is None

    def close(self) -> None:
        handle = self._handle
        if handle is None:
            return
        self._api.close_handle(handle)
        self._handle = None

    @contextlib.contextmanager
    def impersonate(self) -> Iterator[None]:
        if not self._api.advapi32.ImpersonateLoggedOnUser(
            ctypes.c_void_p(self.handle)
        ):
            raise self._api.error("ImpersonateLoggedOnUser")
        try:
            yield
        finally:
            if not self._api.advapi32.RevertToSelf():
                raise self._api.error("RevertToSelf")

    def __enter__(self) -> "RestrictedToken":
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.close()

    def __del__(self) -> None:  # pragma: no cover
        try:
            self.close()
        except Exception:
            pass


class _ObjectDaclLease:
    """Keep the original user-object DACL alive and restore it on close."""

    def __init__(
        self,
        *,
        handle: int,
        descriptor: int,
        original_dacl: int,
        api: Any,
    ) -> None:
        self.handle = handle
        self._descriptor = descriptor
        self._original_dacl = original_dacl
        self._api = api

    @property
    def closed(self) -> bool:
        return self._descriptor == 0

    def restore(self) -> None:
        if self._descriptor == 0:
            return
        code = int(
            self._api.advapi32.SetSecurityInfo(
                ctypes.c_void_p(self.handle),
                SE_WINDOW_OBJECT,
                DACL_SECURITY_INFORMATION,
                None,
                None,
                ctypes.c_void_p(self._original_dacl),
                None,
            )
        )
        if code:
            raise RestrictedLaunchError(
                f"SetSecurityInfo(restore DACL) failed with WinError {code}"
            )
        descriptor = self._descriptor
        self._descriptor = 0
        self._original_dacl = 0
        self._api.local_free(descriptor)


def _grant_sid_on_user_object(
    handle: int,
    sid_pointer: int,
    access_mask: int,
    *,
    api: Any,
) -> _ObjectDaclLease:
    old_dacl = ctypes.c_void_p()
    descriptor = ctypes.c_void_p()
    code = int(
        api.advapi32.GetSecurityInfo(
            ctypes.c_void_p(handle),
            SE_WINDOW_OBJECT,
            DACL_SECURITY_INFORMATION,
            None,
            None,
            ctypes.byref(old_dacl),
            None,
            ctypes.byref(descriptor),
        )
    )
    if code:
        raise RestrictedLaunchError(
            f"GetSecurityInfo(user object) failed with WinError {code}"
        )
    new_acl = ctypes.c_void_p()
    try:
        trustee = _TRUSTEE_W(
            None,
            0,
            TRUSTEE_IS_SID,
            TRUSTEE_IS_UNKNOWN,
            ctypes.c_void_p(sid_pointer),
        )
        entry = _EXPLICIT_ACCESS_W(
            access_mask,
            SET_ACCESS,
            NO_INHERITANCE,
            trustee,
        )
        code = int(
            api.advapi32.SetEntriesInAclW(
                1, ctypes.byref(entry), old_dacl, ctypes.byref(new_acl)
            )
        )
        if code:
            raise RestrictedLaunchError(
                f"SetEntriesInAclW(user object) failed with WinError {code}"
            )
        code = int(
            api.advapi32.SetSecurityInfo(
                ctypes.c_void_p(handle),
                SE_WINDOW_OBJECT,
                DACL_SECURITY_INFORMATION,
                None,
                None,
                new_acl,
                None,
            )
        )
        if code:
            raise RestrictedLaunchError(
                f"SetSecurityInfo(user object) failed with WinError {code}"
            )
        return _ObjectDaclLease(
            handle=handle,
            descriptor=int(descriptor.value),
            original_dacl=int(old_dacl.value or 0),
            api=api,
        )
    except Exception:
        api.local_free(int(descriptor.value) if descriptor.value else None)
        raise
    finally:
        api.local_free(int(new_acl.value) if new_acl.value else None)


class RestrictedDesktopLease:
    """Private desktop plus temporary, serialized window-station DACL grant.

    Modifying the process window station is shared state. A process-wide lock is
    therefore held for the whole child lifetime, making restoration race-free
    and intentionally serializing this first Tier-A launch substrate.
    """

    def __init__(
        self,
        policy: RestrictedLaunchPolicy,
        *,
        api: Any | None = None,
    ) -> None:
        if not isinstance(policy, RestrictedLaunchPolicy):
            raise RestrictedLaunchError("desktop lease requires a validated policy")
        self._api = api or _WindowsSecurityApi()
        self._lock_held = False
        self._sid_pointer = 0
        self._station_handle = 0
        self._desktop_handle = 0
        self._station_dacl: _ObjectDaclLease | None = None
        self._desktop_dacl: _ObjectDaclLease | None = None
        self.full_name = ""

        _DESKTOP_LEASE_LOCK.acquire()
        self._lock_held = True
        try:
            current_station = self._api.user32.GetProcessWindowStation()
            if not current_station:
                raise self._api.error("GetProcessWindowStation")
            station_name = self._api.user_object_name(int(current_station))
            self._station_handle = self._api.open_window_station_security(
                station_name
            )
            self._sid_pointer = self._api.sid(str(policy.workspace_sid))
            self._station_dacl = _grant_sid_on_user_object(
                self._station_handle,
                self._sid_pointer,
                WINDOW_STATION_CHILD_ACCESS,
                api=self._api,
            )

            desktop_name = (
                f"KalivRestricted-{os.getpid()}-{secrets.token_hex(12)}"
            )
            self._desktop_handle = self._api.create_private_desktop(desktop_name)
            self._desktop_dacl = _grant_sid_on_user_object(
                self._desktop_handle,
                self._sid_pointer,
                DESKTOP_CHILD_ACCESS,
                api=self._api,
            )
            self.full_name = f"{station_name}\\{desktop_name}"
        except Exception:
            try:
                self.close()
            except Exception:
                pass
            raise

    @property
    def closed(self) -> bool:
        return not self._lock_held

    def close(self) -> None:
        if not self._lock_held:
            return
        if self._desktop_dacl is not None:
            self._desktop_dacl.restore()
            self._desktop_dacl = None
        if self._desktop_handle:
            handle = self._desktop_handle
            self._api.close_desktop(handle)
            self._desktop_handle = 0
        if self._station_dacl is not None:
            self._station_dacl.restore()
            self._station_dacl = None
        if self._station_handle:
            handle = self._station_handle
            self._api.close_window_station(handle)
            self._station_handle = 0
        if self._sid_pointer:
            pointer = self._sid_pointer
            self._sid_pointer = 0
            self._api.local_free(pointer)
        self.full_name = ""
        self._lock_held = False
        _DESKTOP_LEASE_LOCK.release()

    def __enter__(self) -> "RestrictedDesktopLease":
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.close()

    def __del__(self) -> None:  # pragma: no cover
        try:
            self.close()
        except Exception:
            pass


def _workspace_paths(root: str, api: Any) -> list[str]:
    paths = [root]
    for current, directories, files in os.walk(root, topdown=True, followlinks=False):
        directories.sort()
        files.sort()
        for name in directories + files:
            candidate = os.path.join(current, name)
            if os.path.islink(candidate) or api.is_reparse(candidate):
                raise RestrictedLaunchError(
                    f"workspace ACL provisioning refuses reparse points: {candidate}"
                )
            paths.append(candidate)
    return paths


def _apply_sid_ace(
    path: str,
    sid_pointer: int,
    *,
    is_directory: bool,
    api: Any,
) -> None:
    old_dacl = ctypes.c_void_p()
    descriptor = ctypes.c_void_p()
    code = int(
        api.advapi32.GetNamedSecurityInfoW(
            path,
            SE_FILE_OBJECT,
            DACL_SECURITY_INFORMATION,
            None,
            None,
            ctypes.byref(old_dacl),
            None,
            ctypes.byref(descriptor),
        )
    )
    if code:
        raise RestrictedLaunchError(
            f"GetNamedSecurityInfoW failed with WinError {code}"
        )
    new_acl = ctypes.c_void_p()
    try:
        trustee = _TRUSTEE_W(
            None,
            0,
            TRUSTEE_IS_SID,
            TRUSTEE_IS_UNKNOWN,
            ctypes.c_void_p(sid_pointer),
        )
        entry = _EXPLICIT_ACCESS_W(
            WORKSPACE_ACCESS_MASK,
            SET_ACCESS,
            SUB_CONTAINERS_AND_OBJECTS_INHERIT if is_directory else NO_INHERITANCE,
            trustee,
        )
        code = int(
            api.advapi32.SetEntriesInAclW(
                1, ctypes.byref(entry), old_dacl, ctypes.byref(new_acl)
            )
        )
        if code:
            raise RestrictedLaunchError(
                f"SetEntriesInAclW failed with WinError {code}"
            )
        code = int(
            api.advapi32.SetNamedSecurityInfoW(
                path,
                SE_FILE_OBJECT,
                DACL_SECURITY_INFORMATION,
                None,
                None,
                new_acl,
                None,
            )
        )
        if code:
            raise RestrictedLaunchError(
                f"SetNamedSecurityInfoW failed with WinError {code}"
            )
    finally:
        api.local_free(int(new_acl.value) if new_acl.value else None)
        api.local_free(int(descriptor.value) if descriptor.value else None)


def provision_workspace_acl(
    root: os.PathLike[str] | str,
    *,
    api: Any | None = None,
) -> WorkspaceAclReceipt:
    """Grant only the deterministic restricting SID on a reparse-free tree."""

    native = api or _WindowsSecurityApi()
    canonical = _canonical_root(root)
    if os.path.islink(canonical) or native.is_reparse(canonical):
        raise RestrictedLaunchError("workspace root must not be a reparse point")
    paths = _workspace_paths(canonical, native)
    sid_string = derive_workspace_sid(canonical)
    sid_pointer = native.sid(sid_string)
    try:
        for path in paths:
            if os.path.islink(path) or native.is_reparse(path):
                raise RestrictedLaunchError(
                    f"workspace changed to a reparse point during provisioning: {path}"
                )
            _apply_sid_ace(
                path,
                sid_pointer,
                is_directory=os.path.isdir(path),
                api=native,
            )
    finally:
        native.local_free(sid_pointer)
    return WorkspaceAclReceipt(
        root=canonical,
        workspace_sid=sid_string,
        access_mask=WORKSPACE_ACCESS_MASK,
        paths_updated=len(paths),
    )


def _environment_block(env: Mapping[str, str]) -> ctypes.Array[Any]:
    items: list[str] = []
    for key, value in sorted(env.items(), key=lambda item: item[0].upper()):
        if not isinstance(key, str) or not key or "=" in key or "\0" in key:
            raise RestrictedLaunchError("child environment contains an invalid key")
        if not isinstance(value, str) or "\0" in value:
            raise RestrictedLaunchError("child environment contains an invalid value")
        items.append(f"{key}={value}")
    return ctypes.create_unicode_buffer("\0".join(items) + "\0\0")


class RestrictedWindowsProcess:
    """Own a child process and its private desktop lease."""

    def __init__(
        self,
        *,
        process_handle: int,
        thread_handle: int,
        pid: int,
        args: Sequence[str],
        api: Any,
        desktop_lease: RestrictedDesktopLease,
    ) -> None:
        self._handle = process_handle
        self._thread_handle = thread_handle
        self.pid = pid
        self.args = list(args)
        self.returncode: int | None = None
        self._api = api
        self._desktop_lease: RestrictedDesktopLease | None = desktop_lease

    def close_thread_handle(self) -> None:
        handle = self._thread_handle
        if not handle:
            return
        self._api.close_handle(handle)
        self._thread_handle = 0

    def poll(self) -> int | None:
        if self.returncode is not None:
            return self.returncode
        if not self._handle:
            return self.returncode
        result = int(
            self._api.kernel32.WaitForSingleObject(
                ctypes.c_void_p(self._handle), 0
            )
        )
        if result == WAIT_TIMEOUT:
            return None
        if result != WAIT_OBJECT_0:
            raise self._api.error("WaitForSingleObject")
        code = ctypes.c_uint32()
        if not self._api.kernel32.GetExitCodeProcess(
            ctypes.c_void_p(self._handle), ctypes.byref(code)
        ):
            raise self._api.error("GetExitCodeProcess")
        if code.value == STILL_ACTIVE:
            return None
        self.returncode = int(code.value)
        return self.returncode

    def wait(self, timeout: float | None = None) -> int:
        if self.returncode is not None:
            return self.returncode
        milliseconds = INFINITE if timeout is None else max(0, int(timeout * 1000))
        result = int(
            self._api.kernel32.WaitForSingleObject(
                ctypes.c_void_p(self._handle), milliseconds
            )
        )
        if result == WAIT_TIMEOUT:
            raise subprocess.TimeoutExpired(self.args, timeout)
        if result != WAIT_OBJECT_0:
            raise self._api.error("WaitForSingleObject")
        return_code = self.poll()
        if return_code is None:
            raise RestrictedLaunchError("process signaled without an exit code")
        return return_code

    def kill(self) -> None:
        if self.poll() is not None:
            return
        if not self._api.kernel32.TerminateProcess(
            ctypes.c_void_p(self._handle), ctypes.c_uint32(1)
        ):
            raise self._api.error("TerminateProcess")

    def close(self) -> None:
        if self._handle and self.poll() is None:
            raise RestrictedLaunchError("cannot close a running restricted process")
        self.close_thread_handle()
        if self._handle:
            handle = self._handle
            self._api.close_handle(handle)
            self._handle = 0
        if self._desktop_lease is not None:
            lease = self._desktop_lease
            lease.close()
            self._desktop_lease = None

    def __del__(self) -> None:  # pragma: no cover
        try:
            if self._handle and self.poll() is None:
                self.kill()
                self.wait(timeout=5)
            self.close()
        except Exception:
            pass


def spawn_restricted_in_job(
    command: Sequence[str],
    *,
    env: Mapping[str, str],
    limits: JobLimits,
    policy: RestrictedLaunchPolicy,
    api: Any | None = None,
    creationflags: int = 0,
) -> RestrictedWindowsProcess:
    """Create a restricted child on a private desktop, then assign and resume."""

    if isinstance(creationflags, bool) or not isinstance(creationflags, int):
        raise RestrictedLaunchError("restricted launch creation flags are invalid")
    if creationflags != 0:
        raise RestrictedLaunchError(
            "restricted launch does not accept caller creation flags"
        )
    if os.name != "nt" and api is None:
        raise RestrictedLaunchError("restricted Windows launch requires Windows")
    if not command or not all(
        isinstance(part, str) and part and "\0" not in part for part in command
    ):
        raise RestrictedLaunchError(
            "restricted child command must be non-empty NUL-free strings"
        )
    executable = os.path.normcase(os.path.realpath(os.path.abspath(command[0])))
    if not os.path.isfile(executable) or os.path.islink(executable):
        raise RestrictedLaunchError(
            "restricted child executable must be a regular file"
        )
    root = pathlib.Path(policy.workspace_root)
    try:
        pathlib.Path(executable).relative_to(root)
    except ValueError as exc:
        raise RestrictedLaunchError(
            "restricted child executable must live inside the provisioned workspace"
        ) from exc

    native = api or _WindowsSecurityApi()
    if native.is_reparse(policy.workspace_root) or native.is_reparse(executable):
        raise RestrictedLaunchError(
            "restricted launch refuses reparse-point roots/executables"
        )

    process: RestrictedWindowsProcess | None = None
    token: RestrictedToken | None = None
    desktop: RestrictedDesktopLease | None = None
    job: WindowsJob | None = None
    try:
        token = RestrictedToken(policy, api=native)
        desktop = RestrictedDesktopLease(policy, api=native)
        startup = _STARTUPINFOW()
        startup.cb = ctypes.sizeof(_STARTUPINFOW)
        startup.lpDesktop = desktop.full_name
        command_line = ctypes.create_unicode_buffer(
            subprocess.list2cmdline(list(command))
        )
        environment = _environment_block(env)
        info = _PROCESS_INFORMATION()
        flags = (
            CREATE_SUSPENDED
            | CREATE_NEW_PROCESS_GROUP
            | CREATE_NO_WINDOW
            | CREATE_UNICODE_ENVIRONMENT
        )
        if not native.advapi32.CreateProcessAsUserW(
            ctypes.c_void_p(token.handle),
            executable,
            command_line,
            None,
            None,
            0,
            flags,
            ctypes.cast(environment, ctypes.c_void_p),
            policy.workspace_root,
            ctypes.byref(startup),
            ctypes.byref(info),
        ):
            raise native.error("CreateProcessAsUserW")
        process = RestrictedWindowsProcess(
            process_handle=int(info.hProcess),
            thread_handle=int(info.hThread),
            pid=int(info.dwProcessId),
            args=command,
            api=native,
            desktop_lease=desktop,
        )
        desktop = None
        job = WindowsJob(limits)
        job.assign_and_resume(process)
        process.close_thread_handle()
        setattr(process, "_kaliv_windows_job", job)
        job = None
        return process
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
        if process is not None:
            try:
                process.kill()
            except Exception:
                pass
            try:
                process.wait(timeout=5)
            except Exception:
                pass
            try:
                process.close()
            except Exception:
                pass
        elif desktop is not None:
            try:
                desktop.close()
            except Exception:
                pass
        raise
    finally:
        if token is not None:
            token.close()
