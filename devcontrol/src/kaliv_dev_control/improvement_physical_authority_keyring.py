"""Host-controlled Ed25519 trust root for RSI physical request verification.

This module is verification-only. It never loads a private key, signs data,
contacts a network service, or grants physical execution authority. Production
verification reads one fixed host-admin-controlled public-keyring file and fails
closed when that trust root is missing, malformed, or writable by an untrusted
host principal.
"""
from __future__ import annotations

import ctypes
import json
import os
import stat
from pathlib import Path
from typing import Any, Mapping

from .asymmetric_authority import (
    AsymmetricAuthorityError,
    Ed25519AuthorityVerifier,
    TrustedEd25519AuthorityKey,
)
from .improvement_physical_request import PHYSICAL_REQUEST_ISSUER_SYSTEM_ID
from .trusted_git_runtime_model import _has_linkish_component

PHYSICAL_REQUEST_AUTHORITY_KEYRING_SCHEMA = (
    "kaliv-rsi-physical-request-authority-keyring/v1"
)
PHYSICAL_REQUEST_AUTHORITY_DOMAIN = "rsi-dc-l15-physical-request"
_MAX_KEYRING_BYTES = 256 * 1024
_KEYRING_FIELDS = {
    "schema",
    "authority_domain",
    "minimum_keyring_epoch",
    "trusted_keys",
}

# Windows security constants. The ACL policy intentionally permits write/control
# authority only to SYSTEM, BUILTIN\Administrators, or TrustedInstaller.
_SE_FILE_OBJECT = 1
_OWNER_SECURITY_INFORMATION = 0x00000001
_DACL_SECURITY_INFORMATION = 0x00000004
_ACL_SIZE_INFORMATION_CLASS = 2
_ACCESS_ALLOWED_ACE_TYPE = 0x00
_ACCESS_ALLOWED_OBJECT_ACE_TYPE = 0x05
_ACCESS_ALLOWED_CALLBACK_ACE_TYPE = 0x09
_ACCESS_ALLOWED_CALLBACK_OBJECT_ACE_TYPE = 0x0B
_OBJECT_TYPE_PRESENT = 0x00000001
_INHERITED_OBJECT_TYPE_PRESENT = 0x00000002
_INHERIT_ONLY_ACE = 0x08
_GENERIC_ALL = 0x10000000
_GENERIC_WRITE = 0x40000000
_DELETE = 0x00010000
_WRITE_DAC = 0x00040000
_WRITE_OWNER = 0x00080000
_FILE_WRITE_DATA = 0x00000002
_FILE_APPEND_DATA = 0x00000004
_FILE_WRITE_EA = 0x00000010
_FILE_DELETE_CHILD = 0x00000040
_FILE_WRITE_ATTRIBUTES = 0x00000100
_WINDOWS_FILE_WRITE_MASK = (
    _GENERIC_ALL
    | _GENERIC_WRITE
    | _DELETE
    | _WRITE_DAC
    | _WRITE_OWNER
    | _FILE_WRITE_DATA
    | _FILE_APPEND_DATA
    | _FILE_WRITE_EA
    | _FILE_WRITE_ATTRIBUTES
)
_WINDOWS_DIRECTORY_WRITE_MASK = _WINDOWS_FILE_WRITE_MASK | _FILE_DELETE_CHILD
_WINDOWS_TRUSTED_CONTROL_SIDS = frozenset(
    {
        "S-1-5-18",  # NT AUTHORITY\SYSTEM
        "S-1-5-32-544",  # BUILTIN\Administrators
        # NT SERVICE\TrustedInstaller
        "S-1-5-80-956008885-3418522649-1831038044-1853292631-2271478464",
    }
)
_WINDOWS_ALLOW_ACE_TYPES = frozenset(
    {
        _ACCESS_ALLOWED_ACE_TYPE,
        _ACCESS_ALLOWED_OBJECT_ACE_TYPE,
        _ACCESS_ALLOWED_CALLBACK_ACE_TYPE,
        _ACCESS_ALLOWED_CALLBACK_OBJECT_ACE_TYPE,
    }
)


