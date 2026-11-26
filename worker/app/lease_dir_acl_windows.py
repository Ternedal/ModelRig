"""Read the GPU lease directory's owner and DACL on Windows and judge it (gap G5, #2296).

Reuses the reader that is qualified for credential files (``credential_acl_windows``):
the same API bindings and the same descriptor walk, on a handle opened with
FILE_FLAG_OPEN_REPARSE_POINT so a junction or symlink is never followed. The
only difference is the open: a directory needs FILE_FLAG_BACKUP_SEMANTICS, and
the opened object must BE a directory. ``lease_dir_acl`` is the judgment.

Fail closed: any API failure, a reparse point, something that is not a directory,
or a descriptor that cannot be walked refuses.
"""
from __future__ import annotations

import ctypes
import os
from pathlib import Path

from .credential_acl_windows import (
    FILE_ATTRIBUTE_DIRECTORY,
    FILE_ATTRIBUTE_REPARSE_POINT,
    FILE_FLAG_OPEN_REPARSE_POINT,
    FILE_READ_ATTRIBUTES,
    FILE_SHARE_DELETE,
    FILE_SHARE_READ,
    FILE_SHARE_WRITE,
    INVALID_FILE_ATTRIBUTES,
    INVALID_HANDLE_VALUE,
    OPEN_EXISTING,
    READ_CONTROL,
    CredentialAclUnavailable,
    _Api,
    _BY_HANDLE_FILE_INFORMATION,
    _security_of_handle,
)
from .lease_dir_acl import evaluate_lease_dir_acl

FILE_FLAG_BACKUP_SEMANTICS = 0x02000000  # required to open a directory handle


def read_lease_dir_security(path: str | os.PathLike[str]) -> tuple[str, list | None, str]:
    """Return (owner_sid, dacl, process_sid) for a directory, read via its own handle."""
    api = _Api()
    name = os.fspath(Path(path))
    attributes = int(api.k32.GetFileAttributesW(name))
    if attributes == INVALID_FILE_ATTRIBUTES:
        raise CredentialAclUnavailable(f"GetFileAttributesW failed (WinError {api.last_error()})")
    if attributes & FILE_ATTRIBUTE_REPARSE_POINT:
        raise CredentialAclUnavailable("lease directory is a symlink or junction")
    if not attributes & FILE_ATTRIBUTE_DIRECTORY:
        raise CredentialAclUnavailable("lease directory is not a directory")
    handle = api.k32.CreateFileW(name, READ_CONTROL | FILE_READ_ATTRIBUTES,
                                 FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE, None, OPEN_EXISTING,
                                 FILE_FLAG_BACKUP_SEMANTICS | FILE_FLAG_OPEN_REPARSE_POINT, None)
    value = ctypes.cast(handle, ctypes.c_void_p).value
    if not value or value == INVALID_HANDLE_VALUE:
        raise CredentialAclUnavailable(f"CreateFileW failed (WinError {api.last_error()})")
    try:
        # Authoritative: the object actually opened (a swap after the name check is caught here).
        info = _BY_HANDLE_FILE_INFORMATION()
        if not api.k32.GetFileInformationByHandle(ctypes.c_void_p(value), ctypes.byref(info)):
            raise CredentialAclUnavailable(f"GetFileInformationByHandle failed (WinError {api.last_error()})")
        if info.dwFileAttributes & FILE_ATTRIBUTE_REPARSE_POINT:
            raise CredentialAclUnavailable("opened object is a symlink or junction")
        if not info.dwFileAttributes & FILE_ATTRIBUTE_DIRECTORY:
            raise CredentialAclUnavailable("opened object is not a directory")
        owner_sid, aces = _security_of_handle(api, value)
        return owner_sid, aces, api.process_sid()
    finally:
        api.k32.CloseHandle(ctypes.c_void_p(value))


def lease_dir_private(path: str | os.PathLike[str]) -> tuple[bool, str]:
    """Judge the lease directory; every failure to read its descriptor refuses."""
    try:
        owner, dacl, process = read_lease_dir_security(path)
    except CredentialAclUnavailable as exc:
        return False, f"security descriptor could not be verified: {exc}"
    except (OSError, ValueError, TypeError):
        return False, "security descriptor could not be verified"
    return evaluate_lease_dir_acl(owner, dacl, process)
