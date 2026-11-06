"""Real-Windows contract for the private work area (Anders, 6 Nov 2026, #2275 6686905826).

Run on the Windows gate: ``PYTHONPATH=worker python tests/support/windows_media_work_area_contract.py``.
The real probe only: GetVolumePathNameW, GetDriveTypeW and GetVolumeInformationW for the filesystem,
and the directory security reader with ``credential_acl``'s judgment for privacy. ACLs are set with
icacls, by SID, so a localized Windows behaves the same.
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "worker"))

from app.lease_dir_acl_windows import read_lease_dir_security  # noqa: E402
from app.media_generation_contract import ArtifactSinkUnavailable, MediaWorkArea  # noqa: E402
from app.media_work_area import MediaWorkAreaConfigError, PrivateWorkArea, WorkAreaProbe  # noqa: E402

USERS = "S-1-5-32-545"
EVERYONE = "S-1-1-0"
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


def config_error(root: str) -> str | None:
    try:
        PrivateWorkArea(root)
    except MediaWorkAreaConfigError as exc:
        return str(exc)
    return None


def refused(area: PrivateWorkArea, path: Path) -> str | None:
    try:
        area.require(str(path))
    except ArtifactSinkUnavailable as exc:
        return str(exc)
    return None


def main() -> int:
    if os.name != "nt":
        print("windows_media_work_area_contract: Windows only")
        return 0
    probe = WorkAreaProbe()
    with tempfile.TemporaryDirectory(prefix="kaliv-work-") as td:
        base = Path(td)
        fs, remote = probe.containing_filesystem(str(base))
        check(fs in ("ntfs", "refs") and remote is False, f"the temp folder's volume is local NTFS/ReFS ({fs}, {remote})")
        check(probe.acl_per_entry, "Windows checks the ACL of every folder and file used")

        _, _, process = read_lease_dir_security(base)
        counter = iter(range(1000))

        def private_dir(parent: Path = base) -> Path:
            path = parent / f"case-{next(counter)}"
            path.mkdir()
            icacls(path, "/inheritance:r", "/grant:r", f"*{process}:(OI)(CI)F",
                   "/grant", "*S-1-5-18:(OI)(CI)F", "/grant", "*S-1-5-32-544:(OI)(CI)F")
            return path

        root = private_dir()
        area = PrivateWorkArea(str(root))
        check(isinstance(area, MediaWorkArea), "a private folder is accepted and satisfies MediaWorkArea")
        (root / "comfy" / "output").mkdir(parents=True)
        (root / "state").mkdir()
        check(refused(area, root / "comfy" / "output") is None, "an inherited subfolder is private and accepted")
        check(refused(area, root / "state") is None, "the job database's folder is accepted")

        readable = private_dir()
        icacls(readable, "/grant", f"*{USERS}:(OI)(CI)(RX)")
        reason = config_error(str(readable))
        check(bool(reason) and reason.startswith("media_work_area_not_private"),
              f"a root Users can list and read is refused at start ({reason})")

        inherited = Path(tempfile.gettempdir()).drive + "\\"
        reason = config_error(inherited)
        check(bool(reason) and reason.startswith("media_work_area_not_private"),
              f"the drive root is refused: Authenticated Users can write there ({reason})")

        # A file moved in from a folder Users can read keeps that ACL (same-volume rename).
        outside = base / "outside"
        outside.mkdir()
        icacls(outside, "/grant", f"*{USERS}:(OI)(CI)(RX)")
        (outside / "jobs.sqlite3").write_bytes(b"")
        os.rename(outside / "jobs.sqlite3", root / "state" / "jobs.sqlite3")
        check(refused(area, root / "state" / "jobs.sqlite3") == "media_work_path_not_private",
              "a job database moved in with its old grants is refused")
        (root / "state" / "created-here.sqlite3").write_bytes(b"")
        check(refused(area, root / "state" / "created-here.sqlite3") is None, "a file created here inherits privacy")

        icacls(root / "comfy", "/grant", f"*{USERS}:(OI)(CI)(RX)")
        check(refused(area, root / "comfy" / "output") == "media_work_path_not_private",
              "a subfolder with its own grant for Users is refused, even under a private root")
        check(refused(area, root / "state") is None, "its private sibling is still accepted")

        icacls(root, "/grant", f"*{EVERYONE}:(R)")
        reason = refused(area, root / "state")
        check(bool(reason) and reason.startswith("media_work_area_not_private"), f"a root opened up after start is refused ({reason})")
        icacls(root, "/remove:g", f"*{EVERYONE}")
        check(refused(area, root / "state") is None, "and accepted again once private")

        target = private_dir()
        junction = root / "junction"
        made = subprocess.run(["cmd", "/c", "mklink", "/J", str(junction), str(target)], capture_output=True,
                              text=True, timeout=30)
        if made.returncode != 0:
            print(f"  info: junction not creatable here ({made.stdout.strip()} {made.stderr.strip()}); case skipped")
        else:
            reason = refused(area, junction)
            check(reason in ("media_work_path_link", "media_work_path_not_canonical"),
                  f"a junction inside the work area is refused, never followed ({reason})")
            reason = config_error(str(junction))
            check(reason in ("media_work_area_root_link", "media_work_area_root_not_canonical"),
                  f"a junction as the root is refused ({reason})")

        for bad in ("\\\\server\\share\\work", "\\\\?\\" + str(root), str(root) + ":stream"):
            check(config_error(bad) == "media_work_area_root_invalid", f"{bad!r} is refused by syntax")

    print(f"\n===== Windows media work area contract: {passed} passed, {failed} failed =====")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
