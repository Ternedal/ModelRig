"""Read a credential file's owner and DACL on Windows (step 2 of the ACL design).

docs/T038_WINDOWS_TOKEN_ACL_DESIGN.md, KalivNexus #1. ``credential_acl`` is the
pure judgment; this module turns a real Windows security descriptor into its
inputs. It is still **not wired into any loader**: no behaviour changes.

Pattern follows ``windows_runtime_guard``: the file is opened with
READ_CONTROL | FILE_READ_ATTRIBUTES only (never its contents) and
FILE_FLAG_OPEN_REPARSE_POINT, so a symlink or junction is never followed; the
opened handle's own attributes must show a regular, non-reparse file; and the
descriptor is read from that handle (GetSecurityInfo), not by name.

Fail closed: any API failure, a reparse point, a missing owner, an ACL or ACE
whose size does not add up, or an invalid SID raises ``CredentialAclUnavailable``;
``credential_file_private`` turns every such case into a refusal.
"""
from __future__ import annotations

import ctypes
import os
from pathlib import Path

from .credential_acl import (
    ACCESS_ALLOWED_ACE_TYPE,
    ACCESS_DENIED_ACE_TYPE,
    Ace,
    evaluate_credential_acl,
)

ERROR_SUCCESS = 0
ERROR_INSUFFICIENT_BUFFER = 122
INVALID_FILE_ATTRIBUTES = 0xFFFFFFFF
FILE_ATTRIBUTE_DIRECTORY = 0x00000010
FILE_ATTRIBUTE_REPARSE_POINT = 0x00000400
FILE_READ_ATTRIBUTES = 0x00000080
FILE_FLAG_OPEN_REPARSE_POINT = 0x00200000
FILE_SHARE_READ = 0x00000001
FILE_SHARE_WRITE = 0x00000002
FILE_SHARE_DELETE = 0x00000004
OPEN_EXISTING = 3
READ_CONTROL = 0x00020000
TOKEN_QUERY = 0x0008
TOKEN_USER = 1
SE_FILE_OBJECT = 1
OWNER_SECURITY_INFORMATION = 0x00000001
DACL_SECURITY_INFORMATION = 0x00000004
INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value

_MAX_ACES = 1024
_ACE_HEADER_SIZE = 4
_ALLOW_DENY_SID_OFFSET = 8  # ACE_HEADER (4) + ACCESS_MASK (4)


class CredentialAclUnavailable(RuntimeError):
    """The security descriptor could not be read and judged; treat as refusal."""


class _ACL(ctypes.Structure):
    _fields_ = [("AclRevision", ctypes.c_ubyte), ("Sbz1", ctypes.c_ubyte), ("AclSize", ctypes.c_ushort),
                ("AceCount", ctypes.c_ushort), ("Sbz2", ctypes.c_ushort)]


class _ACE_HEADER(ctypes.Structure):
    _fields_ = [("AceType", ctypes.c_ubyte), ("AceFlags", ctypes.c_ubyte), ("AceSize", ctypes.c_ushort)]


class _BY_HANDLE_FILE_INFORMATION(ctypes.Structure):
    _fields_ = [("dwFileAttributes", ctypes.c_uint32), ("ftCreationTime", ctypes.c_uint64),
                ("ftLastAccessTime", ctypes.c_uint64), ("ftLastWriteTime", ctypes.c_uint64),
                ("dwVolumeSerialNumber", ctypes.c_uint32), ("nFileSizeHigh", ctypes.c_uint32),
                ("nFileSizeLow", ctypes.c_uint32), ("nNumberOfLinks", ctypes.c_uint32),
                ("nFileIndexHigh", ctypes.c_uint32), ("nFileIndexLow", ctypes.c_uint32)]
    _pack_ = 4


class _SID_AND_ATTRIBUTES(ctypes.Structure):
    _fields_ = [("Sid", ctypes.c_void_p), ("Attributes", ctypes.c_uint32)]


class _TOKEN_USER(ctypes.Structure):
    _fields_ = [("User", _SID_AND_ATTRIBUTES)]


