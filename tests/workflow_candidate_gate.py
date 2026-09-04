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



# ---------------------------------------------------------------------------
# Rejection matrix.
#
# The block above proves the happy path and that the gate does not overclaim.
# It never asserts that any individual rule *rejects*, so a sweep that disables
# each `if <cond>: errors.append(...)` in _validate_candidate_campaign in turn
# leaves all sixteen rules unfelled.  Every rule is correct today -- each of the
# forgeries below is rejected by the unmutated gate -- but nothing would notice
# if one were removed.  This is the same class as the receipt-validator matrix,
# for the gate that decides physical promotion.
#
# Each case is built from an independent deep copy of a valid campaign, and the
# candidate the gate is evaluated against is a *separate* object from the one
# embedded in the campaign.  Sharing them would let a candidate.* mutation change
# both sides at once and pass for the wrong reason.
# ---------------------------------------------------------------------------

import copy


def _valid_campaign(candidate: dict, freeze_rel: Path, freeze_raw: bytes) -> dict:
    return {
        "schema": module.CAMPAIGN_SCHEMA,
        "generated_at": REJECTION_NOW.isoformat().replace("+00:00", "Z"),
        "mode": "verify",
        "candidate": copy.deepcopy(candidate),
        "freeze": {
            "path": str(freeze_rel),
            "sha256": hashlib.sha256(freeze_raw).hexdigest(),
            "schema": module.freeze.SCHEMA,
        },
        "proof_allowlist": list(module.PROOF_NAMES),
        "summary": {
            "total": len(module.PROOF_NAMES),
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


REJECTION_NOW = datetime(2026, 7, 20, 20, 0, tzinfo=timezone.utc)

# (name, mutate(campaign), expected error fragment)
REJECTION_CASES = [
    ("campaign schema mismatch",
     lambda c: c.__setitem__("schema", "kaliv-forged/v0"),
     "candidate campaign schema mismatch"),
    ("campaign not in verify mode",
     lambda c: c.__setitem__("mode", "candidate"),
     "was not produced in verify mode"),
    ("proof allowlist mismatch",
     lambda c: c.__setitem__("proof_allowlist", list(module.PROOF_NAMES)[:-1]),
     "proof allowlist mismatch"),
    ("campaign gate.passed not true",
     lambda c: c["gate"].__setitem__("passed", False),
     "candidate campaign gate.passed is not true"),
    ("campaign incomplete",
     lambda c: c["gate"].__setitem__("candidate_campaign_complete", False),
     "candidate campaign is incomplete"),
    ("release validation not preserved",
     lambda c: c["gate"].__setitem__("release_validation_pending", False),
     "does not preserve release_validation_pending"),
    ("campaign claims release completion",
     lambda c: c["gate"].__setitem__("release_complete", True),
     "incorrectly claims release completion"),
    ("campaign activated production",
     lambda c: c["gate"].__setitem__("production_activation", True),
     "candidate campaign activated production"),
    ("summary total not six",
     lambda c: c["summary"].__setitem__("total", len(module.PROOF_NAMES) - 1),
     "candidate campaign total is not six"),
    ("summary passed not the exact allowlist",
     lambda c: c["summary"].__setitem__("passed", list(module.PROOF_NAMES)[:-1]),
     "did not pass the exact six-proof allowlist"),
    ("summary carries failed evidence",
     lambda c: c["summary"].__setitem__("failed", ["agent3_write_pilot"]),
     "candidate campaign contains failed evidence"),
    ("summary carries missing evidence",
     lambda c: c["summary"].__setitem__("missing", ["agent3_write_pilot"]),
     "candidate campaign contains missing evidence"),
    ("summary carries candidate errors",
     lambda c: c["summary"].__setitem__("candidate_errors", ["stale"]),
     "candidate campaign contains candidate errors"),
    ("embedded candidate git_sha differs",
     lambda c: c["candidate"].__setitem__("git_sha", "0" * 40),
     "candidate campaign candidate.git_sha mismatch"),
    ("freeze path missing",
     lambda c: c["freeze"].__setitem__("path", ""),
     "candidate campaign freeze path is missing"),
    ("freeze digest differs from campaign",
     lambda c: c["freeze"].__setitem__("sha256", "0" * 64),
     "candidate freeze digest differs from campaign"),
    ("freeze schema differs from campaign",
     lambda c: c["freeze"].__setitem__("schema", "kaliv-forged-freeze/v0"),
     "candidate freeze schema differs from campaign"),
]


with tempfile.TemporaryDirectory(prefix="candidate-gate-reject-") as rej_dir:
    rej_root = Path(rej_dir)
    (rej_root / "validation").mkdir()
    rej_candidate = {
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
    rej_freeze_rel = Path("validation/pre-release-candidate-freeze-latest.json")
    rej_freeze_raw = (json.dumps({"schema": module.freeze.SCHEMA}) + "\n").encode()
    (rej_root / rej_freeze_rel).write_bytes(rej_freeze_raw)
    rej_campaign_rel = Path("validation/physical-validation-candidate-campaign-latest.json")
    rej_att_rel = Path("validation/browser-peer-public-validation-physical-latest.json")
    (rej_root / rej_att_rel).write_text("{}", encoding="utf-8")
    rej_browser = rej_root / "validation" / "browser-peer-public-validation-latest.json"
    rej_browser.write_text("{}", encoding="utf-8")

    old_freeze = module.freeze.load_receipt
    old_browser = module.release_gate.validate_attestation
    try:
        module.freeze.load_receipt = lambda *_a, **_k: {"schema": module.freeze.SCHEMA}
        module.release_gate.validate_attestation = lambda *_a, **_k: (
            {"selected_address": "1.1.1.1", "response_status": 200},
            rej_browser.read_bytes(),
            rej_browser,
        )

        def evaluate(campaign: dict):
            (rej_root / rej_campaign_rel).write_text(json.dumps(campaign), encoding="utf-8")
            return module.evaluate_candidate_gate(
                rej_root,
                rej_campaign_rel,
                rej_att_rel,
                candidate=rej_candidate,
                now=REJECTION_NOW,
                max_age_hours=168.0,
            )

        baseline_report, baseline_code = evaluate(
            _valid_campaign(rej_candidate, rej_freeze_rel, rej_freeze_raw)
        )
        check(
            baseline_code == 0 and baseline_report["gate"]["passed"] is True,
            "rejection matrix baseline: a valid campaign is promotable",
        )

        for name, mutate, fragment in REJECTION_CASES:
            campaign = _valid_campaign(rej_candidate, rej_freeze_rel, rej_freeze_raw)
            mutate(campaign)
            report, code = evaluate(campaign)
            errors = report["summary"]["errors"]
            rejected = code == 1 and report["gate"]["passed"] is False
            named = any(fragment in error for error in errors)
            check(
                rejected and named,
                f"{name} is rejected by its own rule "
                f"(code={code}, passed={report['gate']['passed']}, errors={errors})",
            )

        restored_report, restored_code = evaluate(
            _valid_campaign(rej_candidate, rej_freeze_rel, rej_freeze_raw)
        )
        check(
            restored_code == 0 and restored_report["gate"]["passed"] is True,
            "rejection matrix: baseline still promotable after all mutations",
        )
    finally:
        module.freeze.load_receipt = old_freeze
        module.release_gate.validate_attestation = old_browser

print(f"candidate final gate contracts: {passed} passed, {failed} failed")
if failed:
    raise SystemExit(1)
