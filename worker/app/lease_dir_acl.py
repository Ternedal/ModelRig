"""Pure judgment of the GPU lease directory's owner and DACL on Windows (gap G5, #2296).

On POSIX ``gpu_lease`` refuses a lease directory that is not owned by the
process user or is group- or world-writable. On Windows the mode bits say
nothing, so until now nothing checked who could create, replace or delete the
lock files that decide which process may use a GPU. This module is the decision
half; ``lease_dir_acl_windows`` reads the real security descriptor.

The rule follows ``credential_acl`` (owner, trusted principals, fail closed),
with one difference: a lease directory holds no secret, so another principal may
also list and traverse it and read attributes and extended attributes. Anything
that can add, replace, delete or re-permission an entry refuses.
"""
from __future__ import annotations

from typing import Iterable

from .credential_acl import (
    ACCESS_ALLOWED_ACE_TYPE,
    ACCESS_DENIED_ACE_TYPE,
    ADMINISTRATORS_SID,
    FILE_READ_ATTRIBUTES,
    GENERIC_EXECUTE,
    GENERIC_READ,
    OWNER_RIGHTS_SID,
    READ_CONTROL,
    SYNCHRONIZE,
    SYSTEM_SID,
    Ace,
    _sid,
)

FILE_LIST_DIRECTORY = 0x0000_0001
FILE_ADD_FILE = 0x0000_0002
FILE_ADD_SUBDIRECTORY = 0x0000_0004
FILE_READ_EA = 0x0000_0008
FILE_WRITE_EA = 0x0000_0010
FILE_TRAVERSE = 0x0000_0020
FILE_DELETE_CHILD = 0x0000_0040
FILE_WRITE_ATTRIBUTES = 0x0000_0100

# Allowlist: another principal may hold only these. Every other bit, known or
# not (add file or subdirectory, delete child, write attributes or EAs, DELETE,
# WRITE_DAC, WRITE_OWNER, GENERIC_WRITE, GENERIC_ALL, MAXIMUM_ALLOWED), refuses.
BENIGN_DIRECTORY_RIGHTS = (SYNCHRONIZE | READ_CONTROL | FILE_READ_ATTRIBUTES | FILE_LIST_DIRECTORY
                           | FILE_READ_EA | FILE_TRAVERSE | GENERIC_READ | GENERIC_EXECUTE)


def evaluate_lease_dir_acl(owner_sid: object, dacl: Iterable[Ace] | None, process_sid: object) -> tuple[bool, str]:
    """Return (acceptable, reason). Refuses unless the directory is positively private for writing.

    Accepted only when the owner is the process user, LocalSystem or
    Administrators, and every allow ACE for any other principal (OWNER RIGHTS
    counts as the owner once the owner is trusted) holds nothing beyond
    BENIGN_DIRECTORY_RIGHTS. Deny ACEs never make a directory acceptable.
    Inherited and inherit-only ACEs count like explicit ones: an inherit-only
    grant reaches the lock files themselves. CREATOR OWNER and CREATOR GROUP are
    other principals like any else.

    ``dacl=None`` is a NULL DACL (everyone has full access) and refuses.
    """
    process = _sid(process_sid)
    if process is None:
        return False, "process user SID is unknown"
    trusted = {process, SYSTEM_SID, ADMINISTRATORS_SID}
    owner = _sid(owner_sid)
    if owner is None:
        return False, "lease directory owner is unknown"
    if owner not in trusted:
        return False, "lease directory is owned by another principal"
    trusted.add(OWNER_RIGHTS_SID)
    if dacl is None:
        return False, "NULL DACL grants everyone full access"
    try:
        aces = list(dacl)
    except TypeError:
        return False, "DACL could not be read"
    for ace in aces:
        if not isinstance(ace, Ace):
            return False, "DACL entry could not be parsed"
        if ace.ace_type not in (ACCESS_ALLOWED_ACE_TYPE, ACCESS_DENIED_ACE_TYPE):
            return False, "DACL has an entry type this check does not understand"
        if isinstance(ace.mask, bool) or not isinstance(ace.mask, int) or not 0 <= ace.mask <= 0xFFFF_FFFF:
            return False, "DACL entry has an invalid access mask"
        sid = _sid(ace.sid)
        if sid is None:
            return False, "DACL entry names an unknown principal"
        if ace.ace_type == ACCESS_ALLOWED_ACE_TYPE and sid not in trusted and ace.mask & ~BENIGN_DIRECTORY_RIGHTS:
            return False, f"{sid} can add, replace, delete or re-permission lease files"
    return True, "only the process user, SYSTEM and Administrators can change the lease directory"
