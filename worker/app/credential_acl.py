"""Pure judgment of a Windows credential file's owner and DACL.

Step 1 of docs/T038_WINDOWS_TOKEN_ACL_DESIGN.md (KalivNexus #1). The three
bearer-file loaders (Home Assistant, RigGate, GitHub connector) reject a
group/world-readable file only on POSIX; on Windows nothing checks who can
read it. This module is the decision half of the fix: given an owner SID, a
DACL as a list of ACEs and the process user's SID, decide whether the file is
private enough to hold a bearer token.

It reads nothing from the operating system and is not yet called by any
loader, so it changes no behaviour. Reading the real security descriptor
(``GetNamedSecurityInfoW`` through ctypes) and wiring it into the loaders are
later, separately reviewed steps. Every uncertainty decides towards refusal.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

SYSTEM_SID = "S-1-5-18"
ADMINISTRATORS_SID = "S-1-5-32-544"

ACCESS_ALLOWED_ACE_TYPE = 0
ACCESS_DENIED_ACE_TYPE = 1

# Access-mask bits named in tests and docs.
FILE_READ_DATA = 0x0000_0001
FILE_WRITE_DATA = 0x0000_0002
FILE_APPEND_DATA = 0x0000_0004
FILE_EXECUTE = 0x0000_0020
FILE_READ_ATTRIBUTES = 0x0000_0080
DELETE = 0x0001_0000
READ_CONTROL = 0x0002_0000
WRITE_DAC = 0x0004_0000
WRITE_OWNER = 0x0008_0000
SYNCHRONIZE = 0x0010_0000
MAXIMUM_ALLOWED = 0x0200_0000
GENERIC_ALL = 0x1000_0000
GENERIC_EXECUTE = 0x2000_0000
GENERIC_WRITE = 0x4000_0000
GENERIC_READ = 0x8000_0000

# Allowlist, not denylist: another principal may hold ONLY rights that can
# neither read the token nor tamper with it (replace, append, delete, re-permission,
# take ownership, map/execute). Any other bit -- known or not -- refuses.
BENIGN_RIGHTS = SYNCHRONIZE | FILE_READ_ATTRIBUTES | READ_CONTROL

# Canonical SID bounds (MS-DTYP 2.4.2): revision 1, 48-bit identifier
# authority, 1..15 subauthorities of 32 bits each, ASCII decimal only.
_MAX_AUTHORITY = (1 << 48) - 1
_MAX_SUBAUTHORITY = (1 << 32) - 1
_MAX_SUBAUTHORITIES = 15


@dataclass(frozen=True)
class Ace:
    ace_type: int
    flags: int
    mask: int
    sid: str


def _ascii_decimal(text: str, maximum: int) -> int | None:
    # str.isdigit() accepts "\u00b2" and other non-ASCII digits; only 0-9 are valid here.
    if not text or len(text) > 20 or any(c not in "0123456789" for c in text):
        return None
    if len(text) > 1 and text[0] == "0":
        return None  # canonical form has no leading zeros
    value = int(text)
    return value if value <= maximum else None


def _sid(value: object) -> str | None:
    """Return the SID if it is canonical "S-1-<authority>-<sub>..." text, else None."""
    if not isinstance(value, str) or len(value) > 184:
        return None
    parts = value.split("-")
    if len(parts) < 4 or parts[0] != "S" or parts[1] != "1":
        return None
    if _ascii_decimal(parts[2], _MAX_AUTHORITY) is None:
        return None
    subauthorities = parts[3:]
    if not 1 <= len(subauthorities) <= _MAX_SUBAUTHORITIES:
        return None
    if any(_ascii_decimal(part, _MAX_SUBAUTHORITY) is None for part in subauthorities):
        return None
    return value


def evaluate_credential_acl(
    owner_sid: object,
    dacl: Iterable[Ace] | None,
    process_sid: object,
) -> tuple[bool, str]:
    """Return (acceptable, reason). Refuses unless privacy is positively shown.

    Accepted only when the owner is the process user, LocalSystem or
    Administrators, and every allow ACE for any other principal holds nothing
    beyond SYNCHRONIZE, FILE_READ_ATTRIBUTES and READ_CONTROL. Deny ACEs never
    make a file acceptable: allow ACEs alone decide, which is conservative by
    construction. Inherited and inherit-only ACEs count like explicit ones.

    ``dacl=None`` means a NULL DACL (everyone has full access) and refuses.
    ``dacl=[]`` means an empty DACL (nobody is granted access); the judgment
    accepts it as private, and the actual read then fails on its own. A reader
    that cannot tell these apart, or fails, must not call this at all: refuse.
    """
    process = _sid(process_sid)
    if process is None:
        return False, "process user SID is unknown"
    trusted = {process, SYSTEM_SID, ADMINISTRATORS_SID}
    owner = _sid(owner_sid)
    if owner is None:
        return False, "file owner is unknown"
    if owner not in trusted:
        return False, "file is owned by another principal"
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
        if ace.ace_type == ACCESS_ALLOWED_ACE_TYPE and sid not in trusted and ace.mask & ~BENIGN_RIGHTS:
            return False, "another principal can read, change, delete or re-permission the file"
    return True, "only the process user, SYSTEM and Administrators can read or change the file"
