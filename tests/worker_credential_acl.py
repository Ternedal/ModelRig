"""Contract for worker/app/credential_acl.py (Windows credential-file DACL judgment).

Synthetic owners/DACLs only: no secrets, no Windows, no file system. Pins the
accept cases and every refusal rule from docs/T038_WINDOWS_TOKEN_ACL_DESIGN.md,
and that the module is not yet wired into any loader.
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "worker"))
sys.path.insert(0, str(ROOT / "tests" / "support"))

from app.credential_acl import (  # noqa: E402
    ADMINISTRATORS_SID,
    SYSTEM_SID,
    Ace,
    FILE_READ_DATA,
    GENERIC_ALL,
    GENERIC_READ,
    WRITE_DAC,
    WRITE_OWNER,
    evaluate_credential_acl,
)
from source_code import code_of  # noqa: E402

ME = "S-1-5-21-1111111111-2222222222-3333333333-1001"
OTHER_USER = "S-1-5-21-1111111111-2222222222-3333333333-1002"
USERS = "S-1-5-32-545"
AUTHENTICATED_USERS = "S-1-5-11"
EVERYONE = "S-1-1-0"
INHERITED = 0x10
FULL = 0x001F_01FF  # FILE_ALL_ACCESS
READ = 0x0012_0089  # FILE_GENERIC_READ

passed = failed = 0


def check(condition: bool, name: str) -> None:
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS: {name}")
    else:
        failed += 1
        print(f"  FAIL: {name}")


def allow(sid: str, mask: int = FULL, flags: int = 0) -> Ace:
    return Ace(0, flags, mask, sid)


def deny(sid: str, mask: int = FULL) -> Ace:
    return Ace(1, 0, mask, sid)


def ok(owner, dacl, process=ME) -> bool:
    return evaluate_credential_acl(owner, dacl, process)[0]


print("== accepted")
check(ok(ME, [allow(ME)]), "only the process user")
check(ok(ME, [allow(ME), allow(SYSTEM_SID), allow(ADMINISTRATORS_SID)]),
      "process user + SYSTEM + Administrators (the usual locked-down file)")
check(ok(ADMINISTRATORS_SID, [allow(ME, READ)]), "owned by Administrators, readable by the process user")
check(ok(ME, [allow(ME), allow(USERS, 0x0010_0000)]),
      "another principal with SYNCHRONIZE only cannot read or re-permission")
check(ok(ME, [allow(ME), deny(EVERYONE)]), "a deny ACE does not make a private file unacceptable")

print("== refused")
check(not ok(ME, None), "NULL DACL (everyone full access)")
check(not ok(OTHER_USER, [allow(ME)]), "owned by another user")
for name, sid in (("Users", USERS), ("Authenticated Users", AUTHENTICATED_USERS),
                  ("Everyone", EVERYONE), ("another user", OTHER_USER)):
    check(not ok(ME, [allow(ME), allow(sid, READ)]), f"{name} can read")
check(not ok(ME, [allow(ME), allow(USERS, READ, INHERITED)]), "an INHERITED Users:R is refused like an explicit one")
check(not ok(ME, [allow(ME), allow(OTHER_USER, WRITE_DAC)]), "another user can rewrite the DACL (WRITE_DAC)")
check(not ok(ME, [allow(ME), allow(OTHER_USER, WRITE_OWNER)]), "another user can take ownership (WRITE_OWNER)")
check(not ok(ME, [allow(ME), allow(USERS, GENERIC_READ)]), "GENERIC_READ for Users")
check(not ok(ME, [allow(ME), allow(USERS, GENERIC_ALL)]), "GENERIC_ALL for Users")
check(not ok(ME, [allow(ME), allow(USERS, FILE_READ_DATA)]), "bare FILE_READ_DATA for Users")
check(not ok(ME, [deny(USERS, READ), allow(USERS, READ), allow(ME)]),
      "a deny ACE before an allow does not rescue a readable file (allow ACEs decide)")
check(not ok(ME, [allow(ME), Ace(5, 0, READ, USERS)]), "an object/callback ACE type is not understood")
check(not ok(ME, [allow(ME), Ace(0, 0, READ, "not-a-sid")]), "a malformed principal")
check(not ok(ME, [allow(ME), Ace(0, 0, -1, USERS)]), "an invalid access mask")
check(not ok(ME, [allow(ME), "garbage"]), "an entry that is not an ACE")
check(not ok(ME, 12345), "a DACL that cannot be iterated")
check(not ok(None, [allow(ME)]), "unknown owner")
check(not ok(ME, [allow(ME)], process=None), "unknown process user")
check(not ok(ME, [allow(ME)], process="S-1-5-21-x"), "malformed process user SID")

reason = evaluate_credential_acl(ME, [allow(ME), allow(EVERYONE, READ)], ME)[1]
check("another principal" in reason and ME not in reason, "the refusal reason names no SID")

print("== not wired yet (no behaviour change in this step)")
for rel in ("worker/app/home_assistant_provider_transport.py", "worker/app/riggate_provider_transport.py",
            "worker/app/github_connector_transport.py"):
    check("credential_acl" not in code_of(ROOT / rel), f"{rel} does not call it yet")
tree = ast.parse(code_of(ROOT / "worker" / "app" / "credential_acl.py"))
imported = {alias.name.split(".")[0] for node in ast.walk(tree) if isinstance(node, (ast.Import, ast.ImportFrom))
            for alias in (node.names if isinstance(node, ast.Import) else [ast.alias(node.module or "")])}
check(imported <= {"__future__", "dataclasses", "typing"}, f"the judgment imports nothing that reads the OS ({sorted(imported)})")
calls = {node.func.id for node in ast.walk(tree) if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)}
check("open" not in calls and "exec" not in calls and "eval" not in calls, "the judgment opens nothing and runs no code")

print(f"\n===== CREDENTIAL ACL JUDGMENT: {passed} passed, {failed} failed =====")
raise SystemExit(1 if failed else 0)
