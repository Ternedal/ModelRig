#!/usr/bin/env python3
"""Current-head adapter for the repository's retained Stage A one-click campaign."""
from __future__ import annotations
import os, subprocess, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import stage_a_one_click as stage  # noqa: E402

def cap(*args: str) -> str:
    p = subprocess.run(args, cwd=ROOT, capture_output=True, text=True, check=False)
    if p.returncode: raise stage.WizardError((p.stderr or p.stdout).strip())
    return p.stdout.strip()

def ensure_current() -> str:
    if os.name != "nt": raise stage.WizardError("Stage A må kun køres på Windows-riggen")
    dirty = cap("git", "status", "--porcelain")
    if dirty: raise stage.WizardError("Working tree er ikke ren:\n" + dirty)
    branch = cap("git", "branch", "--show-current")
    if not branch: raise stage.WizardError("Detached HEAD afvises; brug en navngivet branch")
    # Never switch branch. Update exactly the checkout the operator selected.
    cap("git", "fetch", "--quiet", "origin", branch)
    cap("git", "pull", "--ff-only", "origin", branch)
    sha = cap("git", "rev-parse", "HEAD")
    remote = cap("git", "rev-parse", f"origin/{branch}")
    if sha != remote: raise stage.WizardError("Lokal HEAD matcher ikke origin/" + branch)
    version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    if version != stage.VERSION: raise stage.WizardError(f"VERSION er {version}, forventede {stage.VERSION}")
    stage.ok(f"Aktuel kandidat {version} på {sha}")
    return sha

def voice_current(planner: str) -> None:
    stage.heading("Fysisk voice-bevis — guidet og automatisk")
    stage.run(["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
               str(ROOT / "scripts" / "stage-a-voice-test.ps1"), "-PlannerModel", planner])

def scheduler_current(planner: str, state: dict) -> None:
    del planner, state
    stage.heading("Fysisk scheduler-bevis — én Pixel-godkendelse")
    stage.run([sys.executable, str(ROOT / "scripts" / "proof_scheduler_current.py")])

def main() -> int:
    os.chdir(ROOT)
    branch = cap("git", "branch", "--show-current")
    version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    stage.BRANCH, stage.VERSION = branch, version
    stage.ensure_candidate = ensure_current
    stage.run_voice = voice_current
    stage.run_scheduler = scheduler_current
    return int(stage.main())

if __name__ == "__main__":
    try: raise SystemExit(main())
    except KeyboardInterrupt: raise SystemExit(130)
    except Exception as exc:
        print(f"STAGE A CURRENT-HEAD BLOCKED: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise SystemExit(2)
