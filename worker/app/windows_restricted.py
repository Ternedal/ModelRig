"""Windows AppContainer workspace boundary for dormant Tier-A tools.

A hand-built ``CreateRestrictedToken`` restricting-SID list could enforce the
workspace, but it also blocked the Windows loader before the child reached its
entry point. Adding ordinary user/group SIDs would make the loader work by
reopening the same outside files the boundary exists to deny.

AppContainer is Windows' native dual-principal sandbox: normal user/group
access and the AppContainer package SID must both authorize a protected
resource. Regular AppContainers retain the system runtime resources Windows
marks for packaged applications, while a workspace is reachable only after an
explicit package-SID ACE. No network capability is supplied.

This module remains dormant. It does not provision ACLs implicitly and no
registered ModelRig tool invokes it. The operator must create/resolve the
profile, provision the exact workspace tree, retain the receipt, and pass all
three objects to ``spawn_restricted_in_job``. The child is still created
suspended and assigned to the existing Job Object before it runs.
"""
from __future__ import annotations

import ctypes
import hashlib
import os
import pathlib
import re
import subprocess
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from .windows_job import JobLimits, WindowsIsolationError, WindowsJob

S_OK = 0
HRESULT_ALREADY_EXISTS = 0x800700B7
ERROR_INSUFFICIENT_BUFFER = 122

CREATE_SUSPENDED = 0x00000004
CREATE_UNICODE_ENVIRONMENT = 0x00000400
CREATE_NEW_PROCESS_GROUP = 0x00000200
EXTENDED_STARTUPINFO_PRESENT = 0x00080000
CREATE_NO_WINDOW = 0x08000000
PROC_THREAD_ATTRIBUTE_SECURITY_CAPABILITIES = 0x00020009

WAIT_OBJECT_0 = 0x00000000
WAIT_TIMEOUT = 0x00000102
INFINITE = 0xFFFFFFFF
STILL_ACTIVE = 259

SE_FILE_OBJECT = 1
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

_PROFILE_NAMESPACE = b"kaliv-appcontainer-workspace/v1\0"
_PROFILE_PATTERN = re.compile(r"[-_. A-Za-z0-9]{1,64}\Z")


class RestrictedLaunchError(WindowsIsolationError):
    """The AppContainer or workspace boundary could not be established."""


def _canonical_root(path: os.PathLike[str] | str, *, must_exist: bool = True) -> str:
    raw = os.fspath(path)
    if not raw or not os.path.isabs(raw):
        raise RestrictedLaunchError("workspace root must be an absolute path")
    canonical = os.path.normcase(os.path.realpath(os.path.abspath(raw)))
    if must_exist and not os.path.isdir(canonical):
        raise RestrictedLaunchError("workspace root must be an existing directory")
    return canonical


def derive_profile_name(path: os.PathLike[str] | str) -> str:
    """Return one deterministic AppContainer moniker for one canonical root."""

    canonical = _canonical_root(path, must_exist=False)
    digest = hashlib.sha256(
        _PROFILE_NAMESPACE + canonical.encode("utf-8", "surrogatepass")
    ).hexdigest()[:24]
    return f"Kaliv.ModelRig.{digest}"


@dataclass(frozen=True, slots=True)
class RestrictedLaunchPolicy:
    """Exact AppContainer identity and workspace authority for one launch."""

    workspace_root: str
    profile_name: str | None = None

    def __post_init__(self) -> None:
        root = _canonical_root(self.workspace_root)
        expected = derive_profile_name(root)
        profile = self.profile_name or expected
        if profile != expected:
            raise RestrictedLaunchError(
                "AppContainer profile name does not match the canonical workspace root"
            )
        if not _PROFILE_PATTERN.fullmatch(profile):
            raise RestrictedLaunchError("AppContainer profile name is invalid")
        object.__setattr__(self, "workspace_root", root)
        object.__setattr__(self, "profile_name", profile)


@dataclass(frozen=True, slots=True)
class WorkspaceAclReceipt:
    root: str
    profile_name: str
    appcontainer_sid: str
    access_mask: int
    paths_updated: int
    capability_count: int = 0


class _SID_AND_ATTRIBUTES(ctypes.Structure):
    _fields_ = [("Sid", ctypes.c_void_p), ("Attributes", ctypes.c_uint32)]


