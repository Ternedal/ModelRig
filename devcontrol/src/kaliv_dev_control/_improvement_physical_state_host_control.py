"""Privilege boundary for the production RSI physical-request replay ledger.

Live descriptor/directory provenance can detect tamper while a receipt exists,
but it cannot make a service-user-writable directory rollback-resistant between
transactions or after restart. Production replay state therefore lives only in
a fixed administrator-controlled directory and may be mutated only by an
explicit elevated host-operator invocation. The ordinary ModelRig service
identity is not a replay-state writer.

The private reservation implementation keeps its injectable/test ledger seam;
this module is used only by the public production facade.
"""
from __future__ import annotations

import ctypes
import errno
import os
import stat
from pathlib import Path

from .improvement_physical_authority_keyring import (
    PhysicalRequestAuthorityKeyringError,
    _validate_windows_acl_snapshot,
    _windows_acl_snapshot,
)
from .trusted_git_runtime_model import _has_linkish_component

_POSIX_LEDGER = Path("/var/lib/modelrig/devcontrol/rsi-physical-request-ledger-v1")
_WINDOWS_LEDGER = Path(
    r"C:\Program Files\ModelRig\DevControl\state\rsi-physical-request-ledger-v1"
)
_WINDOWS_ANCHOR = Path(r"C:\Program Files")
_POSIX_ACL_XATTRS = ("system.posix_acl_access", "system.posix_acl_default")
# Only explicit xattr absence proves no POSIX ACL is present. If this filesystem
# cannot expose ACL state, production replay authority is intentionally unavailable.
_NO_ACL_XATTR_ERRNOS = frozenset(
    {
        errno.ENODATA,
        getattr(errno, "ENOATTR", errno.ENODATA),
    }
)
_TOKEN_QUERY = 0x0008
_TOKEN_ELEVATION_CLASS = 20


class PhysicalHostStateError(ValueError):
    """The canonical physical-request replay ledger is not host-admin controlled."""


class _TOKEN_ELEVATION(ctypes.Structure):
    _fields_ = [("TokenIsElevated", ctypes.c_uint32)]


def _same_identity(left: os.stat_result, right: os.stat_result) -> bool:
    return (left.st_dev, left.st_ino) == (right.st_dev, right.st_ino)


def _require_posix_elevated_operator() -> None:
    """Production replay mutation is a root/operator action, never service-user work."""

    geteuid = getattr(os, "geteuid", None)
    if geteuid is None or geteuid() != 0:
        raise PhysicalHostStateError(
            "physical request replay reservation requires an elevated host operator"
        )


def _require_windows_elevated_operator() -> None:
    """Require a full elevated Windows token before permitting replay-state writes."""

    if os.name != "nt":
        raise PhysicalHostStateError(
            "Windows replay-state elevation inspection requires Windows"
        )
    try:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    except (AttributeError, OSError) as exc:
        raise PhysicalHostStateError(
            "physical request replay operator token cannot be inspected"
        ) from exc

    kernel32.GetCurrentProcess.argtypes = []
    kernel32.GetCurrentProcess.restype = ctypes.c_void_p
    kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
    kernel32.CloseHandle.restype = ctypes.c_int
    advapi32.OpenProcessToken.argtypes = [
        ctypes.c_void_p,
        ctypes.c_uint32,
        ctypes.POINTER(ctypes.c_void_p),
    ]
    advapi32.OpenProcessToken.restype = ctypes.c_int
    advapi32.GetTokenInformation.argtypes = [
        ctypes.c_void_p,
        ctypes.c_int,
        ctypes.c_void_p,
        ctypes.c_uint32,
        ctypes.POINTER(ctypes.c_uint32),
    ]
    advapi32.GetTokenInformation.restype = ctypes.c_int

    token = ctypes.c_void_p()
    if not advapi32.OpenProcessToken(
        kernel32.GetCurrentProcess(),
        _TOKEN_QUERY,
        ctypes.byref(token),
    ):
        raise PhysicalHostStateError(
            "physical request replay operator token is unavailable"
        )
    try:
        elevation = _TOKEN_ELEVATION()
        returned = ctypes.c_uint32()
        if not advapi32.GetTokenInformation(
            token,
            _TOKEN_ELEVATION_CLASS,
            ctypes.byref(elevation),
            ctypes.sizeof(elevation),
            ctypes.byref(returned),
        ):
            raise PhysicalHostStateError(
                "physical request replay operator elevation is unavailable"
            )
        if returned.value < ctypes.sizeof(elevation) or elevation.TokenIsElevated != 1:
            raise PhysicalHostStateError(
                "physical request replay reservation requires an elevated host operator"
            )
    finally:
        if token.value:
            kernel32.CloseHandle(token)


def _require_elevated_operator() -> None:
    if os.name == "posix":
        _require_posix_elevated_operator()
        return
    if os.name == "nt":
        _require_windows_elevated_operator()
        return
    raise PhysicalHostStateError(
        "physical request replay operator platform is unsupported"
    )


def _validate_posix_directory_stat(observed: os.stat_result) -> None:
    """Require one ordinary root-owned directory with no group/world mutation."""

    if (
        not stat.S_ISDIR(observed.st_mode)
        or observed.st_nlink < 1
        or observed.st_uid != 0
        or stat.S_IMODE(observed.st_mode) & 0o022
    ):
        raise PhysicalHostStateError(
            "physical request replay ledger directory is not root-controlled"
        )


