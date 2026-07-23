#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "candidate_campaign_test",
    ROOT / "scripts" / "physical_validation_candidate_campaign.py",
)
assert SPEC and SPEC.loader
module = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = module
SPEC.loader.exec_module(module)

passed = failed = 0


def check(condition: bool, message: str) -> None:
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS: {message}")
    else:
        failed += 1
        print(f"  FAIL: {message}")


with tempfile.TemporaryDirectory(prefix="candidate-campaign-") as directory:
    root = Path(directory)
    freeze_path = root / "validation" / "pre-release-candidate-freeze-latest.json"
    freeze_path.parent.mkdir(parents=True)
    freeze_path.write_text(json.dumps({"schema": module.freeze.SCHEMA}), encoding="utf-8")
    candidate = {
        "version": "1.58.141",
        "git_sha": "c" * 40,
        "code_sha256": "d" * 64,
        "branch": "candidate",
        "working_tree_clean": True,
        "dirty_entries": 0,
        "identity_source": "git",
        "version_stamps_consistent": True,
        "version_check_detail": None,
    }
    old_root = module.ROOT
    old_identity = module.campaign.candidate_identity
    old_assessor = module.campaign._load_agent3_assessor
    old_validate = module.campaign.validate_evidence
    old_freeze = module.freeze.load_receipt
    try:
        module.ROOT = root
        module.campaign.candidate_identity = lambda _root: dict(candidate)
        module.campaign._load_agent3_assessor = lambda _root: object()
        module.freeze.load_receipt = lambda *_args, **_kwargs: {
            "schema": module.freeze.SCHEMA,
            "generated_at": datetime(2026, 7, 20, 20, 0, tzinfo=timezone.utc).isoformat(),
            "main_anchor": {"git_sha": "a" * 40, "ancestor_of_candidate": True},
            "software_checks": {
                name: "success" for name in module.freeze.REQUIRED_WORKFLOWS
            },
        }

        def pass_result(_root, name, _path, **_kwargs):
            return {
                "name": name,
                "status": "pass",
                "errors": [],
                "warnings": [],
                "summary": {},
            }

        module.campaign.validate_evidence = pass_result
        args = SimpleNamespace(
            mode="verify",
            freeze_report=Path("validation/pre-release-candidate-freeze-latest.json"),
            preflight_report=Path("preflight.json"),
            agent3_report=Path("agent3.json"),
            model_eval_report=Path("model.json"),
            voice_report=Path("voice.json"),
            rag_report=Path("rag.json"),
            scheduler_pilot_report=Path("scheduler.json"),
            max_age_hours=168.0,
            min_model_exact=1.0,
        )
        report, code = module.build_report(args)
        check(code == 0, "all six candidate proofs pass verify")
        check(report["proof_allowlist"] == list(module.PROOF_NAMES), "proof allowlist is exact and ordered")
        check("lifecycle" not in report["evidence"] and report["summary"]["total"] == 6, "only release-bound lifecycle is excluded")
        check(report["gate"]["candidate_campaign_complete"] is True, "six-proof campaign marks candidate complete")
        check(report["gate"]["release_validation_pending"] is True and report["gate"]["release_complete"] is False, "candidate campaign cannot claim release completion")

        def one_missing(_root, name, _path, **_kwargs):
            status = "missing" if name == "voice" else "pass"
            return {
                "name": name,
                "status": status,
                "errors": [],
                "warnings": [],
                "summary": {},
            }

        module.campaign.validate_evidence = one_missing
        report, code = module.build_report(args)
        check(code == 1 and report["gate"]["candidate_campaign_complete"] is False, "verify fails on one missing proof")
        args.mode = "prepare"
        report, code = module.build_report(args)
        check(code == 0 and report["gate"]["candidate_campaign_complete"] is False, "prepare inventories missing proof without claiming completion")
    finally:
        module.ROOT = old_root
        module.campaign.candidate_identity = old_identity
        module.campaign._load_agent3_assessor = old_assessor
        module.campaign.validate_evidence = old_validate
        module.freeze.load_receipt = old_freeze

print(f"candidate campaign contracts: {passed} passed, {failed} failed")
if failed:
    raise SystemExit(1)