class _Api:
    def __init__(self) -> None:
        if os.name != "nt":
            raise CredentialAclUnavailable("Windows security descriptors can only be read on Windows")
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        adv = ctypes.WinDLL("advapi32", use_last_error=True)
        k32.CreateFileW.argtypes = [ctypes.c_wchar_p, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p,
                                    ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p]
        k32.CreateFileW.restype = ctypes.c_void_p
        k32.CloseHandle.argtypes = [ctypes.c_void_p]
        k32.CloseHandle.restype = ctypes.c_int
        k32.GetCurrentProcess.argtypes = []
        k32.GetCurrentProcess.restype = ctypes.c_void_p
        k32.GetFileAttributesW.argtypes = [ctypes.c_wchar_p]
        k32.GetFileAttributesW.restype = ctypes.c_uint32
        k32.LocalFree.argtypes = [ctypes.c_void_p]
        k32.LocalFree.restype = ctypes.c_void_p
        k32.GetFileInformationByHandle.argtypes = [ctypes.c_void_p, ctypes.POINTER(_BY_HANDLE_FILE_INFORMATION)]
        k32.GetFileInformationByHandle.restype = ctypes.c_int
        adv.OpenProcessToken.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.POINTER(ctypes.c_void_p)]
        adv.OpenProcessToken.restype = ctypes.c_int
        adv.GetTokenInformation.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p, ctypes.c_uint32,
                                            ctypes.POINTER(ctypes.c_uint32)]
        adv.GetTokenInformation.restype = ctypes.c_int
        adv.GetSecurityInfo.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_uint32] + \
            [ctypes.POINTER(ctypes.c_void_p)] * 5
        adv.GetSecurityInfo.restype = ctypes.c_uint32
        adv.GetAce.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.POINTER(ctypes.c_void_p)]
        adv.GetAce.restype = ctypes.c_int
        adv.IsValidSid.argtypes = [ctypes.c_void_p]
        adv.IsValidSid.restype = ctypes.c_int
        adv.GetLengthSid.argtypes = [ctypes.c_void_p]
        adv.GetLengthSid.restype = ctypes.c_uint32
        adv.ConvertSidToStringSidW.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_wchar_p)]
        adv.ConvertSidToStringSidW.restype = ctypes.c_int
        self.k32, self.adv = k32, adv

    def fail(self, action: str) -> CredentialAclUnavailable:
        return CredentialAclUnavailable(f"{action} failed (WinError {ctypes.get_last_error()})")

    def sid_string(self, psid: int, *, limit: int | None = None) -> str:
        if not psid or not self.adv.IsValidSid(ctypes.c_void_p(psid)):
            raise CredentialAclUnavailable("descriptor contains an invalid SID")
        if limit is not None and self.adv.GetLengthSid(ctypes.c_void_p(psid)) > limit:
            raise CredentialAclUnavailable("SID runs past the end of its ACE")
        text = ctypes.c_wchar_p()
        if not self.adv.ConvertSidToStringSidW(ctypes.c_void_p(psid), ctypes.byref(text)):
            raise self.fail("ConvertSidToStringSidW")
        try:
            return str(text.value)
        finally:
            self.k32.LocalFree(ctypes.cast(text, ctypes.c_void_p))

    def process_sid(self) -> str:
        token = ctypes.c_void_p()
        if not self.adv.OpenProcessToken(self.k32.GetCurrentProcess(), TOKEN_QUERY, ctypes.byref(token)):
            raise self.fail("OpenProcessToken")
        try:
            needed = ctypes.c_uint32()
            self.adv.GetTokenInformation(token, TOKEN_USER, None, 0, ctypes.byref(needed))
            if ctypes.get_last_error() != ERROR_INSUFFICIENT_BUFFER or not needed.value:
                raise self.fail("GetTokenInformation(size)")
            storage = ctypes.create_string_buffer(needed.value)
            if not self.adv.GetTokenInformation(token, TOKEN_USER, storage, needed.value, ctypes.byref(needed)):
                raise self.fail("GetTokenInformation")
            user = ctypes.cast(storage, ctypes.POINTER(_TOKEN_USER)).contents
            return self.sid_string(int(user.User.Sid or 0))
        finally:
            if token.value:
                self.k32.CloseHandle(token)