class PhysicalRequestAuthorityKeyringError(ValueError):
    """The host-controlled physical-request verification trust root is invalid."""


class _ACE_HEADER(ctypes.Structure):
    _fields_ = [
        ("AceType", ctypes.c_ubyte),
        ("AceFlags", ctypes.c_ubyte),
        ("AceSize", ctypes.c_ushort),
    ]


class _ACL_SIZE_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("AceCount", ctypes.c_uint32),
        ("AclBytesInUse", ctypes.c_uint32),
        ("AclBytesFree", ctypes.c_uint32),
    ]


def _canonical(value: Mapping[str, Any]) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise PhysicalRequestAuthorityKeyringError(
            "physical request authority keyring is not canonical JSON"
        ) from exc


def _canonical_physical_request_authority_keyring_path() -> Path:
    """Return the fixed host-admin path; callers cannot select this location."""

    if os.name == "nt":
        return Path(
            r"C:\Program Files\ModelRig\DevControl\authority\rsi-physical-request-authority-keyring-v1.json"
        )
    if os.name == "posix":
        return Path(
            "/etc/modelrig/devcontrol/authority/rsi-physical-request-authority-keyring-v1.json"
        )
    raise PhysicalRequestAuthorityKeyringError(
        "physical request authority keyring is unsupported on this platform"
    )


def _require_posix_host_control(path: Path, observed: os.stat_result) -> None:
    """Require a root-owned keyring under a root-owned non-writable directory chain."""

    if observed.st_uid != 0 or stat.S_IMODE(observed.st_mode) & 0o022:
        raise PhysicalRequestAuthorityKeyringError(
            "physical request authority keyring is not root-controlled"
        )
    cursor = path.parent
    while True:
        try:
            directory = cursor.stat()
        except OSError as exc:
            raise PhysicalRequestAuthorityKeyringError(
                "physical request authority keyring parent is unavailable"
            ) from exc
        if (
            not stat.S_ISDIR(directory.st_mode)
            or directory.st_uid != 0
            or stat.S_IMODE(directory.st_mode) & 0o022
        ):
            raise PhysicalRequestAuthorityKeyringError(
                "physical request authority keyring directory chain is not root-controlled"
            )
        if cursor.parent == cursor:
            return
        cursor = cursor.parent


def _windows_sid_string(advapi32: Any, kernel32: Any, sid_pointer: int) -> str:
    output = ctypes.c_wchar_p()
    if not sid_pointer or not advapi32.ConvertSidToStringSidW(
        ctypes.c_void_p(sid_pointer), ctypes.byref(output)
    ):
        raise PhysicalRequestAuthorityKeyringError(
            "physical request authority ACL contains an invalid SID"
        )
    try:
        value = output.value or ""
        if not value.startswith("S-"):
            raise PhysicalRequestAuthorityKeyringError(
                "physical request authority ACL SID is malformed"
            )
        return value
    finally:
        pointer = ctypes.cast(output, ctypes.c_void_p).value
        if pointer:
            kernel32.LocalFree(ctypes.c_void_p(pointer))


def _windows_allowed_ace_sid_offset(ace_type: int, address: int, ace_size: int) -> int:
    if ace_type in {_ACCESS_ALLOWED_ACE_TYPE, _ACCESS_ALLOWED_CALLBACK_ACE_TYPE}:
        offset = 8
    elif ace_type in {
        _ACCESS_ALLOWED_OBJECT_ACE_TYPE,
        _ACCESS_ALLOWED_CALLBACK_OBJECT_ACE_TYPE,
    }:
        if ace_size < 12:
            raise PhysicalRequestAuthorityKeyringError(
                "physical request authority ACL object ACE is truncated"
            )
        flags = ctypes.c_uint32.from_address(address + 8).value
        offset = 12
        if flags & _OBJECT_TYPE_PRESENT:
            offset += 16
        if flags & _INHERITED_OBJECT_TYPE_PRESENT:
            offset += 16
    else:
        raise PhysicalRequestAuthorityKeyringError(
            "physical request authority ACL contains an unsupported allow ACE"
        )
    if offset >= ace_size:
        raise PhysicalRequestAuthorityKeyringError(
            "physical request authority ACL ACE has no SID"
        )
    return offset


