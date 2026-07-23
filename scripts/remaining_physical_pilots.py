#!/usr/bin/env python3
"""Run the remaining physical pilots in the safest useful order.

The authoritative seven-proof Stage A gate is re-evaluated first against the
current clean checkout. Agent 3 runs only after that exact-candidate prerequisite
passes. The scheduler pilot then verifies or refreshes its own report. Both child
operators are independently resumable and SHA-bound, so a failed or interrupted
run is safely continued by double-clicking again.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
sys.dont_write_bytecode = True

ROOT = Path(__file__).resolve().parents[1]
STAGE_A_GATE = ROOT / "scripts" / "physical_validation_candidate_gate.py"
STAGE_A_REPORT = ROOT / "validation" / "physical-validation-candidate-final-latest.json"
PILOTS = (
    ("Agent 3 read-only pilot", ROOT / "scripts" / "agent3_readonly_pilot_one_click.py"),
    ("Scheduler M2 physical pilot", ROOT / "scripts" / "scheduler_pilot_wizard.py"),
)


def heading(text: str) -> None:
    print(f"\n{'=' * 72}\n{text}\n{'=' * 72}")


def run_stage_a_gate() -> int:
    """Re-evaluate Stage A; never trust a rolling JSON by presence alone."""
    if not STAGE_A_GATE.is_file():
        print(f"  STOP  Mangler Stage A-evaluator: {STAGE_A_GATE}", file=sys.stderr)
        return 2
    heading("Forudsætning — verificér Stage A på den aktuelle kandidat")
    result = subprocess.run(
        [
            sys.executable,
            str(STAGE_A_GATE),
            "--report",
            str(STAGE_A_REPORT),
        ],
        cwd=ROOT,
        env=os.environ.copy(),
        check=False,
    )
    return int(result.returncode)


def run_pilot(label: str, path: Path) -> int:
    if not path.is_file():
        print(f"  STOP  Mangler pilotoperator: {path}", file=sys.stderr)
        return 2
    heading(label)
    result = subprocess.run(
        [sys.executable, str(path)],
        cwd=ROOT,
        env=os.environ.copy(),
        check=False,
    )
    return int(result.returncode)


def main() -> int:
    os.chdir(ROOT)
    heading("Kaliv — resterende fysiske piloter")
    print("  Ét dobbeltklik. Stage A verificeres først på den aktuelle kandidat.")
    print("  Derefter køres Agent 3 og til sidst Scheduler-piloten.")
    print("  Ingen merge, release eller produktionsaktivering kan udføres herfra.")

    stage_a_code = run_stage_a_gate()
    if stage_a_code != 0:
        print(
            f"\n  SIKKERT STOP  Stage A-gaten returnerede exit code {stage_a_code}.",
            file=sys.stderr,
        )
        print(
            "  Kør START_STAGE_A_TEST.cmd til den syv-bevis-gate er grøn på samme kandidat.",
            file=sys.stderr,
        )
        return stage_a_code

    print("  OK  Stage A er grønt og exact-candidate-bundet.")
    for label, path in PILOTS:
        code = run_pilot(label, path)
        if code != 0:
            print(f"\n  SIKKERT STOP  {label} returnerede exit code {code}.", file=sys.stderr)
            print("  Ret det viste problem og dobbeltklik igen; beståede trin genbruges.", file=sys.stderr)
            return code

    heading("ALLE RESTERENDE PILOTER ER BESTÅET")
    print("  Gennemgå de tre SHA-bundne rapporter før nogen integrationsbeslutning:")
    print("  validation\\physical-validation-candidate-final-latest.json")
    print("  validation\\agent3-readonly-pilot-latest.json")
    print("  validation\\scheduler-pilot-latest.json")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\n  SIKKERT STOP  Afbrudt af operatøren.", file=sys.stderr)
        raise SystemExit(1)
