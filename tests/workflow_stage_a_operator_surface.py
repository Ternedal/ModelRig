#!/usr/bin/env python3
"""Static surface contract for Stage A operator and runbook."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "support"))
from source_code import code_of, strip_comments  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
# The .py file is a thin shim that exec()s stage_a_physical_operator.retained,
# and it carries a comment block labelled "static surface markers retained by
# tests" -- markers added so this gate would keep passing after the code moved.
# Reading only the shim, "_require_physical_operator()" was satisfied by that
# comment. The code itself lives in the retained file: read both, as code.
_SHIM = ROOT / "scripts/stage_a_physical_operator.py"
_RETAINED = ROOT / "scripts/stage_a_physical_operator.retained"
PY = code_of(_SHIM) + "\n" + strip_comments(
    _RETAINED.read_text(encoding="utf-8"), ".py")
PS = code_of(ROOT / "scripts/run-stage-a-physical-validation.ps1")
DOC = code_of(ROOT / "STAGED_PHYSICAL_PROMOTION.md")

passed = failed = 0


def check(condition, message):
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS: {message}")
    else:
        failed += 1
        print(f"  FAIL: {message}")


# "_require_physical_operator()" appearing somewhere is not the claim; the
# def line contains it too, so the check passed with the call commented out.
# The claim is that the guard is DEFINED and CALLED.
_guard_lines = [l.strip() for l in PY.splitlines() if "_require_physical_operator()" in l]
check(any(l.startswith("def _require_physical_operator()") for l in _guard_lines)
      and any(not l.startswith("def ") for l in _guard_lines),
      "Windows, TTY and non-CI guard is defined and called")
check("candidate_freeze_check.py" in PY, "exact-SHA freeze is invoked")
check("physical_validation_candidate_campaign.py" in PY, "candidate campaign is invoked")
check("run-browser-peer-public-validation.ps1" in PY, "interactive browser launcher is reused")
check("physical_validation_candidate_gate.py" in PY, "seven-proof gate is invoked")
check('choices=("prepare", "verify", "complete")' in PY, "Python CLI exposes only three Stage A actions")
check('[ValidateSet("Prepare", "Verify", "Complete")]' in PS, "PowerShell exposes only three Stage A actions")
check("run-stage-a-physical-validation.ps1" in DOC, "runbook delegates Stage A to the launcher")
check("-Action Prepare" in DOC, "prepare action is documented")
check("-Action Verify" in DOC, "verify action is documented")
check("-Action Complete" in DOC, "complete action is documented")
check("candidate_ready_for_fast_forward=true" in DOC, "candidate-ready boundary remains explicit")
check("release_validation_pending=true" in DOC, "release-pending boundary remains explicit")
check("release_complete=false" in DOC, "release cannot be claimed complete in Stage A")
check("all_physical_evidence_complete=false" in DOC, "seven proofs cannot claim final completion")
check("production_activation=false" in DOC, "production remains inactive")

lower = (PY + "\n" + PS).lower()
check("api.github.com/repos" not in lower, "operator has no repository mutation API")
check("enable_auto" not in lower, "operator has no automatic integration path")
check("create_release" not in lower, "operator has no release creation path")
check("production_activation\": true" not in lower, "operator cannot emit an active production gate")

print(f"stage A operator surface: {passed} passed, {failed} failed")
raise SystemExit(1 if failed else 0)