def _windows_acl_snapshot(path: Path) -> tuple[str, tuple[tuple[int, str], ...]]:
    """Read owner + effective allow ACEs through Win32 security APIs."""

    if os.name != "nt":
        raise PhysicalRequestAuthorityKeyringError(
            "Windows authority ACL inspection requires Windows"
        )
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)

    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p
    advapi32.ConvertSidToStringSidW.argtypes = [
        ctypes.c_void_p,
        ctypes.POINTER(ctypes.c_wchar_p),
    ]
    advapi32.ConvertSidToStringSidW.restype = ctypes.c_int
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
    advapi32.GetAclInformation.argtypes = [
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_uint32,
        ctypes.c_int,
    ]
    advapi32.GetAclInformation.restype = ctypes.c_int
    advapi32.GetAce.argtypes = [
        ctypes.c_void_p,
        ctypes.c_uint32,
        ctypes.POINTER(ctypes.c_void_p),
    ]
    advapi32.GetAce.restype = ctypes.c_int

    owner = ctypes.c_void_p()
    dacl = ctypes.c_void_p()
    descriptor = ctypes.c_void_p()
    code = int(
        advapi32.GetNamedSecurityInfoW(
            os.fspath(path),
            _SE_FILE_OBJECT,
            _OWNER_SECURITY_INFORMATION | _DACL_SECURITY_INFORMATION,
            ctypes.byref(owner),
            None,
            ctypes.byref(dacl),
            None,
            ctypes.byref(descriptor),
        )
    )
    if code:
        raise PhysicalRequestAuthorityKeyringError(
            f"physical request authority ACL query failed with WinError {code}"
        )
    try:
        if not owner.value or not dacl.value:
            raise PhysicalRequestAuthorityKeyringError(
                "physical request authority ACL has no protected owner/DACL"
            )
        owner_sid = _windows_sid_string(
            advapi32, kernel32, int(owner.value)
        )
        info = _ACL_SIZE_INFORMATION()
        if not advapi32.GetAclInformation(
            dacl,
            ctypes.byref(info),
            ctypes.sizeof(info),
            _ACL_SIZE_INFORMATION_CLASS,
        ):
            raise PhysicalRequestAuthorityKeyringError(
                "physical request authority DACL could not be enumerated"
            )
        entries: list[tuple[int, str]] = []
        for index in range(int(info.AceCount)):
            ace_pointer = ctypes.c_void_p()
            if not advapi32.GetAce(dacl, index, ctypes.byref(ace_pointer)):
                raise PhysicalRequestAuthorityKeyringError(
                    "physical request authority DACL ACE could not be read"
                )
            if not ace_pointer.value:
                raise PhysicalRequestAuthorityKeyringError(
                    "physical request authority DACL contains a null ACE"
                )
            address = int(ace_pointer.value)
            header = ctypes.cast(
                ace_pointer, ctypes.POINTER(_ACE_HEADER)
            ).contents
            if header.AceSize < 8:
                raise PhysicalRequestAuthorityKeyringError(
                    "physical request authority DACL ACE is truncated"
                )
            if header.AceType not in _WINDOWS_ALLOW_ACE_TYPES:
                continue
            if header.AceFlags & _INHERIT_ONLY_ACE:
                continue
            mask = int(ctypes.c_uint32.from_address(address + 4).value)
            offset = _windows_allowed_ace_sid_offset(
                int(header.AceType), address, int(header.AceSize)
            )
            sid = _windows_sid_string(
                advapi32, kernel32, address + offset
            )
            entries.append((mask, sid))
        return owner_sid, tuple(entries)
    finally:
        if descriptor.value:
            kernel32.LocalFree(ctypes.c_void_p(int(descriptor.value)))


