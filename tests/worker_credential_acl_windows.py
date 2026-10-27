"""Portable contract for worker/app/credential_acl_windows.py (steps 2 and 3).

Runs everywhere. The real descriptor reads are proven on the Windows runner by
tests/support/windows_credential_acl_contract.py; this file pins what holds on
every OS: outside Windows every read refuses, every failure of the reader
becomes a refusal, a good descriptor is judged by credential_acl, reparse
points are never followed, and (step 3) the credential bytes are read from the
same handle that was judged -- only after the judgment accepted it.
"""
from __future__ import annotations

import ast
import ctypes
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "worker"))
sys.path.insert(0, str(ROOT / "tests" / "support"))

import app.credential_acl_windows as reader  # noqa: E402
from app.credential_acl import Ace  # noqa: E402
from app.credential_file import CredentialFileRefused  # noqa: E402
from source_code import code_of  # noqa: E402

ME = "S-1-5-21-1111111111-2222222222-3333333333-1001"
passed = failed = 0


def check(condition: bool, name: str) -> None:
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS: {name}")
    else:
        failed += 1
        print(f"  FAIL: {name}")


print("== outside Windows nothing is read and everything refuses")
if os.name != "nt":
    with tempfile.NamedTemporaryFile() as handle:
        try:
            reader.read_credential_security(handle.name)
            check(False, "read_credential_security refuses off Windows")
        except reader.CredentialAclUnavailable:
            check(True, "read_credential_security refuses off Windows")
        ok, reason = reader.credential_file_private(handle.name)
        check(ok is False and "could not be verified" in reason, "credential_file_private refuses off Windows")
else:
    check(True, "running on Windows: real reads are covered by the Windows contract")

print("== every reader failure becomes a refusal; a good descriptor is judged")
real = reader.read_credential_security
try:
    for exc in (reader.CredentialAclUnavailable("x"), OSError("x"), ValueError("x"), TypeError("x")):
        reader.read_credential_security = lambda path, e=exc: (_ for _ in ()).throw(e)
        check(reader.credential_file_private("C:/x")[0] is False, f"{type(exc).__name__} from the reader refuses")
    reader.read_credential_security = lambda path: (ME, [Ace(0, 0, 0x1F01FF, ME)], ME)
    check(reader.credential_file_private("C:/x")[0] is True, "a private descriptor is accepted via the judgment")
    reader.read_credential_security = lambda path: (ME, None, ME)
    check(reader.credential_file_private("C:/x")[0] is False, "a NULL DACL from the reader refuses")
    reader.read_credential_security = lambda path: (ME, [Ace(0, 0, 0x120089, "S-1-5-32-545")], ME)
    check(reader.credential_file_private("C:/x")[0] is False, "Users:R from the reader refuses")
finally:
    reader.read_credential_security = real

print("== how the reader touches the file (source)")
source = code_of(ROOT / "worker" / "app" / "credential_acl_windows.py")
tree = ast.parse(source)
functions = {n.name: n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}


def calls_in(name: str, attr: str) -> list[ast.Call]:
    node = functions.get(name)
    return [n for n in ast.walk(node) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
            and n.func.attr == attr] if node else []


def open_args(name: str) -> str:
    found = [n for n in ast.walk(functions[name]) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
             and n.func.id == "_open_regular"] if name in functions else []
    return ast.unparse(found[0]) if len(found) == 1 else ""


all_creates = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
               and n.func.attr == "CreateFileW"]
check(len(all_creates) == 1 and len(calls_in("_open_regular", "CreateFileW")) == 1,
      "exactly one CreateFileW call, inside _open_regular")
create = ast.unparse(all_creates[0]) if all_creates else ""
check("FILE_FLAG_OPEN_REPARSE_POINT" in create, "the open never follows a symlink or junction")
descriptor_only = open_args("read_credential_security")
check("READ_CONTROL" in descriptor_only and "FILE_READ_DATA" not in descriptor_only
      and "GENERIC_READ" not in descriptor_only,
      "read_credential_security opens for READ_CONTROL only, never for the contents")
