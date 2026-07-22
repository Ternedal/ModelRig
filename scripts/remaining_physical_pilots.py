#!/usr/bin/env python3
"""Run the remaining physical pilots in the safest useful order.

Agent 3 runs first because its exact-head stack may leave backend/worker windows
open for review. The scheduler pilot can reuse the healthy backend and owns its
separate controlled worker. Both child operators are independently resumable and
SHA-bound, so a failed or interrupted run is safely continued by double-clicking
again.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
sys.dont_write_bytecode = True

ROOT = Path(__file__).resolve().parents[1]
PILOTS = (
    ("Agent 3 read-only pilot", ROOT / "scripts" / "agent3_readonly_pilot_one_click.py"),
    ("Scheduler M2 physical pilot", ROOT / "scripts" / "scheduler_pilot_wizard.py"),
)


def heading(text: str) -> None:
    print(f"\n{'=' * 72}\n{text}\n{'=' * 72}")


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
    print("  Ét dobbeltklik. Agent 3 køres først, scheduler-piloten bagefter.")
    print("  Begge forløb er exact-SHA-bundne og genoptages sikkert ved nyt dobbeltklik.")
    print("  Ingen merge, release eller produktionsaktivering kan udføres herfra.")

    for label, path in PILOTS:
        code = run_pilot(label, path)
        if code != 0:
            print(f"\n  SIKKERT STOP  {label} returnerede exit code {code}.", file=sys.stderr)
            print("  Ret det viste problem og dobbeltklik igen; beståede trin genbruges.", file=sys.stderr)
            return code

    heading("ALLE RESTERENDE PILOTER ER BESTÅET")
    print("  Gennemgå de to SHA-bundne rapporter før nogen integrationsbeslutning:")
    print("  validation\\agent3-readonly-pilot-latest.json")
    print("  validation\\scheduler-pilot-latest.json")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\n  SIKKERT STOP  Afbrudt af operatøren.", file=sys.stderr)
        raise SystemExit(1)
