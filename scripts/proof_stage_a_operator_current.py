#!/usr/bin/env python3
"""Bind the retained Stage A physical operator to the exact current candidate.

This is deliberately only a version/branch shim. The retained operator owns all
freeze, evidence, browser and promotion semantics unchanged.
"""
# ruff: noqa: F821 -- main() is defined by the retained operator through exec().
from __future__ import annotations
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RETAINED = ROOT / "scripts" / "stage_a_physical_operator.retained"

def cap(*args: str) -> str:
    p = subprocess.run(args, cwd=ROOT, capture_output=True, text=True, check=False)
    if p.returncode:
        raise RuntimeError((p.stderr or p.stdout).strip())
    return p.stdout.strip()

_branch = cap("git", "branch", "--show-current")
if not _branch:
    raise RuntimeError("Detached HEAD afvises for Stage A fysisk kandidat")
_version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
_source = RETAINED.read_text(encoding="utf-8")
_source = _source.replace("agent/unified-candidate-1.58.143", _branch)
_source = _source.replace("1.58.143", _version)
_name = __name__
globals()["__name__"] = "_proof_stage_a_operator_current_retained"
exec(compile(_source, str(RETAINED), "exec"), globals(), globals())
globals()["__name__"] = _name
EXPECTED_BRANCH = _branch
EXPECTED_VERSION = _version

if _name == "__main__":
    raise SystemExit(main())