class _SECURITY_CAPABILITIES(ctypes.Structure):
    _fields_ = [
        ("AppContainerSid", ctypes.c_void_p),
        ("Capabilities", ctypes.POINTER(_SID_AND_ATTRIBUTES)),
        ("CapabilityCount", ctypes.c_uint32),
        ("Reserved", ctypes.c_uint32),
    ]


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


class _STARTUPINFOEXW(ctypes.Structure):
    _fields_ = [
        ("StartupInfo", _STARTUPINFOW),
        ("lpAttributeList", ctypes.c_void_p),
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


class _WindowsAppContainerApi:
    """Small Win32 wrapper kept injectable for contract testing."""

    def __init__(self) -> None:
        if os.name != "nt":
            raise RestrictedLaunchError("AppContainer launch requires Windows")
        self.kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self.advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
        self.userenv = ctypes.WinDLL("userenv", use_last_error=True)

        k32 = self.kernel32
        advapi = self.advapi32
        userenv = self.userenv

        k32.CloseHandle.argtypes = [ctypes.c_void_p]
        k32.CloseHandle.restype = ctypes.c_int
        k32.LocalFree.argtypes = [ctypes.c_void_p]
        k32.LocalFree.restype = ctypes.c_void_p
        k32.GetFileAttributesW.argtypes = [ctypes.c_wchar_p]
        k32.GetFileAttributesW.restype = ctypes.c_uint32
        k32.GetExitCodeProcess.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_uint32),
        ]
        k32.GetExitCodeProcess.restype = ctypes.c_int
        k32.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
        k32.WaitForSingleObject.restype = ctypes.c_uint32
        k32.TerminateProcess.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
        k32.TerminateProcess.restype = ctypes.c_int
        k32.InitializeProcThreadAttributeList.argtypes = [
            ctypes.c_void_p,
            ctypes.c_size_t,
            ctypes.c_uint32,
            ctypes.POINTER(ctypes.c_size_t),
        ]
        k32.InitializeProcThreadAttributeList.restype = ctypes.c_int
        k32.UpdateProcThreadAttribute.argtypes = [
            ctypes.c_void_p,
            ctypes.c_uint32,
            ctypes.c_size_t,
            ctypes.c_void_p,
            ctypes.c_size_t,
            ctypes.c_void_p,
            ctypes.c_void_p,
        ]
        k32.UpdateProcThreadAttribute.restype = ctypes.c_int
        k32.DeleteProcThreadAttributeList.argtypes = [ctypes.c_void_p]
        k32.DeleteProcThreadAttributeList.restype = None
        k32.CreateProcessW.argtypes = [
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
        k32.CreateProcessW.restype = ctypes.c_int

        advapi.FreeSid.argtypes = [ctypes.c_void_p]
        advapi.FreeSid.restype = ctypes.c_void_p
        advapi.ConvertSidToStringSidW.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_wchar_p),
        ]
        advapi.ConvertSidToStringSidW.restype = ctypes.c_int
        advapi.GetNamedSecurityInfoW.argtypes = [
            ctypes.c_wchar_p,
            ctypes.c_int,
            ctypes.c_uint32,
            ctypes.POINTER(ctypes.c_void_p),
            ctypes.POINTER(ctypes.c_void_p),
            ctypes.POINTER(ctypes.c_void_p),
            ctypes.POINTER(ctypes.c_void_p),
            ctypes.POINTER(ctypes.c_void_p),
        ]
        advapi.GetNamedSecurityInfoW.restype = ctypes.c_uint32
        advapi.SetEntriesInAclW.argtypes = [
            ctypes.c_uint32,
            ctypes.POINTER(_EXPLICIT_ACCESS_W),
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_void_p),
        ]
        advapi.SetEntriesInAclW.restype = ctypes.c_uint32
        advapi.SetNamedSecurityInfoW.argtypes = [
            ctypes.c_wchar_p,
            ctypes.c_int,
            ctypes.c_uint32,
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_void_p,
        ]
        advapi.SetNamedSecurityInfoW.restype = ctypes.c_uint32

        userenv.CreateAppContainerProfile.argtypes = [
            ctypes.c_wchar_p,
            ctypes.c_wchar_p,
            ctypes.c_wchar_p,
            ctypes.POINTER(_SID_AND_ATTRIBUTES),
            ctypes.c_uint32,
            ctypes.POINTER(ctypes.c_void_p),
        ]
        userenv.CreateAppContainerProfile.restype = ctypes.c_long
        userenv.DeriveAppContainerSidFromAppContainerName.argtypes = [
            ctypes.c_wchar_p,
            ctypes.POINTER(ctypes.c_void_p),
        ]
        userenv.DeriveAppContainerSidFromAppContainerName.restype = ctypes.c_long
        userenv.DeleteAppContainerProfile.argtypes = [ctypes.c_wchar_p]
        userenv.DeleteAppContainerProfile.restype = ctypes.c_long

    @staticmethod
    def win_error(action: str) -> RestrictedLaunchError:
        return RestrictedLaunchError(
            f"{action} failed with WinError {ctypes.get_last_error()}"
        )

    @staticmethod
    def hresult_error(action: str, result: int) -> RestrictedLaunchError:
        return RestrictedLaunchError(
            f"{action} failed with HRESULT 0x{result & 0xFFFFFFFF:08x}"
        )

    def close_handle(self, handle: int) -> None:
        if handle and not self.kernel32.CloseHandle(ctypes.c_void_p(handle)):
            raise self.win_error("CloseHandle")

    def free_sid(self, sid: int) -> None:
        if sid:
            self.advapi32.FreeSid(ctypes.c_void_p(sid))

    def local_free(self, pointer: int | None) -> None:
        if pointer:
            self.kernel32.LocalFree(ctypes.c_void_p(pointer))

    def sid_string(self, sid: int) -> str:
        output = ctypes.c_wchar_p()
        if not self.advapi32.ConvertSidToStringSidW(
            ctypes.c_void_p(sid), ctypes.byref(output)
        ):
            raise self.win_error("ConvertSidToStringSidW")
        try:
            value = output.value or ""
            if not value.startswith("S-"):
                raise RestrictedLaunchError("AppContainer returned an invalid SID")
            return value
        finally:
            self.local_free(ctypes.cast(output, ctypes.c_void_p).value)

    def is_reparse(self, path: str) -> bool:
        attributes = int(self.kernel32.GetFileAttributesW(path))
        if attributes == INVALID_FILE_ATTRIBUTES:
            raise self.win_error("GetFileAttributesW")
        return bool(attributes & FILE_ATTRIBUTE_REPARSE_POINT)


