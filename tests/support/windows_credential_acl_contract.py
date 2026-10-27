"""Real-Windows contract for the credential-file DACL reader (step 2, not wired).

Run on the Windows gate: ``PYTHONPATH=worker python tests/support/windows_credential_acl_contract.py``.
Each case is a fresh temp file holding a dummy token whose ACL is set with
icacls; no real credential is involved. The reader reads the real security
descriptor and credential_acl judges it.
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "worker"))

from app.credential_acl_windows import (  # noqa: E402
    CredentialAclUnavailable,
    credential_file_private,
    read_credential_security,
)

USERS = "S-1-5-32-545"
EVERYONE = "S-1-1-0"
AUTHENTICATED_USERS = "S-1-5-11"
passed = failed = 0


def check(condition: bool, name: str) -> None:
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS: {name}")
    else:
        failed += 1
        print(f"  FAIL: {name}")


def icacls(path: Path, *args: str) -> None:
    result = subprocess.run(["icacls", str(path), *args], capture_output=True, text=True, timeout=30)
    if result.returncode != 0:
        raise RuntimeError(f"icacls {' '.join(args)} failed: {result.stdout} {result.stderr}")


def main() -> int:
    if os.name != "nt":
        print("SKIP: Windows-only contract")
        return 0
    with tempfile.TemporaryDirectory(prefix="kaliv-cred-acl-") as td:
        root = Path(td)
        probe = root / "probe.token"
        probe.write_text("dummy-token-not-a-secret-000000000000\n", encoding="ascii")
        owner, dacl, process = read_credential_security(probe)
        check(process.startswith("S-1-5-") and owner.startswith("S-1-"), "reads owner and process SIDs")
        check(isinstance(dacl, list), "reads the DACL as a list of ACEs")
        print(f"  info: owner={owner} process={process} inherited ACEs={len(dacl or [])}")
        for ace in dacl or []:
            print(f"  info: probe ACE type={ace.ace_type} flags=0x{ace.flags:02x} mask=0x{ace.mask:08x} sid={ace.sid}")

        counter = iter(range(1000))

        def case(name: str, extra: tuple[str, ...], expected: bool) -> None:
            path = root / f"case-{next(counter)}.token"
            path.write_text("dummy-token-not-a-secret-000000000000\n", encoding="ascii")
            icacls(path, "/inheritance:r", "/grant:r", f"*{process}:(R)")
            if extra:
                icacls(path, *extra)
            ok, reason = credential_file_private(path)
            check(ok is expected, f"{name} -> {'accepted' if expected else 'refused'} ({reason})")
            if ok is not expected:
                o, aces, p = read_credential_security(path)
                print(f"    diag: owner={o} process={p}")
                for ace in aces or []:
                    print(f"    diag: type={ace.ace_type} flags=0x{ace.flags:02x} mask=0x{ace.mask:08x} sid={ace.sid}")
                listing = subprocess.run(["icacls", str(path)], capture_output=True, text=True, timeout=30)
                print("    diag icacls: " + " | ".join(line.strip() for line in listing.stdout.splitlines() if line.strip()))

        case("only the process user (inheritance removed)", (), True)
        case("plus SYSTEM and Administrators", ("/grant", "*S-1-5-18:(F)", "/grant", "*S-1-5-32-544:(F)"), True)
        case("Users with only read-control, synchronize, read-attributes",
             ("/grant", f"*{USERS}:(RC,S,RA)"), True)
        case("Users:R", ("/grant", f"*{USERS}:(R)"), False)
        case("Everyone:R", ("/grant", f"*{EVERYONE}:(R)"), False)
        case("Authenticated Users:R", ("/grant", f"*{AUTHENTICATED_USERS}:(R)"), False)
        case("Users:W (tampering, no read)", ("/grant", f"*{USERS}:(W)"), False)
        case("Users:D (delete)", ("/grant", f"*{USERS}:(D)"), False)
        case("Users with WRITE_DAC", ("/grant", f"*{USERS}:(WDAC)"), False)

        missing = root / "missing.token"
        check(credential_file_private(missing)[0] is False, "a missing file refuses")
        check(credential_file_private(root)[0] is False, "a directory refuses")

        target = root / "target.token"
        target.write_text("dummy-token-not-a-secret-000000000000\n", encoding="ascii")
        icacls(target, "/inheritance:r", "/grant:r", f"*{process}:(R)")
        link = root / "link.token"
        try:
            os.symlink(target, link)
        except OSError as exc:
            print(f"  info: symlink not creatable here ({exc.__class__.__name__}); reparse case not exercised")
        else:
            try:
                read_credential_security(link)
                check(False, "a symlink to a private file is refused, not followed")
            except CredentialAclUnavailable:
                check(True, "a symlink to a private file is refused, not followed")
    print(f"\n===== WINDOWS CREDENTIAL ACL CONTRACT: {passed} passed, {failed} failed =====")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
