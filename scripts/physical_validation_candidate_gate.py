#!/usr/bin/env python3
"""Combine the six-proof candidate campaign with the physical T-032 browser proof.

A passing receipt means the exact SHA is ready for an explicit fast-forward to
``main``. It does NOT mean release validation is complete: the updater lifecycle
proof is necessarily post-release, so this schema can never satisfy the existing
eight-proof final gate and always keeps ``production_activation=false``.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = "kaliv-physical-validation-candidate-final/v1"
CAMPAIGN_SCHEMA = "kaliv-physical-validation-candidate-campaign/v1"
DEFAULT_CAMPAIGN = Path("validation/physical-validation-candidate-campaign-latest.json")
DEFAULT_ATTESTATION = Path("validation/browser-peer-public-validation-physical-latest.json")
DEFAULT_REPORT = Path("validation/physical-validation-candidate-final-latest.json")
PROOF_NAMES = (
    "preflight",
    "agent3",
    "model_eval",
    "voice",
    "rag",
    "scheduler_pilot",
)


class CandidateFinalGateError(RuntimeError):
    """The seven-proof pre-release candidate evidence is incomplete or invalid."""


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise CandidateFinalGateError(f"cannot load {path.name}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


release_gate = _load(
    "candidate_gate_release_contract", ROOT / "scripts" / "physical_validation_final_gate.py"
)
campaign_base = _load(
    "candidate_gate_campaign_base", ROOT / "scripts" / "physical_validation_campaign.py"
)
freeze = _load(
    "candidate_gate_freeze_contract", ROOT / "scripts" / "candidate_freeze_check.py"
)


def _write_json_atomic(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=path.parent,
        prefix=path.name + ".",
        suffix=".tmp",
        delete=False,
    ) as handle:
        handle.write(payload)
        temporary = Path(handle.name)
    temporary.replace(path)


def _same_candidate(errors: list[str], label: str, actual: Any, expected: Mapping[str, Any]) -> None:
    if not isinstance(actual, Mapping):
        errors.append(f"{label} candidate is missing")
        return
    for key in ("version", "git_sha", "code_sha256"):
        if actual.get(key) != expected.get(key):
            errors.append(f"{label} candidate.{key} mismatch")


def _validate_candidate_campaign(
    root: Path,
    report: Mapping[str, Any],
    candidate: Mapping[str, Any],
    errors: list[str],
    *,
    now: datetime,
    max_age_hours: float,
) -> dict[str, Any]:
    if report.get("schema") != CAMPAIGN_SCHEMA:
        errors.append("candidate campaign schema mismatch")
    if report.get("mode") != "verify":
        errors.append("candidate campaign was not produced in verify mode")
    _same_candidate(errors, "candidate campaign", report.get("candidate"), candidate)
    release_gate._fresh(
        errors,
        "candidate campaign.generated_at",
        report.get("generated_at"),
        now,
        max_age_hours,
    )
    if report.get("proof_allowlist") != list(PROOF_NAMES):
        errors.append("candidate campaign proof allowlist mismatch")
    gate = report.get("gate") if isinstance(report.get("gate"), Mapping) else {}
    if gate.get("passed") is not True:
        errors.append("candidate campaign gate.passed is not true")
    if gate.get("candidate_campaign_complete") is not True:
        errors.append("candidate campaign is incomplete")
    if gate.get("release_validation_pending") is not True:
        errors.append("candidate campaign does not preserve release_validation_pending=true")
    if gate.get("release_complete") is not False:
        errors.append("candidate campaign incorrectly claims release completion")
    if gate.get("production_activation") is not False:
        errors.append("candidate campaign activated production")

    summary = report.get("summary") if isinstance(report.get("summary"), Mapping) else {}
    if summary.get("total") != len(PROOF_NAMES):
        errors.append("candidate campaign total is not six")
    if summary.get("passed") != list(PROOF_NAMES):
        errors.append("candidate campaign did not pass the exact six-proof allowlist")
    if summary.get("failed") not in ([], None):
        errors.append("candidate campaign contains failed evidence")
    if summary.get("missing") not in ([], None):
        errors.append("candidate campaign contains missing evidence")
    if summary.get("candidate_errors") not in ([], None):
        errors.append("candidate campaign contains candidate errors")

    freeze_meta = report.get("freeze") if isinstance(report.get("freeze"), Mapping) else {}
    freeze_path = freeze_meta.get("path")
    if not isinstance(freeze_path, str) or not freeze_path:
        errors.append("candidate campaign freeze path is missing")
    else:
        try:
            strict = freeze.load_receipt(
                root,
                path=Path(freeze_path),
                expected_candidate=candidate,
                now=now,
            )
            raw = (root / freeze_path).read_bytes()
            if hashlib.sha256(raw).hexdigest() != freeze_meta.get("sha256"):
                errors.append("candidate freeze digest differs from campaign")
            if strict.get("schema") != freeze_meta.get("schema"):
                errors.append("candidate freeze schema differs from campaign")
        except Exception as exc:
            errors.append(f"candidate freeze receipt is invalid: {str(exc)[:300]}")
    return {
        "total": len(PROOF_NAMES),
        "passed": list(PROOF_NAMES),
    }


def evaluate_candidate_gate(
    root: Path,
    campaign_path: Path,
    attestation_path: Path,
    *,
    candidate: Mapping[str, Any],
    now: datetime,
    max_age_hours: float,
) -> tuple[dict[str, Any], int]:
    errors: list[str] = []
    campaign, campaign_raw, campaign_file = release_gate._load_json(root, campaign_path)
    attestation, attestation_raw, attestation_file = release_gate._load_json(
        root, attestation_path
    )
    campaign_summary = _validate_candidate_campaign(
        root,
        campaign,
        candidate,
        errors,
        now=now,
        max_age_hours=max_age_hours,
    )
    browser_summary, browser_raw, browser_file = release_gate.validate_attestation(
        root,
        attestation,
        candidate,
        now=now,
        max_age_hours=max_age_hours,
        errors=errors,
    )
    passed_names = list(campaign_summary["passed"])
    if not errors:
        passed_names.append("browser_peer_physical")
    report = {
        "schema": SCHEMA,
        "generated_at": now.isoformat().replace("+00:00", "Z"),
        "candidate": dict(candidate),
        "configuration": {"max_age_hours": max_age_hours},
        "evidence": {
            "candidate_campaign": {
                "path": str(campaign_file.relative_to(root.resolve())),
                "sha256": hashlib.sha256(campaign_raw).hexdigest(),
                "bytes": len(campaign_raw),
                "status": "pass" if not any("campaign" in error for error in errors) else "fail",
                "summary": campaign_summary,
            },
            "browser_peer_physical_attestation": {
                "path": str(attestation_file.relative_to(root.resolve())),
                "sha256": hashlib.sha256(attestation_raw).hexdigest(),
                "bytes": len(attestation_raw),
                "receipt_path": str(browser_file.relative_to(root.resolve())),
                "receipt_sha256": hashlib.sha256(browser_raw).hexdigest(),
                "receipt_bytes": len(browser_raw),
                "status": "pass" if not errors else "fail",
                "summary": browser_summary,
            },
        },
        "summary": {
            "total": len(PROOF_NAMES) + 1,
            "passed": passed_names,
            "errors": errors,
        },
        "gate": {
            "passed": not errors,
            "candidate_campaign_complete": not errors,
            "browser_peer_physical_complete": not errors,
            "candidate_ready_for_fast_forward": not errors,
            "release_validation_pending": True,
            "release_complete": False,
            "all_physical_evidence_complete": False,
            "production_activation": False,
        },
    }
    return report, 0 if not errors else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate-campaign", type=Path, default=DEFAULT_CAMPAIGN)
    parser.add_argument("--browser-attestation", type=Path, default=DEFAULT_ATTESTATION)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--max-age-hours", type=float, default=168.0)
    args = parser.parse_args(argv)
    if args.max_age_hours <= 0 or args.max_age_hours > 720:
        parser.error("--max-age-hours must be greater than 0 and at most 720")
    now = datetime.now(timezone.utc)
    try:
        candidate = campaign_base.candidate_identity(ROOT)
        if candidate.get("identity_source") != "git":
            raise CandidateFinalGateError("candidate gate requires the git checkout")
        if candidate.get("working_tree_clean") is not True:
            raise CandidateFinalGateError("current candidate working tree is not clean")
        if candidate.get("version_stamps_consistent") is not True:
            raise CandidateFinalGateError("current candidate version stamps are inconsistent")
        report, exit_code = evaluate_candidate_gate(
            ROOT,
            args.candidate_campaign,
            args.browser_attestation,
            candidate=candidate,
            now=now,
            max_age_hours=args.max_age_hours,
        )
    except Exception as exc:
        report = {
            "schema": SCHEMA,
            "generated_at": now.isoformat().replace("+00:00", "Z"),
            "error": {
                "type": type(exc).__name__,
                "message": str(exc).replace("\r", " ").replace("\n", " ")[:500],
            },
            "summary": {"total": 7, "passed": [], "errors": [str(exc)[:500]]},
            "gate": {
                "passed": False,
                "candidate_campaign_complete": False,
                "browser_peer_physical_complete": False,
                "candidate_ready_for_fast_forward": False,
                "release_validation_pending": True,
                "release_complete": False,
                "all_physical_evidence_complete": False,
                "production_activation": False,
            },
        }
        exit_code = 2
    destination = args.report if args.report.is_absolute() else ROOT / args.report
    try:
        destination.resolve().relative_to(ROOT.resolve())
    except ValueError:
        parser.error("--report must remain under the repository")
    _write_json_atomic(destination, report)
    print(f"report: {destination.relative_to(ROOT)}")
    print("gate: " + ("PASS" if report.get("gate", {}).get("passed") else "BLOCKED"))
    if report.get("gate", {}).get("passed"):
        print("candidate ready for exact-SHA fast-forward; release validation remains pending")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
