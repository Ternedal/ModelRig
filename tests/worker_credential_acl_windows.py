"""Portable contract for worker/app/credential_acl_windows.py (step 2, not wired).

Runs everywhere. The real descriptor reads are proven on the Windows runner by
tests/support/windows_credential_acl_contract.py; this file pins what holds on
every OS: outside Windows every read refuses, every failure of the reader
becomes a refusal, a good descriptor is judged by credential_acl, and the
reader opens by handle with READ_CONTROL only and never follows reparse points.
"""
from __future__ import annotations

import ast
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "worker"))
sys.path.insert(0, str(ROOT / "tests" / "support"))

import app.credential_acl_windows as reader  # noqa: E402
from app.credential_acl import Ace  # noqa: E402
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
create_calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                and n.func.attr == "CreateFileW"]
check(len(create_calls) == 1, "exactly one CreateFileW call")
args = ast.unparse(create_calls[0]) if create_calls else ""
check("READ_CONTROL" in args and "GENERIC_READ" not in args and "FILE_READ_DATA" not in args,
      "the file is opened for READ_CONTROL only, never for its contents")
check("FILE_FLAG_OPEN_REPARSE_POINT" in args, "the open never follows a symlink or junction")
check("GetSecurityInfo" in source and "GetNamedSecurityInfo" not in source,
      "the descriptor is read from the handle, not looked up again by name")
check("FILE_ATTRIBUTE_REPARSE_POINT" in source, "a reparse point is refused before opening")

print("== not wired yet")
for rel in ("worker/app/home_assistant_provider_transport.py", "worker/app/riggate_provider_transport.py",
            "worker/app/github_connector_transport.py"):
    check("credential_acl" not in code_of(ROOT / rel), f"{rel} does not call it yet")

print(f"\n===== CREDENTIAL ACL WINDOWS READER (portable): {passed} passed, {failed} failed =====")
raise SystemExit(1 if failed else 0)