def _validate_windows_acl_snapshot(
    owner_sid: str,
    allow_entries: tuple[tuple[int, str], ...],
    *,
    is_directory: bool,
) -> None:
    """Fail closed if an untrusted Windows principal can mutate/control the object."""

    if owner_sid not in _WINDOWS_TRUSTED_CONTROL_SIDS:
        raise PhysicalRequestAuthorityKeyringError(
            "physical request authority object owner is not host-admin controlled"
        )
    dangerous = (
        _WINDOWS_DIRECTORY_WRITE_MASK if is_directory else _WINDOWS_FILE_WRITE_MASK
    )
    for mask, sid in allow_entries:
        if mask & dangerous and sid not in _WINDOWS_TRUSTED_CONTROL_SIDS:
            raise PhysicalRequestAuthorityKeyringError(
                "physical request authority ACL grants untrusted write/control access"
            )


def _require_windows_host_control(path: Path, observed: os.stat_result) -> None:
    """Require a protected Program Files keyring and protected directory chain."""

    candidate = Path(os.path.abspath(os.fspath(path)))
    anchor = Path(os.path.abspath(r"C:\Program Files"))
    candidate_norm = os.path.normcase(os.fspath(candidate))
    anchor_norm = os.path.normcase(os.fspath(anchor))
    try:
        common = os.path.normcase(os.path.commonpath([candidate_norm, anchor_norm]))
    except ValueError as exc:
        raise PhysicalRequestAuthorityKeyringError(
            "physical request authority keyring is outside Program Files"
        ) from exc
    if common != anchor_norm:
        raise PhysicalRequestAuthorityKeyringError(
            "physical request authority keyring is outside Program Files"
        )
    try:
        current = candidate.stat()
    except OSError as exc:
        raise PhysicalRequestAuthorityKeyringError(
            "physical request authority keyring path changed during validation"
        ) from exc
    if (current.st_dev, current.st_ino) != (observed.st_dev, observed.st_ino):
        raise PhysicalRequestAuthorityKeyringError(
            "physical request authority keyring path was replaced during validation"
        )

    owner_sid, entries = _windows_acl_snapshot(candidate)
    _validate_windows_acl_snapshot(owner_sid, entries, is_directory=False)

    cursor = candidate.parent
    while True:
        cursor_norm = os.path.normcase(os.path.abspath(os.fspath(cursor)))
        if not cursor.is_dir() or _has_linkish_component(cursor):
            raise PhysicalRequestAuthorityKeyringError(
                "physical request authority keyring directory chain is unsafe"
            )
        owner_sid, entries = _windows_acl_snapshot(cursor)
        _validate_windows_acl_snapshot(owner_sid, entries, is_directory=True)
        if cursor_norm == anchor_norm:
            break
        parent = cursor.parent
        if parent == cursor or not cursor_norm.startswith(anchor_norm):
            raise PhysicalRequestAuthorityKeyringError(
                "physical request authority keyring directory chain escaped Program Files"
            )
        cursor = parent


def _require_host_control(path: Path, observed: os.stat_result) -> None:
    if os.name == "posix":
        _require_posix_host_control(path, observed)
        return
    if os.name == "nt":
        _require_windows_host_control(path, observed)
        return
    raise PhysicalRequestAuthorityKeyringError(
        "physical request authority host-control validation is unsupported"
    )


def _read_keyring_bytes(
    path: Path,
    *,
    require_host_control: bool,
) -> bytes:
    candidate = Path(path)
    if not candidate.is_absolute() or _has_linkish_component(candidate):
        raise PhysicalRequestAuthorityKeyringError(
            "physical request authority keyring path is unsafe"
        )
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(candidate, flags)
    except OSError as exc:
        raise PhysicalRequestAuthorityKeyringError(
            "physical request authority keyring is missing or unreadable"
        ) from exc
    try:
        observed = os.fstat(descriptor)
        if (
            not stat.S_ISREG(observed.st_mode)
            or observed.st_nlink != 1
            or observed.st_size < 1
            or observed.st_size > _MAX_KEYRING_BYTES
        ):
            raise PhysicalRequestAuthorityKeyringError(
                "physical request authority keyring file is unsafe"
            )
        if require_host_control:
            _require_host_control(candidate, observed)
        remaining = observed.st_size
        chunks: list[bytes] = []
        while remaining:
            chunk = os.read(descriptor, min(64 * 1024, remaining))
            if not chunk:
                raise PhysicalRequestAuthorityKeyringError(
                    "physical request authority keyring read was incomplete"
                )
            chunks.append(chunk)
            remaining -= len(chunk)
        if os.read(descriptor, 1):
            raise PhysicalRequestAuthorityKeyringError(
                "physical request authority keyring changed while reading"
            )
        return b"".join(chunks)
    except OSError as exc:
        raise PhysicalRequestAuthorityKeyringError(
            "physical request authority keyring could not be read safely"
        ) from exc
    finally:
        os.close(descriptor)