def _require_no_posix_acl(path: Path) -> None:
    """Reject extended POSIX ACLs instead of inferring safety from mode bits alone."""

    if not hasattr(os, "getxattr"):
        raise PhysicalHostStateError(
            "physical request replay ledger ACL state cannot be inspected"
        )
    for name in _POSIX_ACL_XATTRS:
        try:
            payload = os.getxattr(path, name, follow_symlinks=False)
        except OSError as exc:
            if exc.errno in _NO_ACL_XATTR_ERRNOS:
                continue
            raise PhysicalHostStateError(
                "physical request replay ledger POSIX ACL state is unavailable"
            ) from exc
        if payload:
            raise PhysicalHostStateError(
                "physical request replay ledger uses an extended POSIX ACL"
            )


def _require_posix_host_control(path: Path) -> Path:
    candidate = Path(path)
    if not candidate.is_absolute() or _has_linkish_component(candidate):
        raise PhysicalHostStateError(
            "physical request replay ledger path is unsafe"
        )

    chain: list[Path] = []
    cursor = candidate
    while True:
        chain.append(cursor)
        if cursor.parent == cursor:
            break
        cursor = cursor.parent

    # Establish trust root-down. Once a parent is root-controlled and not
    # writable by ordinary principals, the next child cannot be swapped by an
    # unprivileged service process while that child is being attested.
    for directory in reversed(chain):
        try:
            before = directory.lstat()
        except OSError as exc:
            raise PhysicalHostStateError(
                "physical request replay ledger must be pre-provisioned by the host administrator"
            ) from exc
        _validate_posix_directory_stat(before)
        _require_no_posix_acl(directory)
        try:
            after = directory.lstat()
        except OSError as exc:
            raise PhysicalHostStateError(
                "physical request replay ledger directory changed during validation"
            ) from exc
        if not _same_identity(before, after):
            raise PhysicalHostStateError(
                "physical request replay ledger directory was replaced during validation"
            )
    return candidate


def _windows_under_program_files(path: Path) -> tuple[Path, Path]:
    candidate = Path(os.path.abspath(os.fspath(path)))
    anchor = Path(os.path.abspath(os.fspath(_WINDOWS_ANCHOR)))
    candidate_norm = os.path.normcase(os.fspath(candidate))
    anchor_norm = os.path.normcase(os.fspath(anchor))
    try:
        common = os.path.normcase(os.path.commonpath([candidate_norm, anchor_norm]))
    except ValueError as exc:
        raise PhysicalHostStateError(
            "physical request replay ledger is outside Program Files"
        ) from exc
    if common != anchor_norm:
        raise PhysicalHostStateError(
            "physical request replay ledger is outside Program Files"
        )
    return candidate, anchor


def _require_windows_host_control(path: Path) -> Path:
    candidate, anchor = _windows_under_program_files(path)
    if not candidate.is_dir() or _has_linkish_component(candidate):
        raise PhysicalHostStateError(
            "physical request replay ledger must be a pre-provisioned protected directory"
        )

    chain: list[Path] = []
    cursor = candidate
    anchor_norm = os.path.normcase(os.fspath(anchor))
    while True:
        cursor_norm = os.path.normcase(os.path.abspath(os.fspath(cursor)))
        chain.append(cursor)
        if cursor_norm == anchor_norm:
            break
        parent = cursor.parent
        if parent == cursor:
            raise PhysicalHostStateError(
                "physical request replay ledger directory chain escaped Program Files"
            )
        cursor = parent

    for directory in reversed(chain):
        try:
            before = directory.lstat()
            if not stat.S_ISDIR(before.st_mode) or before.st_nlink < 1:
                raise PhysicalHostStateError(
                    "physical request replay ledger directory is unsafe"
                )
            owner_sid, entries = _windows_acl_snapshot(directory)
            _validate_windows_acl_snapshot(
                owner_sid,
                entries,
                is_directory=True,
            )
            after = directory.lstat()
        except PhysicalHostStateError:
            raise
        except (OSError, PhysicalRequestAuthorityKeyringError) as exc:
            raise PhysicalHostStateError(
                "physical request replay ledger Windows ACL is not host controlled"
            ) from exc
        if not _same_identity(before, after):
            raise PhysicalHostStateError(
                "physical request replay ledger directory was replaced during validation"
            )
    return candidate


def _require_host_controlled_ledger_root(path: Path) -> Path:
    if os.name == "posix":
        return _require_posix_host_control(path)
    if os.name == "nt":
        return _require_windows_host_control(path)
    raise PhysicalHostStateError(
        "physical request replay ledger host-control platform is unsupported"
    )


def _canonical_host_controlled_ledger_root() -> Path:
    """Resolve fixed production replay state for one elevated physical operator."""

    _require_elevated_operator()
    if os.name == "posix":
        return _require_posix_host_control(_POSIX_LEDGER)
    if os.name == "nt":
        return _require_windows_host_control(_WINDOWS_LEDGER)
    raise PhysicalHostStateError(
        "canonical physical request replay ledger is unsupported on this platform"
    )


__all__: list[str] = []
