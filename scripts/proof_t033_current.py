#!/usr/bin/env python3
"""Current-head adapter for the existing T-033 physical backup/restore proof."""
from __future__ import annotations
import os, subprocess, sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"scripts"))
import agent3_memory_protected_backup_physical as op  # noqa: E402

def cap(*args:str)->str:
    p=subprocess.run(args,cwd=ROOT,capture_output=True,text=True,check=False)
    if p.returncode: raise RuntimeError((p.stderr or p.stdout).strip())
    return p.stdout.strip()

def exact(*, sync_remote:bool)->str:
    dirty=cap("git","status","--porcelain")
    if dirty: raise RuntimeError("Working tree er ikke ren:\n"+dirty)
    branch=cap("git","branch","--show-current")
    if not branch: raise RuntimeError("Detached HEAD afvises")
    if sync_remote:
        cap("git","fetch","--quiet","origin",branch)
        cap("git","pull","--ff-only","origin",branch)
    sha=cap("git","rev-parse","HEAD")
    if sync_remote and sha != cap("git","rev-parse",f"origin/{branch}"):
        raise RuntimeError("HEAD/remote mismatch")
    return sha

def main()->int:
    os.chdir(ROOT)
    command=sys.argv[1] if len(sys.argv)>1 else ""
    # A foreign Windows SID must not need GitHub credentials. Only prepare may
    # move to the remote branch tip; probe/collect verify the already-bound local tree.
    exact(sync_remote=(command=="prepare"))
    branch=cap("git","branch","--show-current"); version=(ROOT/"VERSION").read_text(encoding="utf-8").strip()
    op.BRANCH,op.VERSION=branch,version
    op.stage.BRANCH,op.stage.VERSION=branch,version
    op.stage.ensure_candidate=lambda: exact(sync_remote=True)
    return int(op.main())
if __name__=="__main__":
    try: raise SystemExit(main())
    except KeyboardInterrupt: raise SystemExit(130)
    except Exception as exc:
        print(f"T-033 BLOCKED: {type(exc).__name__}: {exc}",file=sys.stderr); raise SystemExit(2)
