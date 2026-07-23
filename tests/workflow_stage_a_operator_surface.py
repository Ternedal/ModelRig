#!/usr/bin/env python3
"""Static surface contract for Stage A operator and runbook."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PY = (ROOT / "scripts/stage_a_physical_operator.py").read_text(encoding="utf-8")
PS = (ROOT / "scripts/run-stage-a-physical-validation.ps1").read_text(encoding="utf-8")
DOC = (ROOT / "STAGED_PHYSICAL_PROMOTION.md").read_text(encoding="utf-8")

passed = failed = 0


def check(condition, message):
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS: {message}")
    else:
        failed += 1
        print(f"  FAIL: {message}")


check("_require_physical_operator()" in PY, "Windows, TTY and non-CI guard is enforced")
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