class AppContainerProfile:
    """Own the Package SID buffer for one deterministic AppContainer profile."""

    def __init__(
        self,
        policy: RestrictedLaunchPolicy,
        *,
        api: Any | None = None,
    ) -> None:
        if not isinstance(policy, RestrictedLaunchPolicy):
            raise RestrictedLaunchError("profile requires a validated policy")
        self.policy = policy
        self._api = api or _WindowsAppContainerApi()
        self._sid: int | None = None
        self.created = False
        self.deleted = False

        result_sid = ctypes.c_void_p()
        result = int(
            self._api.userenv.CreateAppContainerProfile(
                policy.profile_name,
                "Kaliv ModelRig isolated tool",
                "Dormant Tier-A workspace sandbox",
                None,
                0,
                ctypes.byref(result_sid),
            )
        )
        code = result & 0xFFFFFFFF
        if code == S_OK:
            self.created = True
        elif code == HRESULT_ALREADY_EXISTS:
            result = int(
                self._api.userenv.DeriveAppContainerSidFromAppContainerName(
                    policy.profile_name, ctypes.byref(result_sid)
                )
            )
            if (result & 0xFFFFFFFF) != S_OK:
                raise self._api.hresult_error(
                    "DeriveAppContainerSidFromAppContainerName", result
                )
        else:
            raise self._api.hresult_error("CreateAppContainerProfile", result)
        if not result_sid.value:
            raise RestrictedLaunchError("AppContainer profile returned no SID")
        self._sid = int(result_sid.value)
        self.sid_string = self._api.sid_string(self._sid)

    @property
    def sid(self) -> int:
        if self._sid is None:
            raise RestrictedLaunchError("AppContainer profile SID is closed")
        return self._sid

    @property
    def closed(self) -> bool:
        return self._sid is None

    def close(self) -> None:
        sid = self._sid
        if sid is None:
            return
        self._api.free_sid(sid)
        self._sid = None

    def delete(self) -> None:
        if self.deleted:
            return
        result = int(
            self._api.userenv.DeleteAppContainerProfile(self.policy.profile_name)
        )
        if (result & 0xFFFFFFFF) != S_OK:
            raise self._api.hresult_error("DeleteAppContainerProfile", result)
        self.deleted = True
        self.close()

    def __enter__(self) -> "AppContainerProfile":
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
    policy: RestrictedLaunchPolicy,
    profile: AppContainerProfile,
    *,
    api: Any | None = None,
) -> WorkspaceAclReceipt:
    """Grant the exact Package SID on a reparse-free workspace tree."""

    if not isinstance(policy, RestrictedLaunchPolicy):
        raise RestrictedLaunchError("ACL provisioning requires a validated policy")
    if not isinstance(profile, AppContainerProfile) or profile.closed:
        raise RestrictedLaunchError("ACL provisioning requires an open profile")
    if profile.policy != policy:
        raise RestrictedLaunchError("profile and ACL policy do not match")
    native = api or profile._api
    root = policy.workspace_root
    if os.path.islink(root) or native.is_reparse(root):
        raise RestrictedLaunchError("workspace root must not be a reparse point")
    paths = _workspace_paths(root, native)
    for path in paths:
        if os.path.islink(path) or native.is_reparse(path):
            raise RestrictedLaunchError(
                f"workspace changed to a reparse point during provisioning: {path}"
            )
        _apply_sid_ace(
            path,
            profile.sid,
            is_directory=os.path.isdir(path),
            api=native,
        )
    return WorkspaceAclReceipt(
        root=root,
        profile_name=policy.profile_name,
        appcontainer_sid=profile.sid_string,
        access_mask=WORKSPACE_ACCESS_MASK,
        paths_updated=len(paths),
        capability_count=0,
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


class AppContainerProcess:
    """Minimal process owner for a child created with security capabilities."""

    def __init__(
        self,
        *,
        process_handle: int,
        thread_handle: int,
        pid: int,
        args: Sequence[str],
        profile_name: str,
        api: Any,
    ) -> None:
        self._handle = process_handle
        self._thread_handle = thread_handle
        self.pid = pid
        self.args = list(args)
        self.profile_name = profile_name
        self.returncode: int | None = None
        self._api = api

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
            raise self._api.win_error("WaitForSingleObject")
        code = ctypes.c_uint32()
        if not self._api.kernel32.GetExitCodeProcess(
            ctypes.c_void_p(self._handle), ctypes.byref(code)
        ):
            raise self._api.win_error("GetExitCodeProcess")
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
            raise self._api.win_error("WaitForSingleObject")
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
            raise self._api.win_error("TerminateProcess")

    def close(self) -> None:
        if self._handle and self.poll() is None:
            raise RestrictedLaunchError("cannot close a running AppContainer process")
        self.close_thread_handle()
        if self._handle:
            handle = self._handle
            self._api.close_handle(handle)
            self._handle = 0

    def __del__(self) -> None:  # pragma: no cover
        try:
            if self._handle and self.poll() is None:
                self.kill()
                self.wait(timeout=5)
            self.close()
        except Exception:
            pass


def _attribute_list(api: Any, capabilities: _SECURITY_CAPABILITIES):
    size = ctypes.c_size_t()
    if api.kernel32.InitializeProcThreadAttributeList(
        None, 1, 0, ctypes.byref(size)
    ):
        raise RestrictedLaunchError(
            "InitializeProcThreadAttributeList unexpectedly accepted a NULL buffer"
        )
    if ctypes.get_last_error() != ERROR_INSUFFICIENT_BUFFER or not size.value:
        raise api.win_error("InitializeProcThreadAttributeList(size)")
    storage = ctypes.create_string_buffer(size.value)
    pointer = ctypes.cast(storage, ctypes.c_void_p)
    if not api.kernel32.InitializeProcThreadAttributeList(
        pointer, 1, 0, ctypes.byref(size)
    ):
        raise api.win_error("InitializeProcThreadAttributeList")
    try:
        if not api.kernel32.UpdateProcThreadAttribute(
            pointer,
            0,
            PROC_THREAD_ATTRIBUTE_SECURITY_CAPABILITIES,
            ctypes.byref(capabilities),
            ctypes.sizeof(capabilities),
            None,
            None,
        ):
            raise api.win_error("UpdateProcThreadAttribute(security capabilities)")
        return storage, pointer
    except Exception:
        api.kernel32.DeleteProcThreadAttributeList(pointer)
        raise


def spawn_restricted_in_job(
    command: Sequence[str],
    *,
    env: Mapping[str, str],
    limits: JobLimits,
    policy: RestrictedLaunchPolicy,
    profile: AppContainerProfile,
    acl_receipt: WorkspaceAclReceipt,
    api: Any | None = None,
    creationflags: int = 0,
) -> AppContainerProcess:
    """Create an AppContainer child suspended, assign its Job Object, then run."""

    if isinstance(creationflags, bool) or not isinstance(creationflags, int):
        raise RestrictedLaunchError("AppContainer creation flags are invalid")
    if creationflags != 0:
        raise RestrictedLaunchError("AppContainer launch accepts no caller flags")
    if os.name != "nt" and api is None:
        raise RestrictedLaunchError("AppContainer launch requires Windows")
    if not command or not all(
        isinstance(part, str) and part and "\0" not in part for part in command
    ):
        raise RestrictedLaunchError(
            "AppContainer child command must be non-empty NUL-free strings"
        )
    if not isinstance(profile, AppContainerProfile) or profile.closed:
        raise RestrictedLaunchError("AppContainer launch requires an open profile")
    if profile.policy != policy:
        raise RestrictedLaunchError("profile and launch policy do not match")
    if not isinstance(acl_receipt, WorkspaceAclReceipt):
        raise RestrictedLaunchError("AppContainer launch requires an ACL receipt")
    expected_receipt = (
        policy.workspace_root,
        policy.profile_name,
        profile.sid_string,
        WORKSPACE_ACCESS_MASK,
        0,
    )
    received_receipt = (
        acl_receipt.root,
        acl_receipt.profile_name,
        acl_receipt.appcontainer_sid,
        acl_receipt.access_mask,
        acl_receipt.capability_count,
    )
    if received_receipt != expected_receipt or acl_receipt.paths_updated < 1:
        raise RestrictedLaunchError(
            "ACL receipt is not bound to the exact no-capability AppContainer"
        )

    executable = os.path.normcase(os.path.realpath(os.path.abspath(command[0])))
    if not os.path.isfile(executable) or os.path.islink(executable):
        raise RestrictedLaunchError(
            "AppContainer child executable must be a regular file"
        )
    try:
        pathlib.Path(executable).relative_to(pathlib.Path(policy.workspace_root))
    except ValueError as exc:
        raise RestrictedLaunchError(
            "AppContainer child executable must live inside the workspace"
        ) from exc

    native = api or profile._api
    if native.is_reparse(policy.workspace_root) or native.is_reparse(executable):
        raise RestrictedLaunchError(
            "AppContainer launch refuses reparse-point roots/executables"
        )

    capabilities = _SECURITY_CAPABILITIES(
        ctypes.c_void_p(profile.sid),
        None,
        0,
        0,
    )
    storage = pointer = None
    process: AppContainerProcess | None = None
    job: WindowsJob | None = None
    try:
        storage, pointer = _attribute_list(native, capabilities)
        startup = _STARTUPINFOEXW()
        startup.StartupInfo.cb = ctypes.sizeof(_STARTUPINFOEXW)
        startup.lpAttributeList = pointer
        info = _PROCESS_INFORMATION()
        command_line = ctypes.create_unicode_buffer(
            subprocess.list2cmdline(list(command))
        )
        environment = _environment_block(env)
        flags = (
            CREATE_SUSPENDED
            | CREATE_NEW_PROCESS_GROUP
            | CREATE_NO_WINDOW
            | CREATE_UNICODE_ENVIRONMENT
            | EXTENDED_STARTUPINFO_PRESENT
        )
        if not native.kernel32.CreateProcessW(
            executable,
            command_line,
            None,
            None,
            0,
            flags,
            ctypes.cast(environment, ctypes.c_void_p),
            policy.workspace_root,
            ctypes.byref(startup.StartupInfo),
            ctypes.byref(info),
        ):
            raise native.win_error("CreateProcessW(AppContainer)")
        process = AppContainerProcess(
            process_handle=int(info.hProcess),
            thread_handle=int(info.hThread),
            pid=int(info.dwProcessId),
            args=command,
            profile_name=policy.profile_name,
            api=native,
        )
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
        raise
    finally:
        if pointer is not None:
            native.kernel32.DeleteProcThreadAttributeList(pointer)
        # Keep the opaque attribute-list storage alive through CreateProcessW.
        _ = storage