def _load_physical_request_authority_verifier_at(
    path: Path,
    *,
    require_host_control: bool = True,
) -> Ed25519AuthorityVerifier:
    """Load one exact public verification keyring; never caller-selected in production."""

    payload = _read_keyring_bytes(
        path,
        require_host_control=require_host_control,
    )
    try:
        value = json.loads(payload.decode("utf-8", errors="strict"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise PhysicalRequestAuthorityKeyringError(
            "physical request authority keyring is invalid JSON"
        ) from exc
    if not isinstance(value, Mapping) or set(value) != _KEYRING_FIELDS:
        raise PhysicalRequestAuthorityKeyringError(
            "physical request authority keyring fields mismatch"
        )
    if value.get("schema") != PHYSICAL_REQUEST_AUTHORITY_KEYRING_SCHEMA:
        raise PhysicalRequestAuthorityKeyringError(
            "physical request authority keyring schema is unsupported"
        )
    if value.get("authority_domain") != PHYSICAL_REQUEST_AUTHORITY_DOMAIN:
        raise PhysicalRequestAuthorityKeyringError(
            "physical request authority keyring belongs to another authority domain"
        )
    minimum_epoch = value.get("minimum_keyring_epoch")
    if (
        not isinstance(minimum_epoch, int)
        or isinstance(minimum_epoch, bool)
        or minimum_epoch < 1
    ):
        raise PhysicalRequestAuthorityKeyringError(
            "physical request authority minimum keyring epoch is invalid"
        )
    raw_keys = value.get("trusted_keys")
    if not isinstance(raw_keys, list) or not raw_keys:
        raise PhysicalRequestAuthorityKeyringError(
            "physical request authority keyring must contain trusted public keys"
        )

    trusted: dict[str, TrustedEd25519AuthorityKey] = {}
    canonical_keys: list[dict[str, Any]] = []
    previous_key_id: str | None = None
    try:
        for raw in raw_keys:
            key = TrustedEd25519AuthorityKey.from_mapping(raw)
            if key.issuer_system_id != PHYSICAL_REQUEST_ISSUER_SYSTEM_ID:
                raise PhysicalRequestAuthorityKeyringError(
                    "physical request authority key belongs to another issuer system"
                )
            if previous_key_id is not None and key.key_id <= previous_key_id:
                raise PhysicalRequestAuthorityKeyringError(
                    "physical request authority keys must be sorted and unique"
                )
            previous_key_id = key.key_id
            trusted[key.key_id] = key
            canonical_keys.append(key.to_dict())
        verifier = Ed25519AuthorityVerifier(
            trusted,
            minimum_keyring_epoch=minimum_epoch,
        )
    except AsymmetricAuthorityError as exc:
        raise PhysicalRequestAuthorityKeyringError(
            "physical request authority keyring contains invalid public-key evidence"
        ) from exc

    canonical_mapping = {
        "schema": PHYSICAL_REQUEST_AUTHORITY_KEYRING_SCHEMA,
        "authority_domain": PHYSICAL_REQUEST_AUTHORITY_DOMAIN,
        "minimum_keyring_epoch": minimum_epoch,
        "trusted_keys": canonical_keys,
    }
    if payload != _canonical(canonical_mapping):
        raise PhysicalRequestAuthorityKeyringError(
            "physical request authority keyring is not canonical"
        )
    return verifier


def _canonical_physical_request_authority_verifier() -> Ed25519AuthorityVerifier:
    """Resolve the production trust root from the fixed host-admin keyring path."""

    return _load_physical_request_authority_verifier_at(
        _canonical_physical_request_authority_keyring_path(),
        require_host_control=True,
    )


__all__: list[str] = []
