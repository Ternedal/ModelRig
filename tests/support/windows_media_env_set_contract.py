"""Real-Windows contract for scripts/media_env_set.py: the env file's access list survives.

Run on the Windows gate: ``PYTHONPATH=worker python tests/support/windows_media_env_set_contract.py``.

#2479 review (Codex P2): modelrig.env can hold secrets. The tool makes two new files beside it
-- a backup and the replacement -- and a new file takes its access list from the directory. In
a directory other users may read, both would expose what the original's own list protected.

The case: a directory that grants BUILTIN\\Users read to everything created in it, holding an
env file whose inheritance is removed and which only the process user may read. A plain new
file there is readable by Users (the control); after the tool has run, neither the replaced
file nor the backup may be. Judged by the repository's own DACL reader (credential_acl_windows).
No real credential is involved.
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "worker"))
sys.path.insert(0, str(ROOT / "scripts"))

USERS = "S-1-5-32-545"
passed = failed = 0


def check(condition: bool, name: str) -> None:
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS: {name}")
    else:
        failed += 1
        print(f"  FAIL: {name}")


def icacls(path: Path, *args: str) -> str:
    result = subprocess.run(["icacls", str(path), *args], capture_output=True, text=True, timeout=30)
    if result.returncode != 0:
        raise RuntimeError(f"icacls {' '.join(args)} failed: {result.stdout} {result.stderr}")
    return result.stdout


def main() -> int:
    if os.name != "nt":
        print("SKIP: Windows-only contract")
        return 0
    import media_env_set as tool
    from app.credential_acl_windows import credential_file_private, read_credential_security

    def diag(path: Path) -> None:
        print("    diag icacls: " + " | ".join(line.strip() for line in icacls(path).splitlines() if line.strip()))

    with tempfile.TemporaryDirectory(prefix="kaliv-env-set-") as td:
        shared = Path(td) / "shared"
        shared.mkdir()
        icacls(shared, "/grant", f"*{USERS}:(OI)(CI)(R)")
        control = shared / "control.txt"
        control.write_bytes(b"x")
        ok, reason = credential_file_private(control)
        check(ok is False, f"control: a plain new file in this directory is readable by Users ({reason})")

        env = shared / "modelrig.env"
        original = "# Blåbær\r\nKALIV_MEDIA_INTERNAL_SECRET=dummy-not-a-secret\r\nKALIV_COMFY_HOST_MEMORY_GIB=64\r\n".encode("cp1252")
        env.write_bytes(original)
        _owner, _dacl, process = read_credential_security(env)
        icacls(env, "/inheritance:r", "/grant:r", f"*{process}:(F)")
        ok, reason = credential_file_private(env)
        check(ok is True, f"the env file starts private ({reason})")

        code = tool.main(["--file", str(env), "KALIV_COMFY_HOST_MEMORY_GIB=40", "KALIV_VIDEO_TOOL_PROFILE=a,b"])
        check(code == 0, "the tool runs on Windows: exit 0")
        after = env.read_bytes()
        check(b"KALIV_COMFY_HOST_MEMORY_GIB=40\r\n" in after and b"=64" not in after and "Blåbær".encode("cp1252") in after,
              "the keys are set and the other bytes are kept")
        ok, reason = credential_file_private(env)
        check(ok is True, f"the replaced env file is still private ({reason})")
        if not ok:
            diag(env)
        backups = sorted(shared.glob("modelrig.env.bak-*"))
        check(len(backups) == 1 and backups[0].read_bytes() == original, "one backup, byte-identical to the original")
        for backup in backups:
            ok, reason = credential_file_private(backup)
            check(ok is True, f"the backup is private too, not readable by Users ({reason})")
            if not ok:
                diag(backup)
        check(not list(shared.glob("*.tmp-*")), "no temporary file is left behind")

        # A second run: the first backup stays, and is still private.
        code = tool.main(["--file", str(env), "KALIV_COMFY_HOST_MEMORY_GIB=48"])
        backups = sorted(shared.glob("modelrig.env.bak-*"))
        check(code == 0 and len(backups) == 2 and any(b.read_bytes() == original for b in backups),
              "a second run adds a backup and keeps the first")
        check(all(credential_file_private(b)[0] for b in backups) and credential_file_private(env)[0],
              "after the second run every copy is still private")

        # An env file that simply inherits from its directory keeps doing so (no surprise lock-out).
        plain = shared / "plain.env"
        plain.write_bytes(b"A=1\r\n")
        before = icacls(plain).replace(str(plain), "").split()
        code = tool.main(["--file", str(plain), "A=2"])
        after_list = icacls(plain).replace(str(plain), "").split()
        check(code == 0 and plain.read_bytes() == b"A=2\r\n", "an inheriting env file is updated")
        check(before == after_list, "and its access list is the same as before")
        if before != after_list:
            print(f"    diag before={before}\n    diag after ={after_list}")

    print(f"\n===== WINDOWS MEDIA ENV SET CONTRACT: {passed} passed, {failed} failed =====")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
