"""Real-Windows contract for the GPU lease directory ACL check (gap G5, #2296).

Run on the Windows gate: ``PYTHONPATH=worker python tests/support/windows_lease_dir_acl_contract.py``.
Each case is a fresh temp directory whose ACL is set with icacls. The reader reads the
real security descriptor through a directory handle, the judgment decides, and the
real gpu_lease entry points must refuse before creating any lock file.
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "worker"))

from app.credential_acl_windows import CredentialAclUnavailable  # noqa: E402
from app.gpu_lease import GpuLeaseError, acquire_executor_lock, acquire_gpu_lease, check_lease_dir  # noqa: E402
from app.lease_dir_acl_windows import lease_dir_private, read_lease_dir_security  # noqa: E402

GPU = "GPU-6a7f0c2e-1b2d-4c3e-8f9a-0123456789ab"
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


def describe(path: Path) -> None:
    try:
        owner, aces, process = read_lease_dir_security(path)
    except CredentialAclUnavailable as exc:
        print(f"    diag: unreadable ({exc})")
        return
    print(f"    diag: owner={owner} process={process}")
    for ace in aces or []:
        print(f"    diag: type={ace.ace_type} flags=0x{ace.flags:02x} mask=0x{ace.mask:08x} sid={ace.sid}")


_DIAG_CHARS = 200


def _one_line(text: str) -> str:
    return " ".join(str(text).split())[:_DIAG_CHARS]


def junction_case(junction: Path, target: Path) -> None:
    """A real NTFS junction to a private directory must be refused, not followed.

    Making the junction is part of the contract: a runner that cannot (no privilege, mklink
    missing or hung) FAILS here, with a bounded one-line diagnostic, instead of skipping and
    passing without proving anything about junctions (#2275 6699231451). `mklink /J` needs no
    admin rights, so on the Windows gate this is expected to succeed."""
    try:
        made = subprocess.run(["cmd", "/c", "mklink", "/J", str(junction), str(target)], capture_output=True,
                              text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired) as exc:
        check(False, f"the junction case can create its junction (mklink /J: {_one_line(type(exc).__name__)})")
        return
    if made.returncode != 0:
        check(False, "the junction case can create its junction "
                     f"(mklink /J rc={made.returncode}: {_one_line(made.stdout)} | {_one_line(made.stderr)})")
        return
    check(lease_dir_private(junction)[0] is False, "a junction to a private directory is refused, not followed")


def main() -> int:
    if os.name != "nt":
        print("SKIP: Windows-only contract")
        return 0
    with tempfile.TemporaryDirectory(prefix="kaliv-lease-acl-") as td:
        root = Path(td)
        owner, dacl, process = read_lease_dir_security(root)
        check(process.startswith("S-1-5-") and owner.startswith("S-1-"), "reads owner and process SIDs of a directory")
        check(isinstance(dacl, list), "reads the directory DACL as a list of ACEs")
        default = lease_dir_private(root)
        print(f"  info: the runner's temp folder shape -> {default}")
        describe(root)
        check(default[0] is True, "a fresh folder under the user's temp (inherited, private) is accepted")

        counter = iter(range(1000))

        def fresh(extra: tuple[str, ...]) -> Path:
            path = root / f"case-{next(counter)}"
            path.mkdir()
            icacls(path, "/inheritance:r", "/grant:r", f"*{process}:(OI)(CI)F")
            if extra:
                icacls(path, *extra)
            return path

        def case(name: str, extra: tuple[str, ...], expected: bool) -> Path:
            path = fresh(extra)
            ok, reason = lease_dir_private(path)
            check(ok is expected, f"{name} -> {'accepted' if expected else 'refused'} ({reason})")
            if ok is not expected:
                describe(path)
            return path

        case("only the process user (inheritance removed)", (), True)
        case("plus SYSTEM and Administrators",
             ("/grant", "*S-1-5-18:(OI)(CI)F", "/grant", "*S-1-5-32-544:(OI)(CI)F"), True)
        case("Users may list and traverse (RX)", ("/grant", f"*{USERS}:(OI)(CI)(RX)"), True)
        case("Users:M", ("/grant", f"*{USERS}:(OI)(CI)(M)"), False)
        case("Everyone may add files (WD)", ("/grant", f"*{EVERYONE}:(WD)"), False)
        case("Everyone may add subdirectories (AD)", ("/grant", f"*{EVERYONE}:(AD)"), False)
        case("Users may delete children (DC)", ("/grant", f"*{USERS}:(DC)"), False)
        case("Users with WRITE_DAC", ("/grant", f"*{USERS}:(WDAC)"), False)
        case("Authenticated Users Modify, inherit-only (the C:\\ shape)",
             ("/grant", f"*{AUTHENTICATED_USERS}:(OI)(CI)(IO)(M)"), False)

        check(lease_dir_private(root / "missing")[0] is False, "a missing directory refuses")
        a_file = root / "a-file"
        a_file.write_bytes(b"x")
        check(lease_dir_private(a_file)[0] is False, "a regular file refuses")

        junction_case(root / "junction", fresh(()))

        # The real lock entry points: refused before any lock file exists, and working when private.
        writable = fresh(("/grant", f"*{USERS}:(OI)(CI)(M)"))
        for name, call in (("check_lease_dir", lambda: check_lease_dir(str(writable))),
                           ("acquire_gpu_lease", lambda: acquire_gpu_lease(GPU, lease_dir=str(writable))),
                           ("acquire_executor_lock", lambda: acquire_executor_lock(GPU, lease_dir=str(writable)))):
            try:
                call()
                check(False, f"{name} refuses a lease directory Users can modify")
            except GpuLeaseError as exc:
                check("lease directory refused" in str(exc), f"{name} refuses a lease directory Users can modify")
        check(list(writable.iterdir()) == [], "no lock file was created in the refused directory")

        private = fresh(())
        lease = acquire_gpu_lease(GPU, lease_dir=str(private))
        check(lease.held, "acquire_gpu_lease works in a private directory")
        lease.release()
        check(not lease.held, "and releases")

    print(f"\n===== Windows lease directory ACL contract: {passed} passed, {failed} failed =====")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