reading = open_args("read_private_credential_windows")
check("FILE_READ_DATA" in reading and "READ_CONTROL" in reading and "GENERIC_READ" not in reading,
      "read_private_credential_windows opens one handle for FILE_READ_DATA | READ_CONTROL")
check(reading.rstrip(")").endswith("FILE_SHARE_READ") and "FILE_SHARE_WRITE" not in reading
      and "FILE_SHARE_DELETE" not in reading,
      "while it is judged and read, nobody can write, rename or delete the file")
check("GetSecurityInfo" in source and "GetNamedSecurityInfo" not in source,
      "the descriptor is read from the handle, not looked up again by name")
opener = ast.unparse(functions["_open_regular"]) if "_open_regular" in functions else ""
order = [opener.find(marker) for marker in ("api.k32.CreateFileW(", "GetFileInformationByHandle(",
                                              "info.dwFileAttributes & FILE_ATTRIBUTE_REPARSE_POINT")]
check(all(i >= 0 for i in order) and order == sorted(order),
      "the OPENED handle's attributes are checked for a reparse point (Codex P2 4387779979)")
check("info.dwFileAttributes & FILE_ATTRIBUTE_DIRECTORY" in opener, "an opened directory is refused")

print("== step 3: judged and read through one handle (fake Windows API)")
INVALID = reader.INVALID_HANDLE_VALUE
REGULAR = 0x20  # FILE_ATTRIBUTE_ARCHIVE
TOKEN = b"t" * 40 + b"\r\n"


class FakeK32:
    def __init__(self, *, attrs=REGULAR, handle_attrs=REGULAR, size=len(TOKEN), data=TOKEN, create_error=0,
                 read_ok=True):
        self.attrs, self.handle_attrs, self.size, self.data = attrs, handle_attrs, size, data
        self.create_error, self.read_ok, self.pos, self.calls = create_error, read_ok, 0, []

    def GetFileAttributesW(self, name):
        self.calls.append("GetFileAttributesW")
        return self.attrs

    def CreateFileW(self, name, access, share, security, disposition, flags, template):
        self.calls.append(("CreateFileW", access, share, flags))
        return INVALID if self.create_error else 0x1234

    def GetFileInformationByHandle(self, handle, pointer):
        self.calls.append("GetFileInformationByHandle")
        info = pointer._obj
        info.dwFileAttributes, info.nFileSizeHigh, info.nFileSizeLow = self.handle_attrs, self.size >> 32, self.size & 0xFFFFFFFF
        return 1

    def ReadFile(self, handle, address, wanted, got, overlapped):
        self.calls.append("ReadFile")
        if not self.read_ok:
            return 0
        chunk = self.data[self.pos:self.pos + min(wanted, 7)]
        ctypes.memmove(address, chunk, len(chunk))
        got._obj.value = len(chunk)
        self.pos += len(chunk)
        return 1

    def CloseHandle(self, handle):
        self.calls.append("CloseHandle")
        return 1


class FakeApi:
    def __init__(self, **kwargs):
        self.k32 = FakeK32(**kwargs)

    def last_error(self):
        return self.k32.create_error

    def process_sid(self):
        self.k32.calls.append("process_sid")
        return ME


PRIVATE = (ME, [Ace(0, 0, 0x1F01FF, ME)])
BROAD = (ME, [Ace(0, 0, 0x1F01FF, ME), Ace(0, 0x10, 0x120089, "S-1-5-32-545")])


def run(security=PRIVATE, max_bytes=4098, **kwargs):
    api = FakeApi(**kwargs)
    real_security = reader._security_of_handle

    def fake_security(api_, value):
        api_.k32.calls.append("GetSecurityInfo")
        if isinstance(security, Exception):
            raise security
        return security

    reader._security_of_handle = fake_security
    try:
        return reader.read_private_credential_windows("C:/rig/ha.token", max_bytes, api=api), None, api.k32.calls
    except CredentialFileRefused as exc:
        return None, exc.kind, api.k32.calls
    finally:
        reader._security_of_handle = real_security


def names(calls):
    return [c if isinstance(c, str) else c[0] for c in calls]


