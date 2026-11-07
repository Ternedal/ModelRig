"""Real-Windows contract for the operator preflight (R17; ChatGPT 6689780350 P2).

Run on the Windows gate: ``PYTHONPATH=worker python tests/support/windows_media_preflight_contract.py``.
Real SIDs (this process, a child process), real ACLs set with icacls by SID, a real SQLite file.
This proves the preflight reads what it claims to on Windows. It is not a physical rig
qualification: the runner has no external publication disk, so that check must fail closed here.
"""
from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "worker"))

from app.media_preflight import current_account, preflight, process_account  # noqa: E402

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


def icacls(path: Path, *args: str) -> None:
    result = subprocess.run(["icacls", str(path), *args], capture_output=True, text=True, timeout=30)
    if result.returncode != 0:
        raise RuntimeError(f"icacls {' '.join(args)} failed: {result.stdout} {result.stderr}")


def main() -> int:
    if os.name != "nt":
        print("windows_media_preflight_contract: Windows only")
        return 0
    me = current_account()
    check(me.startswith("S-1-5-"), f"this process's account is a user SID ({me})")
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    try:
        check(process_account(child.pid) == me, "a child process started by this one runs as the same SID")
        check(process_account(os.getpid()) == me, "the token of this process, read by pid, is the same SID")
        check(process_account(4) is None or process_account(4) == "S-1-5-18",
              "the System process (pid 4) is not readable or is SYSTEM, never this user")
        with tempfile.TemporaryDirectory(prefix="kaliv-preflight-") as td:
            td = os.path.realpath(td)  # %TEMP% can be an 8.3 alias; the work area must be canonical
            work = Path(td) / "work"
            (work / "state").mkdir(parents=True)
            icacls(work, "/inheritance:r", "/grant:r", f"*{me}:(OI)(CI)F",
                   "/grant", "*S-1-5-18:(OI)(CI)F", "/grant", "*S-1-5-32-544:(OI)(CI)F")
            icacls(work / "state", "/reset")
            db = work / "state" / "jobs.sqlite3"
            sqlite3.connect(db).close()
            volume = Path(td) / "not-a-disk"
            volume.mkdir()
            report = preflight(work_root=str(work), job_db=str(db), volume_root=str(volume),
                               volume_id="kaliv-preflight-ci-01", pids=[os.getpid(), child.pid],
                               min_free_gib_work=0, min_free_gib_volume=0, env={})
            results = {c["check"]: c for c in report["checks"]}
            for c in report["checks"]:
                print(f"    diag: {c['check']} ok={c['ok']} {c['detail']}")
            check(results["work_area"]["ok"], "a private work area passes (real DACL)")
            check(results["private:jobs.sqlite3"]["ok"], "a job database created inside it is private")
            check(results[f"same_account:pid {child.pid}"]["ok"], "the child process passes the account check")
            check(not results["publication_volume"]["ok"]
                  and "media_volume" in str(results["publication_volume"]["detail"]),
                  "a folder that is not a mounted disk fails the volume check (fail closed)")
            check(report["ok"] is False, "so the preflight as a whole fails on the runner")
            icacls(db, "/grant", f"*{USERS}:(R)")
            report = preflight(work_root=str(work), job_db=str(db), volume_root=str(volume),
                               volume_id="kaliv-preflight-ci-01", min_free_gib_work=0, min_free_gib_volume=0, env={})
            results = {c["check"]: c for c in report["checks"]}
            check(not results["private:jobs.sqlite3"]["ok"], "a job database Users can read is refused")
    finally:
        child.kill()
        child.wait(30)
    print(f"\n===== Windows media preflight contract: {passed} passed, {failed} failed =====")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
