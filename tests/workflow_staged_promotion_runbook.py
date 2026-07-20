#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
passed = failed = 0


def check(condition: bool, message: str) -> None:
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS: {message}")
    else:
        failed += 1
        print(f"  FAIL: {message}")


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
runbook_path = ROOT / "STAGED_PHYSICAL_PROMOTION.md"
check(version == "1.58.141", "staged candidate has a strictly newer release version")
check(runbook_path.exists(), "one authoritative staged promotion runbook exists")

if runbook_path.exists():
    runbook = runbook_path.read_text(encoding="utf-8")
    required = (
        "candidate_freeze_check.py",
        "physical_validation_candidate_campaign.py",
        "run-browser-peer-public-validation.ps1",
        "physical_validation_candidate_gate.py",
        "candidate_ready_for_fast_forward=true",
        "release_validation_pending=true",
        "release_complete=false",
        "all_physical_evidence_complete=false",
        "production_activation=false",
        "freeze_check.py",
        "physical_validation_campaign.py",
        "physical_validation_final_gate.py",
        "all_physical_evidence_complete=true",
        "summary.total=7",
        "summary.total=8",
    )
    check(all(item in runbook for item in required), "runbook contains both complete gate sequences")
    check("squash" in runbook and "rebase" in runbook and "mergecommit" in runbook, "runbook forbids SHA-changing integration after candidate evidence")
    check("1.58.140" in runbook and "1.58.141" in runbook, "lifecycle update source and target versions are explicit")

version_check = subprocess.run(
    [sys.executable, "scripts/version_tool.py", "check"],
    cwd=ROOT,
    capture_output=True,
    text=True,
)
check(version_check.returncode == 0, "all lockstep version sites match 1.58.141")

device = (ROOT / "DEVICE_TEST.md").read_text(encoding="utf-8")
physical = (ROOT / "PHYSICAL_VALIDATION_CAMPAIGN.md").read_text(encoding="utf-8")
agent3 = (ROOT / "AGENT3_RIG_VALIDATION.md").read_text(encoding="utf-8")
check("STAGED_PHYSICAL_PROMOTION.md" in device, "device runbook delegates promotion order to staged authority")
check("candidate_freeze_check.py" in device and "Stage B" in device, "device freeze section distinguishes pre-release and release freeze")
check("STAGED_PHYSICAL_PROMOTION.md" in physical and "Stage B" in physical, "release campaign declares its post-release scope")
check("STAGED_PHYSICAL_PROMOTION.md" in agent3, "Agent 3 prerequisites accept the exact staged candidate")

candidate_campaign = load(
    "runbook_candidate_campaign", ROOT / "scripts" / "physical_validation_candidate_campaign.py"
)
candidate_gate = load(
    "runbook_candidate_gate", ROOT / "scripts" / "physical_validation_candidate_gate.py"
)
release_gate = load(
    "runbook_release_gate", ROOT / "scripts" / "physical_validation_final_gate.py"
)
check(len(candidate_campaign.PROOF_NAMES) == 6 and "lifecycle" not in candidate_campaign.PROOF_NAMES, "pre-release campaign excludes exactly the release-bound lifecycle slot")
check(candidate_gate.SCHEMA != release_gate.SCHEMA, "seven-proof candidate receipt is schema-distinct from final release receipt")
check(candidate_gate.CAMPAIGN_SCHEMA != release_gate.CAMPAIGN_SCHEMA, "six-proof candidate campaign is schema-distinct from release campaign")

print(f"staged promotion runbook contracts: {passed} passed, {failed} failed")
if failed:
    raise SystemExit(1)