data, kind, calls = run()
check(data == TOKEN and kind is None, "a private file's bytes come back (read in chunks)")
check(names(calls)[:5] == ["GetFileAttributesW", "CreateFileW", "GetFileInformationByHandle", "GetSecurityInfo",
                           "process_sid"] and names(calls)[-1] == "CloseHandle",
      "order: attributes, open, handle check, descriptor, judgment -- then ReadFile, then close")
opened = [c for c in calls if not isinstance(c, str)][0]
check(opened[1] == reader.FILE_READ_DATA | reader.READ_CONTROL | reader.FILE_READ_ATTRIBUTES
      and opened[2] == reader.FILE_SHARE_READ and opened[3] == reader.FILE_FLAG_OPEN_REPARSE_POINT,
      "the one handle: FILE_READ_DATA | READ_CONTROL | FILE_READ_ATTRIBUTES, share read only, no reparse follow")
check(names(calls).count("CreateFileW") == 1, "judgment and read share a single handle")

data, kind, calls = run(security=BROAD)
check(kind == "permissions" and "ReadFile" not in names(calls) and names(calls)[-1] == "CloseHandle",
      "an inherited Users:R ACE refuses as permissions and nothing is read")
data, kind, calls = run(security=reader.CredentialAclUnavailable("GetSecurityInfo failed"))
check(kind == "unverifiable" and "ReadFile" not in names(calls), "an unreadable descriptor refuses, nothing read")
data, kind, calls = run(attrs=reader.FILE_ATTRIBUTE_REPARSE_POINT | REGULAR)
check(kind == "not_regular" and "CreateFileW" not in names(calls), "a symlinked path refuses before opening")
data, kind, calls = run(handle_attrs=reader.FILE_ATTRIBUTE_REPARSE_POINT | REGULAR)
check(kind == "not_regular" and "GetSecurityInfo" not in names(calls) and names(calls)[-1] == "CloseHandle",
      "a symlink swapped in after the name check is caught on the handle and closed")
data, kind, calls = run(handle_attrs=reader.FILE_ATTRIBUTE_DIRECTORY)
check(kind == "not_regular" and "ReadFile" not in names(calls), "a directory refuses")
data, kind, calls = run(attrs=reader.INVALID_FILE_ATTRIBUTES)
check(kind == "unavailable" and "CreateFileW" not in names(calls), "a missing file is unavailable")
data, kind, calls = run(create_error=reader.ERROR_SHARING_VIOLATION)
check(kind == "read" and "GetSecurityInfo" not in names(calls), "a file held open for writing refuses as read")
data, kind, calls = run(create_error=2)
check(kind == "unavailable", "any other open failure is unavailable")
data, kind, calls = run(size=4099)
check(kind == "size" and "GetSecurityInfo" not in names(calls), "an oversized file refuses before the descriptor")
data, kind, calls = run(size=0, data=b"")
check(kind == "size" and "ReadFile" not in names(calls), "an empty file refuses")
data, kind, calls = run(size=len(TOKEN), data=TOKEN + b"x" * 5000)
check(kind == "size" and data is None, "a file that grows past the bound during the read refuses")
data, kind, calls = run(read_ok=False)
check(kind == "read" and names(calls)[-1] == "CloseHandle", "a ReadFile failure refuses and closes")

print("== wired: all three bearer loaders go through credential_file")
for rel in ("worker/app/home_assistant_provider_transport.py", "worker/app/riggate_provider_transport.py",
            "worker/app/github_connector_transport.py"):
    loader = ast.parse(code_of(ROOT / rel))
    imports = [n for n in ast.walk(loader) if isinstance(n, ast.ImportFrom) and n.module == "credential_file"]
    reads = [n for n in ast.walk(loader) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
             and n.func.attr in ("read_bytes", "read_text", "stat")]
    calls_helper = [n for n in ast.walk(loader) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                    and n.func.id == "read_private_credential"]
    check(len(imports) == 1 and len(calls_helper) == 1 and not reads,
          f"{rel} reads its credential only via read_private_credential (no stat/read_bytes of its own)")

print(f"\n===== CREDENTIAL ACL WINDOWS READER (portable): {passed} passed, {failed} failed =====")
raise SystemExit(1 if failed else 0)
