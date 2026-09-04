#!/usr/bin/env python3
"""Run the existing scheduler physical pilot against the current clean checkout."""
from __future__ import annotations
import os, subprocess, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import stage_a_scheduler_pilot_easy as pilot  # noqa: E402

def capture(*args: str) -> str:
    p = subprocess.run(args, cwd=ROOT, capture_output=True, text=True, check=False)
    if p.returncode: raise RuntimeError((p.stderr or p.stdout).strip())
    return p.stdout.strip()

def main() -> int:
    os.chdir(ROOT)
    branch = capture("git", "branch", "--show-current")
    if not branch: raise RuntimeError("detached HEAD is not accepted for physical scheduler proof")
    version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    # Compatibility only: all underlying read/revoke/crash/report gates remain unchanged.
    pilot.CANDIDATE_BRANCH_PREFIX = branch
    pilot.EXPECTED_VERSION = version
    return int(pilot.main())

if __name__ == "__main__":
    try: raise SystemExit(main())
    except KeyboardInterrupt: raise SystemExit(130)
    except Exception as exc:
        print(f"SCHEDULER CURRENT-HEAD BLOCKED: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise SystemExit(2)
