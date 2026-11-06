"""Real-Windows contract for the credential-file DACL reader and its wiring (steps 2 and 3).

Run on the Windows gate: ``PYTHONPATH=worker python tests/support/windows_credential_acl_contract.py``.
Each case is a fresh temp file holding a dummy token whose ACL is set with
icacls; no real credential is involved. The reader reads the real security
descriptor and credential_acl judges it. Step 3: credential_file reads the
bytes through the same handle, and the three bearer loaders refuse a token file
other users can read -- with their existing error messages.
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "worker"))

import app.credential_acl_windows as reader_module  # noqa: E402
from app.credential_acl_windows import (  # noqa: E402
    CredentialAclUnavailable,
    credential_file_private,
    read_credential_security,
)
from app.credential_file import CredentialFileRefused, read_private_credential  # noqa: E402
from app.github_connector_transport import FileGitHubCredentialProvider, GitHubCredentialError  # noqa: E402
from app.home_assistant_provider_transport import HomeAssistantTransportError  # noqa: E402
from app.home_assistant_provider_transport import _load_bearer as ha_load  # noqa: E402
from app.riggate_provider_transport import RigGateTransportError  # noqa: E402
from app.riggate_provider_transport import _load_bearer as rg_load  # noqa: E402

DUMMY = "dummy-token-not-a-secret-000000000000"

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
        probe.write_bytes((DUMMY + "\n").encode("ascii"))  # write_text would add \r on Windows
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

            # Codex P2 4387779979: the path is swapped for a symlink AFTER the name check.
            # Simulate it by making GetFileAttributesW report a plain file for the link.
            class _LyingKernel32:
                def __init__(self, real):
                    self._real = real

                def __getattr__(self, name):
                    return getattr(self._real, name)

                def GetFileAttributesW(self, name):  # noqa: N802
                    return 0x00000020  # FILE_ATTRIBUTE_ARCHIVE: "a regular file"

            real_api = reader_module._Api

            class _RacedApi(real_api):
                def __init__(self):
                    super().__init__()
                    self.k32 = _LyingKernel32(self.k32)

            reader_module._Api = _RacedApi
            try:
                ok, reason = credential_file_private(link)
                check(ok is False and "symlink or junction" in reason,
                      f"a symlink swapped in after the name check is refused on the opened handle ({reason})")
            finally:
                reader_module._Api = real_api

        print("== step 3: credential_file and the three loaders")

        def kind_of(path: Path) -> str | None:
            try:
                read_private_credential(path, max_bytes=4098)
            except CredentialFileRefused as exc:
                return exc.kind
            return None

        def fresh(name: str, *extra: str) -> Path:
            path = root / name
            path.write_bytes((DUMMY + "\n").encode("ascii"))
            icacls(path, "/inheritance:r", "/grant:r", f"*{process}:(R)")
            if extra:
                icacls(path, *extra)
            return path

        private = fresh("s3-private.token")
        check(read_private_credential(private, max_bytes=4098) == (DUMMY + "\n").encode("ascii"),
              "a private token file is read byte for byte through the judged handle")
        check(read_private_credential(probe, max_bytes=4098) == (DUMMY + "\n").encode("ascii"),
              "a file with this runner's inherited temp ACL is accepted (see RUNNER_DACL)")
        broad = fresh("s3-broad.token", "/grant", f"*{USERS}:(R)")
        check(kind_of(broad) == "permissions", "Users:R refuses as permissions")
        check(kind_of(fresh("s3-everyone.token", "/grant", f"*{EVERYONE}:(R)")) == "permissions",
              "Everyone:R refuses as permissions")
        check(kind_of(missing) == "unavailable", "a missing file is unavailable")
        check(kind_of(root) == "not_regular", "a directory is not regular")
        if link.exists() or os.path.lexists(link):
            check(kind_of(link) == "not_regular", "a symlink to a private file is refused, not followed")
        held = fresh("s3-held.token", "/grant", f"*{process}:(M)")  # the writer below needs write access
        with open(held, "a", encoding="ascii"):
            check(kind_of(held) == "read", "a token file held open for writing elsewhere is refused (sharing)")
        check(kind_of(held) is None, "the same file is read once the writer has closed it")

        for name, load, error in (("Home Assistant", ha_load, HomeAssistantTransportError),
                                  ("RigGate", rg_load, RigGateTransportError)):
            check(load(private) == DUMMY, f"{name}: a private token loads on Windows")
            try:
                load(broad)
                check(False, f"{name}: Users:R is refused on Windows")
            except error as exc:
                check(str(exc) == f"{name} credential file permissions are too broad",
                      f"{name}: Users:R is refused on Windows with the existing message")
        check(FileGitHubCredentialProvider(account="Ternedal", token_file=private).bearer_token() == DUMMY,
              "GitHub: a private token loads on Windows")
        try:
            FileGitHubCredentialProvider(account="Ternedal", token_file=broad).bearer_token()
            check(False, "GitHub: Users:R is refused on Windows")
        except GitHubCredentialError as exc:
            check(str(exc) == "GitHub credential file permissions are too broad",
                  "GitHub: Users:R is refused on Windows with the existing message")
    print(f"\n===== WINDOWS CREDENTIAL ACL CONTRACT: {passed} passed, {failed} failed =====")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
