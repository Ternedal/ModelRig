#!/usr/bin/env python3
"""Compose existing physical receipts with candidate-bound T-023 evidence.

The legacy candidate and final receipt schemas remain immutable. This additive
receipt validates one of them, independently validates the T-023 Android/Windows
report, and produces the truthful 7-proof pre-release or 9-proof final view.
Missing T-023 evidence is reported as missing/blocked, never as implicitly green.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import platform
import socket
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = "kaliv-physical-validation-termination-campaign/v1"
CANDIDATE_SCHEMA = "kaliv-physical-validation-candidate-campaign/v1"
FINAL_SCHEMA = "kaliv-physical-validation-final/v1"
TERMINATION_NAME = "agent3_termination_ui_physical"
MAX_EVIDENCE_BYTES = 32 * 1024 * 1024
DEFAULT_TERMINATION = Path("validation/agent3-termination-ui-physical-latest.json")
DEFAULT_BASE = {
    "candidate": Path("validation/physical-validation-candidate-campaign-latest.json"),
    "final": Path("validation/physical-validation-final-latest.json"),
}
DEFAULT_REPORT = {
    "candidate": Path("validation/physical-validation-termination-candidate-latest.json"),
    "final": Path("validation/physical-validation-termination-final-latest.json"),
}
CANDIDATE_BASE_PROOFS = (
    "preflight",
    "agent3",
    "model_eval",
    "voice",
    "rag",
    "scheduler_pilot",
)


class TerminationCampaignError(RuntimeError):
    """The composed physical campaign cannot produce a trustworthy receipt."""


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise TerminationCampaignError(f"cannot load {path.name}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


identity_module = _load_module(
    "termination_campaign_identity",
    ROOT / "scripts" / "physical_validation_campaign.py",
)
termination_gate = _load_module(
    "termination_campaign_t023_gate",
    ROOT / "scripts" / "agent3_termination_ui_physical_gate.py",
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


def _resolve_under(root: Path, raw: Path) -> Path:
    unresolved = raw if raw.is_absolute() else root / raw
    if unresolved.is_symlink():
        raise TerminationCampaignError(f"evidence path is a symlink: {raw}")
    resolved = unresolved.resolve()
    try:
        resolved.relative_to(root.resolve())
    except ValueError as exc:
        raise TerminationCampaignError(f"evidence path escapes repository: {raw}") from exc
    return resolved


def _load_json(root: Path, raw_path: Path) -> tuple[dict[str, Any], bytes, Path]:
    path = _resolve_under(root, raw_path)
    if not path.exists() or not path.is_file() or path.is_symlink():
        raise TerminationCampaignError(f"evidence is missing or irregular: {raw_path}")
    size = path.stat().st_size
    if size <= 0 or size > MAX_EVIDENCE_BYTES:
        raise TerminationCampaignError(f"evidence size is invalid: {raw_path}")
    raw = path.read_bytes()
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise TerminationCampaignError(f"evidence is not UTF-8 JSON: {raw_path}") from exc
    if not isinstance(value, dict):
        raise TerminationCampaignError(f"evidence is not a JSON object: {raw_path}")
    return value, raw, path


def _timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def _fresh(
    errors: list[str], label: str, value: Any, *, now: datetime, hours: float
) -> None:
    observed = _timestamp(value)
    if observed is None:
        errors.append(f"{label} is not a timezone-aware timestamp")
        return
    age = (now - observed).total_seconds() / 3600.0
    if age < -0.25:
        errors.append(f"{label} is in the future")
    elif age > hours:
        errors.append(f"{label} is {age:.1f}h old; max is {hours:.1f}h")


def _same_candidate(
    errors: list[str], label: str, actual: Any, expected: Mapping[str, Any]
) -> None:
    if not isinstance(actual, Mapping):
        errors.append(f"{label} candidate is missing")
        return
    for key in ("version", "git_sha", "code_sha256"):
        if actual.get(key) != expected.get(key):
            errors.append(f"{label} candidate.{key} mismatch")


def _validate_candidate_base(
    report: Mapping[str, Any], candidate: Mapping[str, Any], errors: list[str]
) -> tuple[int | None, list[str]]:
    if report.get("schema") != CANDIDATE_SCHEMA:
        errors.append("candidate campaign schema mismatch")
    if report.get("mode") != "verify":
        errors.append("candidate campaign was not produced in verify mode")
    _same_candidate(errors, "candidate campaign", report.get("candidate"), candidate)
    gate = report.get("gate") if isinstance(report.get("gate"), Mapping) else {}
    if gate.get("passed") is not True or gate.get("candidate_campaign_complete") is not True:
        errors.append("candidate campaign is incomplete")
    if gate.get("release_validation_pending") is not True:
        errors.append("candidate campaign does not preserve release_validation_pending=true")
    if gate.get("release_complete") is not False:
        errors.append("candidate campaign incorrectly claims release completion")
    if gate.get("production_activation") is not False:
        errors.append("candidate campaign activated production")
    if report.get("proof_allowlist") != list(CANDIDATE_BASE_PROOFS):
        errors.append("candidate campaign proof allowlist mismatch")
    summary = report.get("summary") if isinstance(report.get("summary"), Mapping) else {}
    if summary.get("failed") not in ([], None):
        errors.append("candidate campaign contains failed evidence")
    if summary.get("missing") not in ([], None):
        errors.append("candidate campaign contains missing evidence")
    if summary.get("candidate_errors") not in ([], None):
        errors.append("candidate campaign contains candidate errors")
    total = summary.get("total")
    passed = summary.get("passed")
    if total != len(CANDIDATE_BASE_PROOFS):
        errors.append("candidate campaign base total mismatch")
    if passed != list(CANDIDATE_BASE_PROOFS):
        errors.append("candidate campaign passed proof inventory mismatch")
        passed = list(passed) if isinstance(passed, list) else []
    return total if isinstance(total, int) else None, list(passed)


def _validate_final_base(
    report: Mapping[str, Any], candidate: Mapping[str, Any], errors: list[str]
) -> tuple[int | None, list[str]]:
    if report.get("schema") != FINAL_SCHEMA:
        errors.append("final physical gate schema mismatch")
    _same_candidate(errors, "final physical gate", report.get("candidate"), candidate)
    gate = report.get("gate") if isinstance(report.get("gate"), Mapping) else {}
    for key in (
        "passed",
        "physical_campaign_complete",
        "browser_peer_physical_complete",
        "all_physical_evidence_complete",
    ):
        if gate.get(key) is not True:
            errors.append(f"final physical gate.{key} is not true")
    if gate.get("production_activation") is not False:
        errors.append("final physical gate activated production")
    summary = report.get("summary") if isinstance(report.get("summary"), Mapping) else {}
    if summary.get("errors") not in ([], None):
        errors.append("final physical gate contains errors")
    total = summary.get("total")
    passed = summary.get("passed")
    if total != 8:
        errors.append("final physical base total is not eight")
    if not isinstance(passed, list) or len(passed) != total or len(passed) != len(set(passed)):
        errors.append("final physical passed inventory is invalid")
        passed = list(passed) if isinstance(passed, list) else []
    if TERMINATION_NAME in passed:
        errors.append("final physical base already contains the T-023 proof")
    return total if isinstance(total, int) else None, list(passed)


def evaluate(
    *,
    root: Path,
    stage: str,
    base_path: Path,
    termination_path: Path,
    candidate: Mapping[str, Any],
    now: datetime,
    max_age_hours: float,
) -> tuple[dict[str, Any], int]:
    errors: list[str] = []
    base_report, base_raw, base_file = _load_json(root, base_path)
    _fresh(errors, f"{stage} base.generated_at", base_report.get("generated_at"), now=now, hours=max_age_hours)
    if stage == "candidate":
        base_total, passed = _validate_candidate_base(base_report, candidate, errors)
    else:
        base_total, passed = _validate_final_base(base_report, candidate, errors)

    termination = termination_gate.campaign_evidence(
        root=root,
        path=termination_path,
        candidate=candidate,
        now=now,
        max_age_hours=max_age_hours,
    )
    if termination.get("status") != "pass":
        for error in termination.get("errors") or ["T-023 physical evidence is not passing"]:
            errors.append(f"termination UI: {error}")
    elif not errors:
        passed.append(TERMINATION_NAME)

    composed_total = base_total + 1 if isinstance(base_total, int) else None
    passed_unique = len(passed) == len(set(passed))
    if not passed_unique:
        errors.append("composed passed inventory contains duplicates")
    complete = not errors and isinstance(composed_total, int) and len(passed) == composed_total
    report = {
        "schema": SCHEMA,
        "generated_at": now.isoformat().replace("+00:00", "Z"),
        "stage": stage,
        "candidate": dict(candidate),
        "host": {
            "hostname": socket.gethostname(),
            "system": platform.system(),
            "platform": platform.platform(),
        },
        "configuration": {"max_age_hours": max_age_hours},
        "evidence": {
            "base": {
                "path": str(base_file.relative_to(root.resolve())),
                "sha256": hashlib.sha256(base_raw).hexdigest(),
                "bytes": len(base_raw),
                "schema": base_report.get("schema"),
                "status": "pass" if not any("base" in error or "campaign" in error or "final" in error for error in errors) else "fail",
                "summary": base_report.get("summary"),
            },
            "termination_ui_physical": termination,
        },
        "proof_inventory": {
            "base_total": base_total,
            "added": [TERMINATION_NAME],
            "total": composed_total,
            "passed": passed,
        },
        "summary": {
            "total": composed_total,
            "passed": passed,
            "errors": errors,
        },
        "gate": {
            "passed": complete,
            "termination_ui_physical_complete": termination.get("status") == "pass",
            "candidate_campaign_complete": complete if stage == "candidate" else None,
            "release_validation_pending": True if stage == "candidate" else False,
            "all_physical_evidence_complete": complete if stage == "final" else False,
            "production_activation": False,
        },
    }
    return report, 0 if complete else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", choices=("candidate", "final"), required=True)
    parser.add_argument("--base-report", type=Path)
    parser.add_argument("--termination-report", type=Path, default=DEFAULT_TERMINATION)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--max-age-hours", type=float, default=168.0)
    args = parser.parse_args(argv)
    if args.max_age_hours <= 0 or args.max_age_hours > 720:
        parser.error("--max-age-hours must be greater than 0 and at most 720")
    base_path = args.base_report or DEFAULT_BASE[args.stage]
    destination = args.report or DEFAULT_REPORT[args.stage]
    now = datetime.now(timezone.utc)
    try:
        candidate = identity_module.candidate_identity(ROOT)
        if candidate.get("working_tree_clean") is not True:
            raise TerminationCampaignError("current candidate working tree is not clean")
        if candidate.get("version_stamps_consistent") is not True:
            raise TerminationCampaignError("current candidate version stamps are inconsistent")
        report, exit_code = evaluate(
            root=ROOT,
            stage=args.stage,
            base_path=base_path,
            termination_path=args.termination_report,
            candidate=candidate,
            now=now,
            max_age_hours=args.max_age_hours,
        )
    except Exception as exc:
        report = {
            "schema": SCHEMA,
            "generated_at": now.isoformat().replace("+00:00", "Z"),
            "stage": args.stage,
            "error": {
                "type": type(exc).__name__,
                "message": str(exc).replace("\r", " ").replace("\n", " ")[:500],
            },
            "summary": {"total": 0, "passed": [], "errors": [str(exc)[:500]]},
            "gate": {
                "passed": False,
                "termination_ui_physical_complete": False,
                "candidate_campaign_complete": False,
                "release_validation_pending": args.stage == "candidate",
                "all_physical_evidence_complete": False,
                "production_activation": False,
            },
        }
        exit_code = 2
    report_path = _resolve_under(ROOT, destination)
    _write_json_atomic(report_path, report)
    print(f"report: {report_path.relative_to(ROOT)}")
    print(
        "gate: "
        + ("PASS" if report.get("gate", {}).get("passed") else "BLOCKED")
        + f" (stage={args.stage})"
    )
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
