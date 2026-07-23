#!/usr/bin/env python3
"""Aggregate the six physical proofs that can exist before a release is published.

The normal ``physical_validation_campaign.py --mode verify`` remains the release
campaign and still requires all seven proofs, including the real updater
lifecycle trial. This pre-release campaign deliberately excludes only that one
release-bound proof. Its allowlist is fixed and its receipt always states that
release validation is pending and production is not activated.
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
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = "kaliv-physical-validation-candidate-campaign/v1"
DEFAULT_REPORT = Path("validation/physical-validation-candidate-campaign-latest.json")
FREEZE_REPORT = Path("validation/pre-release-candidate-freeze-latest.json")
PROOF_NAMES = (
    "preflight",
    "agent3",
    "model_eval",
    "voice",
    "rag",
    "scheduler_pilot",
)


class CandidateCampaignError(RuntimeError):
    """The pre-release physical campaign cannot produce a trustworthy receipt."""


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise CandidateCampaignError(f"cannot load {path.name}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


campaign = _load("candidate_campaign_base", ROOT / "scripts" / "physical_validation_campaign.py")
freeze = _load("candidate_freeze_contract", ROOT / "scripts" / "candidate_freeze_check.py")


def _write_json_atomic(path: Path, value: dict[str, Any]) -> None:
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


def _candidate_errors(candidate: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if candidate.get("working_tree_clean") is not True:
        errors.append(
            f"working tree has {candidate.get('dirty_entries')} uncommitted change(s)"
        )
    if candidate.get("version_stamps_consistent") is not True:
        errors.append("version stamps are inconsistent")
    return errors


def build_report(args: argparse.Namespace) -> tuple[dict[str, Any], int]:
    root = ROOT
    now = datetime.now(timezone.utc)
    candidate = campaign.candidate_identity(root)
    if candidate.get("identity_source") != "git":
        raise CandidateCampaignError("pre-release campaign requires the git candidate checkout")

    freeze_path = args.freeze_report if args.freeze_report.is_absolute() else root / args.freeze_report
    frozen = freeze.load_receipt(
        root,
        path=args.freeze_report,
        expected_candidate=candidate,
        now=now,
    )
    freeze_raw = freeze_path.read_bytes()

    assessor = campaign._load_agent3_assessor(root)
    thresholds: dict[str, Any] = {
        "min_model_exact": args.min_model_exact,
        "agent3_assessor": assessor,
        "root": root,
    }
    paths = {
        "preflight": args.preflight_report,
        "agent3": args.agent3_report,
        "model_eval": args.model_eval_report,
        "voice": args.voice_report,
        "rag": args.rag_report,
        "scheduler_pilot": args.scheduler_pilot_report,
    }
    if tuple(paths) != PROOF_NAMES:
        raise CandidateCampaignError("pre-release proof allowlist drifted")

    evidence = {
        name: campaign.validate_evidence(
            root,
            name,
            path,
            candidate=candidate,
            thresholds=thresholds,
            now=now,
            max_age_hours=args.max_age_hours,
        )
        for name, path in paths.items()
    }
    failed = [name for name, item in evidence.items() if item["status"] == "fail"]
    missing = [name for name, item in evidence.items() if item["status"] == "missing"]
    passed = [name for name, item in evidence.items() if item["status"] == "pass"]
    candidate_errors = _candidate_errors(candidate)
    complete = len(passed) == len(PROOF_NAMES)
    if args.mode == "prepare":
        gate_passed = not candidate_errors and not failed
    else:
        gate_passed = not candidate_errors and complete
    exit_code = 0 if gate_passed else 1

    report = {
        "schema": SCHEMA,
        "generated_at": now.isoformat().replace("+00:00", "Z"),
        "mode": args.mode,
        "candidate": candidate,
        "freeze": {
            "path": str(freeze_path.relative_to(root.resolve())),
            "sha256": hashlib.sha256(freeze_raw).hexdigest(),
            "schema": frozen.get("schema"),
            "generated_at": frozen.get("generated_at"),
            "main_anchor": frozen.get("main_anchor"),
            "software_checks": frozen.get("software_checks"),
        },
        "configuration": {
            "max_age_hours": args.max_age_hours,
            "min_model_exact": args.min_model_exact,
        },
        "proof_allowlist": list(PROOF_NAMES),
        "evidence": evidence,
        "summary": {
            "total": len(PROOF_NAMES),
            "passed": passed,
            "failed": failed,
            "missing": missing,
            "candidate_errors": candidate_errors,
        },
        "gate": {
            "passed": gate_passed,
            "candidate_campaign_complete": complete and not candidate_errors,
            "release_validation_pending": True,
            "release_complete": False,
            "production_activation": False,
        },
    }
    return report, exit_code


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("prepare", "verify"), default="verify")
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--freeze-report", type=Path, default=FREEZE_REPORT)
    parser.add_argument("--preflight-report", type=Path, default=campaign.DEFAULT_PATHS["preflight"])
    parser.add_argument("--agent3-report", type=Path, default=campaign.DEFAULT_PATHS["agent3"])
    parser.add_argument("--model-eval-report", type=Path, default=campaign.DEFAULT_PATHS["model_eval"])
    parser.add_argument("--voice-report", type=Path, default=campaign.DEFAULT_PATHS["voice"])
    parser.add_argument("--rag-report", type=Path, default=campaign.DEFAULT_PATHS["rag"])
    parser.add_argument(
        "--scheduler-pilot-report",
        type=Path,
        default=campaign.DEFAULT_PATHS["scheduler_pilot"],
    )
    parser.add_argument("--max-age-hours", type=float, default=168.0)
    parser.add_argument("--min-model-exact", type=float, default=1.0)
    args = parser.parse_args(argv)
    if args.max_age_hours <= 0 or args.max_age_hours > 720:
        parser.error("--max-age-hours must be greater than 0 and at most 720")
    if not 0 <= args.min_model_exact <= 1:
        parser.error("--min-model-exact must be between 0 and 1")
    try:
        report, exit_code = build_report(args)
    except Exception as exc:
        report = {
            "schema": SCHEMA,
            "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "mode": args.mode,
            "error": {
                "type": type(exc).__name__,
                "message": str(exc).replace("\r", " ").replace("\n", " ")[:500],
            },
            "summary": {
                "total": len(PROOF_NAMES),
                "passed": [],
                "failed": ["candidate_campaign"],
                "missing": [],
                "candidate_errors": [],
            },
            "gate": {
                "passed": False,
                "candidate_campaign_complete": False,
                "release_validation_pending": True,
                "release_complete": False,
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
    print(
        "gate: "
        + ("PASS" if report.get("gate", {}).get("passed") else "BLOCKED")
        + f" (mode={args.mode}, release_validation_pending=true)"
    )
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