def read_credential_security(path: str | os.PathLike[str]) -> tuple[str, list[Ace] | None, str]:
    """Return (owner_sid, dacl, process_sid) for a regular file, read via its handle.

    ``dacl`` is None for a NULL or absent DACL (the judgment refuses both) and a
    list -- possibly empty -- otherwise. Raises CredentialAclUnavailable instead
    of guessing.
    """
    api = _Api()
    name = os.fspath(Path(path))
    attributes = int(api.k32.GetFileAttributesW(name))
    if attributes == INVALID_FILE_ATTRIBUTES:
        raise api.fail("GetFileAttributesW")
    if attributes & FILE_ATTRIBUTE_REPARSE_POINT:
        raise CredentialAclUnavailable("credential path is a symlink or junction")
    handle = api.k32.CreateFileW(name, READ_CONTROL | FILE_READ_ATTRIBUTES,
                                 FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE,
                                 None, OPEN_EXISTING, FILE_FLAG_OPEN_REPARSE_POINT, None)
    value = ctypes.cast(handle, ctypes.c_void_p).value
    if not value or value == INVALID_HANDLE_VALUE:
        raise api.fail("CreateFileW(READ_CONTROL)")
    descriptor = ctypes.c_void_p()
    try:
        # Authoritative check, on the object actually opened (Codex P2 4387779979):
        # FILE_FLAG_OPEN_REPARSE_POINT opens a link instead of refusing it, so a
        # path swapped for a symlink after GetFileAttributesW must be caught here.
        info = _BY_HANDLE_FILE_INFORMATION()
        if not api.k32.GetFileInformationByHandle(ctypes.c_void_p(value), ctypes.byref(info)):
            raise api.fail("GetFileInformationByHandle")
        if info.dwFileAttributes & FILE_ATTRIBUTE_REPARSE_POINT:
            raise CredentialAclUnavailable("opened object is a symlink or junction")
        if info.dwFileAttributes & FILE_ATTRIBUTE_DIRECTORY:
            raise CredentialAclUnavailable("opened object is a directory")
        owner, group, dacl, sacl = (ctypes.c_void_p() for _ in range(4))
        code = int(api.adv.GetSecurityInfo(ctypes.c_void_p(value), SE_FILE_OBJECT,
                                           OWNER_SECURITY_INFORMATION | DACL_SECURITY_INFORMATION,
                                           ctypes.byref(owner), ctypes.byref(group), ctypes.byref(dacl),
                                           ctypes.byref(sacl), ctypes.byref(descriptor)))
        if code != ERROR_SUCCESS:
            raise CredentialAclUnavailable(f"GetSecurityInfo failed (error {code})")
        if not owner.value:
            raise CredentialAclUnavailable("descriptor has no owner")
        owner_sid = api.sid_string(owner.value)
        aces: list[Ace] | None = None
        if dacl.value:
            header = ctypes.cast(dacl, ctypes.POINTER(_ACL)).contents
            if header.AceCount > _MAX_ACES or header.AclSize < ctypes.sizeof(_ACL):
                raise CredentialAclUnavailable("DACL header is implausible")
            aces = []
            used = ctypes.sizeof(_ACL)
            for index in range(header.AceCount):
                pointer = ctypes.c_void_p()
                if not api.adv.GetAce(dacl, index, ctypes.byref(pointer)) or not pointer.value:
                    raise api.fail(f"GetAce({index})")
                ace_header = ctypes.cast(pointer, ctypes.POINTER(_ACE_HEADER)).contents
                size = int(ace_header.AceSize)
                used += size
                if size < _ACE_HEADER_SIZE or used > header.AclSize:
                    raise CredentialAclUnavailable("ACE size runs past the DACL")
                if ace_header.AceType in (ACCESS_ALLOWED_ACE_TYPE, ACCESS_DENIED_ACE_TYPE):
                    if size < _ALLOW_DENY_SID_OFFSET + 8:
                        raise CredentialAclUnavailable("allow/deny ACE is too small")
                    mask = ctypes.c_uint32.from_address(pointer.value + _ACE_HEADER_SIZE).value
                    sid = api.sid_string(pointer.value + _ALLOW_DENY_SID_OFFSET,
                                         limit=size - _ALLOW_DENY_SID_OFFSET)
                else:
                    # Object/callback/conditional ACEs: the judgment refuses the type itself.
                    mask, sid = 0, ""
                aces.append(Ace(int(ace_header.AceType), int(ace_header.AceFlags), int(mask), sid))
        return owner_sid, aces, api.process_sid()
    finally:
        if descriptor.value:
            api.k32.LocalFree(descriptor)
        api.k32.CloseHandle(ctypes.c_void_p(value))


def credential_file_private(path: str | os.PathLike[str]) -> tuple[bool, str]:
    """Judge a credential file; every failure to read the descriptor refuses."""
    try:
        owner, dacl, process = read_credential_security(path)
    except CredentialAclUnavailable as exc:
        return False, f"security descriptor could not be verified: {exc}"
    except (OSError, ValueError, TypeError):
        return False, "security descriptor could not be verified"
    return evaluate_credential_acl(owner, dacl, process)
