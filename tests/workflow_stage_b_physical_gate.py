#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
import shutil
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "stage_b_physical_gate.py"


def load_module():
    spec = importlib.util.spec_from_file_location("stage_b_gate_contract", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


module = load_module()
passed = failed = 0


def check(condition: bool, message: str) -> None:
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS: {message}")
    else:
        failed += 1
        print(f"  FAIL: {message}")


NOW = datetime.now(timezone.utc).replace(microsecond=0)
CANDIDATE = {
    "version": "1.58.145",
    "git_sha": "a" * 40,
    "code_sha256": "b" * 64,
    "branch": "agent/unified-candidate-1.58.145",
    "working_tree_clean": True,
    "dirty_entries": 0,
    "identity_source": "git",
    "version_stamps_consistent": True,
    "version_check_detail": None,
}


def write(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def components(temp: Path) -> tuple[Path, Path, Path]:
    common = {
        "version": CANDIDATE["version"],
        "git_sha": CANDIDATE["git_sha"],
        "code_sha256": CANDIDATE["code_sha256"],
    }
    chain = {
        "schema": module.CHAIN_SCHEMA,
        "candidate": common,
        "gate": {
            "passed": True,
            "updater_chain_complete": True,
            "production_activation": False,
        },
    }
    campaign = {
        "schema": module.CAMPAIGN_SCHEMA,
        "mode": "verify",
        "candidate": common,
        "summary": {
            "total": 7,
            "passed": [
                "preflight",
                "agent3",
                "model_eval",
                "voice",
                "rag",
                "lifecycle",
                "scheduler_pilot",
            ],
            "failed": [],
            "missing": [],
            "candidate_errors": [],
        },
        "gate": {
            "passed": True,
            "physical_campaign_complete": True,
            "production_activation": False,
        },
    }
    final = {
        "schema": module.FINAL_SCHEMA,
        "candidate": common,
        "summary": {
            "total": 8,
            "passed": campaign["summary"]["passed"] + ["browser_peer_physical"],
            "errors": [],
        },
        "gate": {
            "passed": True,
            "physical_campaign_complete": True,
            "browser_peer_physical_complete": True,
            "all_physical_evidence_complete": True,
            "production_activation": False,
        },
    }
    chain_path = temp / "chain.json"
    campaign_path = temp / "campaign.json"
    final_path = temp / "final.json"
    write(chain_path, chain)
    write(campaign_path, campaign)
    write(final_path, final)
    return chain_path, campaign_path, final_path


validation = ROOT / "validation"
validation.mkdir(exist_ok=True)
temp = Path(tempfile.mkdtemp(prefix="stage-b-gate-test-", dir=validation))
try:
    chain_path, campaign_path, final_path = components(temp)
    steps = [
        {"label": "release freeze", "exit_code": 0},
        {"label": "updater-chain gate", "exit_code": 0},
        {"label": "seven-proof release campaign", "exit_code": 0},
        {"label": "eight-proof component final gate", "exit_code": 0},
    ]
    report, code = module.evaluate_bundle(
        ROOT,
        candidate=CANDIDATE,
        chain_path=chain_path.relative_to(ROOT),
        campaign_path=campaign_path.relative_to(ROOT),
        component_final_path=final_path.relative_to(ROOT),
        steps=steps,
        now=NOW,
    )
    check(code == 0 and report["gate"]["passed"] is True,
          "all Stage B component gates produce one green final receipt")
    check(report["gate"]["all_physical_evidence_complete"] is True,
          "Stage B wrapper is the complete physical evidence verdict")
    check(report["summary"]["total"] == 8,
          "semantic updater hardening does not invent a ninth physical proof")
    check(report["gate"]["production_activation"] is False,
          "Stage B wrapper cannot activate production")

    chain_path, campaign_path, final_path = components(temp)
    chain = json.loads(chain_path.read_text(encoding="utf-8"))
    chain["gate"]["updater_chain_complete"] = False
    write(chain_path, chain)
    report, code = module.evaluate_bundle(
        ROOT,
        candidate=CANDIDATE,
        chain_path=chain_path.relative_to(ROOT),
        campaign_path=campaign_path.relative_to(ROOT),
        component_final_path=final_path.relative_to(ROOT),
        steps=steps,
        now=NOW,
    )
    check(code == 1 and any("updater-chain is incomplete" in error
                            for error in report["summary"]["errors"]),
          "weak updater evidence blocks the final Stage B receipt")

    chain_path, campaign_path, final_path = components(temp)
    final = json.loads(final_path.read_text(encoding="utf-8"))
    final["candidate"]["git_sha"] = "c" * 40
    write(final_path, final)
    report, code = module.evaluate_bundle(
        ROOT,
        candidate=CANDIDATE,
        chain_path=chain_path.relative_to(ROOT),
        campaign_path=campaign_path.relative_to(ROOT),
        component_final_path=final_path.relative_to(ROOT),
        steps=steps,
        now=NOW,
    )
    check(code == 1 and any("component final candidate identity mismatch" in error
                            for error in report["summary"]["errors"]),
          "cross-SHA component reports cannot be bundled")

    chain_path, campaign_path, final_path = components(temp)
    failed_steps = list(steps)
    failed_steps[1] = {"label": "updater-chain gate", "exit_code": 7}
    report, code = module.evaluate_bundle(
        ROOT,
        candidate=CANDIDATE,
        chain_path=chain_path.relative_to(ROOT),
        campaign_path=campaign_path.relative_to(ROOT),
        component_final_path=final_path.relative_to(ROOT),
        steps=failed_steps,
        now=NOW,
    )
    check(code == 1 and any("exit code 7" in error
                            for error in report["summary"]["errors"]),
          "a failed component process remains visible in the final verdict")
finally:
    shutil.rmtree(temp, ignore_errors=True)

source = SCRIPT.read_text(encoding="utf-8")
check(
    source.index('"release freeze"')
    < source.index('"updater-chain gate"')
    < source.index('"seven-proof release campaign"')
    < source.index('"eight-proof component final gate"'),
    "Stage B executes freeze, updater chain, campaign and final gate in order",
)
for forbidden in (
    "git push",
    "git tag",
    "gh release",
    "merge_pull_request",
    "production_activation=true",
):
    check(forbidden not in source.lower(), f"Stage B gate has no forbidden action: {forbidden}")

print(f"Stage B final-gate contracts: {passed} passed, {failed} failed")
if failed:
    raise SystemExit(1)
