#!/usr/bin/env python3
"""Bind the existing T-023 physical UI evidence operator to the current checkout."""
from __future__ import annotations
import os, subprocess, sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"scripts"))
import agent3_termination_ui_physical_one_click as op  # noqa: E402

def cap(*a:str)->str:
    p=subprocess.run(a,cwd=ROOT,capture_output=True,text=True,check=False)
    if p.returncode: raise RuntimeError((p.stderr or p.stdout).strip())
    return p.stdout.strip()

def exact()->str:
    dirty=cap("git","status","--porcelain")
    if dirty: raise RuntimeError("Working tree er ikke ren:\n"+dirty)
    branch=cap("git","branch","--show-current")
    if not branch: raise RuntimeError("Detached HEAD afvises")
    cap("git","fetch","--quiet","origin",branch); cap("git","pull","--ff-only","origin",branch)
    sha=cap("git","rev-parse","HEAD")
    if sha!=cap("git","rev-parse",f"origin/{branch}"): raise RuntimeError("HEAD/remote mismatch")
    return sha

def main()->int:
    os.chdir(ROOT); exact()
    branch=cap("git","branch","--show-current"); version=(ROOT/"VERSION").read_text(encoding="utf-8").strip()
    op.BRANCH,op.VERSION=branch,version
    op.stage.BRANCH,op.stage.VERSION=branch,version
    op.stage.ensure_candidate=exact
    # T-023 is an explicit operator-invoked physical proof. Opt the child stack
    # into the dedicated task UI for this proof process only; readiness still
    # requires exact physical evidence and keeps production_activation=false.
    os.environ["KALIV_AGENT3_TASK_UI"]="1"
    return int(op.main())
if __name__=="__main__":
    try: raise SystemExit(main())
    except KeyboardInterrupt: raise SystemExit(130)
    except Exception as exc:
        print(f"T-023 BLOCKED: {type(exc).__name__}: {exc}",file=sys.stderr); raise SystemExit(2)
