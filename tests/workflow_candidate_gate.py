#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "candidate_gate_test",
    ROOT / "scripts" / "physical_validation_candidate_gate.py",
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


with tempfile.TemporaryDirectory(prefix="candidate-gate-") as directory:
    root = Path(directory)
    validation = root / "validation"
    validation.mkdir()
    now = datetime(2026, 7, 20, 20, 0, tzinfo=timezone.utc)
    candidate = {
        "version": "1.58.141",
        "git_sha": "e" * 40,
        "code_sha256": "f" * 64,
        "branch": "candidate",
        "working_tree_clean": True,
        "dirty_entries": 0,
        "identity_source": "git",
        "version_stamps_consistent": True,
        "version_check_detail": None,
    }
    freeze_rel = Path("validation/pre-release-candidate-freeze-latest.json")
    freeze_raw = (json.dumps({"schema": module.freeze.SCHEMA}) + "\n").encode()
    (root / freeze_rel).write_bytes(freeze_raw)
    campaign = {
        "schema": module.CAMPAIGN_SCHEMA,
        "generated_at": now.isoformat().replace("+00:00", "Z"),
        "mode": "verify",
        "candidate": candidate,
        "freeze": {
            "path": str(freeze_rel),
            "sha256": hashlib.sha256(freeze_raw).hexdigest(),
            "schema": module.freeze.SCHEMA,
        },
        "proof_allowlist": list(module.PROOF_NAMES),
        "summary": {
            "total": 6,
            "passed": list(module.PROOF_NAMES),
            "failed": [],
            "missing": [],
            "candidate_errors": [],
        },
        "gate": {
            "passed": True,
            "candidate_campaign_complete": True,
            "release_validation_pending": True,
            "release_complete": False,
            "production_activation": False,
        },
    }
    campaign_rel = Path("validation/physical-validation-candidate-campaign-latest.json")
    (root / campaign_rel).write_text(json.dumps(campaign), encoding="utf-8")
    attestation_rel = Path("validation/browser-peer-public-validation-physical-latest.json")
    (root / attestation_rel).write_text("{}", encoding="utf-8")
    browser_path = validation / "browser-peer-public-validation-latest.json"
    browser_path.write_text("{}", encoding="utf-8")

    old_freeze = module.freeze.load_receipt
    old_browser = module.release_gate.validate_attestation
    try:
        module.freeze.load_receipt = lambda *_args, **_kwargs: {
            "schema": module.freeze.SCHEMA
        }
        module.release_gate.validate_attestation = lambda *_args, **_kwargs: (
            {"selected_address": "1.1.1.1", "response_status": 200},
            browser_path.read_bytes(),
            browser_path,
        )
        report, code = module.evaluate_candidate_gate(
            root,
            campaign_rel,
            attestation_rel,
            candidate=candidate,
            now=now,
            max_age_hours=168.0,
        )
        check(code == 0 and report["summary"]["total"] == 7, "six candidate proofs plus browser total seven")
        check(report["gate"]["candidate_ready_for_fast_forward"] is True, "seven-proof receipt can mark exact SHA ready for review")
        check(report["gate"]["release_validation_pending"] is True, "candidate gate keeps release validation pending")
        check(report["gate"]["all_physical_evidence_complete"] is False, "candidate gate cannot claim final eight-proof completion")
        check(report["gate"]["production_activation"] is False, "candidate gate never activates production")

        release_errors: list[str] = []
        module.release_gate.validate_campaign(campaign, candidate, release_errors)
        check(any("schema mismatch" in error for error in release_errors), "existing release gate rejects candidate campaign schema")

        campaign["schema"] = module.release_gate.CAMPAIGN_SCHEMA
        campaign["mode"] = "candidate"
        release_errors = []
        module.release_gate.validate_campaign(campaign, candidate, release_errors)
        check(bool(release_errors), "renaming candidate schema cannot satisfy release contract")
    finally:
        module.freeze.load_receipt = old_freeze
        module.release_gate.validate_attestation = old_browser

print(f"candidate final gate contracts: {passed} passed, {failed} failed")
if failed:
    raise SystemExit(1)
