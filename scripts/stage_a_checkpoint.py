#!/usr/bin/env python3
"""Save an honest, resumable checkpoint from the current Stage A campaign.

A checkpoint is not a promotion verdict. It preserves already accepted candidate-
bound evidence, distinguishes missing manual work from real failures, and always
keeps release and production activation disabled.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = "kaliv-stage-a-checkpoint/v1"
CAMPAIGN_SCHEMA = "kaliv-physical-validation-candidate-campaign/v1"
VOICE_SCHEMA = "kaliv-voice-baseline/v1"
DEFAULT_CAMPAIGN = Path("validation/physical-validation-candidate-campaign-latest.json")
DEFAULT_VOICE_FIXTURES = Path("validation/voice-baseline-fixture-check.json")
DEFAULT_REPORT = Path("validation/stage-a-checkpoint-latest.json")
PROOFS = ("preflight", "agent3", "model_eval", "voice", "rag", "scheduler_pilot")
AUTOMATIC_PROOFS = ("preflight", "agent3", "model_eval", "rag")
MANUAL_PROOFS = ("voice", "scheduler_pilot")


class CheckpointError(RuntimeError):
    """The local Stage A state cannot produce a trustworthy checkpoint."""


def _read_json(path: Path) -> tuple[dict[str, Any], bytes]:
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise CheckpointError(f"cannot read {path}") from exc
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CheckpointError(f"{path} is not valid UTF-8 JSON") from exc
    if not isinstance(value, dict):
        raise CheckpointError(f"{path} must contain a JSON object")
    return value, raw


def _repo_path(path: Path) -> Path:
    candidate = path if path.is_absolute() else ROOT / path
    resolved = candidate.resolve()
    try:
        resolved.relative_to(ROOT.resolve())
    except ValueError as exc:
        raise CheckpointError("checkpoint paths must remain under the repository") from exc
    return resolved


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


def _string_list(value: Any, label: str) -> list[str]:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise CheckpointError(f"{label} must be a string list")
    if len(value) != len(set(value)):
        raise CheckpointError(f"{label} contains duplicates")
    return list(value)


def _validate_candidate(candidate: Any) -> dict[str, Any]:
    if not isinstance(candidate, dict):
        raise CheckpointError("campaign candidate is missing")
    version = candidate.get("version")
    git_sha = candidate.get("git_sha")
    if not isinstance(version, str) or not version.strip():
        raise CheckpointError("candidate version is missing")
    if not isinstance(git_sha, str) or not re.fullmatch(r"[0-9a-f]{40}", git_sha):
        raise CheckpointError("candidate git_sha is invalid")
    if candidate.get("identity_source") != "git":
        raise CheckpointError("candidate identity must come from git")
    return candidate


def _validate_campaign(campaign: dict[str, Any]) -> dict[str, Any]:
    if campaign.get("schema") != CAMPAIGN_SCHEMA:
        raise CheckpointError("campaign schema is not supported")
    if campaign.get("mode") != "prepare":
        raise CheckpointError("checkpoint requires a prepare-mode campaign")

    candidate = _validate_candidate(campaign.get("candidate"))
    summary = campaign.get("summary")
    evidence = campaign.get("evidence")
    gate = campaign.get("gate")
    if not isinstance(summary, dict) or not isinstance(evidence, dict) or not isinstance(gate, dict):
        raise CheckpointError("campaign summary, evidence or gate is missing")
    if summary.get("total") != len(PROOFS):
        raise CheckpointError("campaign proof total is invalid")

    passed = _string_list(summary.get("passed"), "summary.passed")
    failed = _string_list(summary.get("failed"), "summary.failed")
    missing = _string_list(summary.get("missing"), "summary.missing")
    candidate_errors = _string_list(summary.get("candidate_errors"), "summary.candidate_errors")
    combined = passed + failed + missing
    if set(combined) != set(PROOFS) or len(combined) != len(PROOFS):
        raise CheckpointError("campaign proof lists do not partition the fixed allowlist")
    if tuple(evidence) != PROOFS:
        raise CheckpointError("campaign evidence allowlist drifted")

    expected_by_name = {
        **{name: "pass" for name in passed},
        **{name: "fail" for name in failed},
        **{name: "missing" for name in missing},
    }
    for name in PROOFS:
        item = evidence.get(name)
        if not isinstance(item, dict) or item.get("status") != expected_by_name[name]:
            raise CheckpointError(f"campaign evidence status mismatch for {name}")

    if gate.get("release_validation_pending") is not True:
        raise CheckpointError("campaign must keep release validation pending")
    if gate.get("release_complete") is not False:
        raise CheckpointError("campaign must keep release incomplete")
    if gate.get("production_activation") is not False:
        raise CheckpointError("campaign must keep production activation disabled")

    expected_prepare_gate = not failed and not candidate_errors
    if gate.get("passed") is not expected_prepare_gate:
        raise CheckpointError("prepare gate contradicts campaign failures")
    expected_complete = len(passed) == len(PROOFS) and not candidate_errors
    if gate.get("candidate_campaign_complete") is not expected_complete:
        raise CheckpointError("campaign completion flag contradicts proof status")

    return {
        "candidate": candidate,
        "passed": passed,
        "failed": failed,
        "missing": missing,
        "candidate_errors": candidate_errors,
        "complete": expected_complete,
    }


def _voice_fixture_status(path: Path, candidate: dict[str, Any]) -> dict[str, Any]:
    if not path.is_file():
        return {"status": "missing", "path": str(path.relative_to(ROOT))}
    try:
        value, raw = _read_json(path)
        if value.get("schema") != VOICE_SCHEMA:
            raise CheckpointError("voice fixture report schema is not supported")
        if value.get("gate") != {"mode": "validate_only", "passed": True}:
            raise CheckpointError("voice fixture validation did not pass")
        build = value.get("build")
        summary = value.get("summary")
        if not isinstance(build, dict) or not isinstance(summary, dict):
            raise CheckpointError("voice fixture report metadata is missing")
        if build.get("version") != candidate.get("version"):
            raise CheckpointError("voice fixture version does not match candidate")
        if build.get("git_sha") != candidate.get("git_sha"):
            raise CheckpointError("voice fixture git_sha does not match candidate")
        if summary.get("audio_present") != 20 or summary.get("audio_missing") != 0:
            raise CheckpointError("voice fixture report does not contain all 20 files")
        return {
            "status": "pass",
            "path": str(path.relative_to(ROOT)),
            "sha256": hashlib.sha256(raw).hexdigest(),
            "audio_present": 20,
        }
    except Exception as exc:
        return {
            "status": "invalid",
            "path": str(path.relative_to(ROOT)),
            "error": {
                "type": type(exc).__name__,
                "message": str(exc).replace("\r", " ").replace("\n", " ")[:500],
            },
        }


def build_checkpoint(
    campaign: dict[str, Any],
    *,
    source_path: Path,
    source_raw: bytes,
    voice_fixture_path: Path,
    now: datetime,
) -> tuple[dict[str, Any], int]:
    status = _validate_campaign(campaign)
    failed = status["failed"]
    missing = status["missing"]
    candidate_errors = status["candidate_errors"]
    checkpoint_valid = not failed and not candidate_errors
    automatic_complete = all(name in status["passed"] for name in AUTOMATIC_PROOFS)
    ready_for_verify = checkpoint_valid and not missing and status["complete"]

    next_steps: list[str] = []
    if any(name in missing for name in AUTOMATIC_PROOFS):
        next_steps.append("Resume Stage A to collect missing automatic evidence.")
    if "voice" in missing:
        next_steps.append("Voice remains pending; do not fabricate Pixel stop/barge-in evidence.")
    if "scheduler_pilot" in missing:
        next_steps.append("Scheduler pilot remains pending; no schedule approval is implied.")
    if failed:
        next_steps.append("Review failed proofs before resuming Stage A.")
    if candidate_errors:
        next_steps.append("Restore the exact clean candidate checkout before any further proof.")
    if ready_for_verify:
        next_steps.append("All six candidate proofs exist; the separate Stage A verify/final step may run.")

    report = {
        "schema": SCHEMA,
        "generated_at": now.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
        "source": {
            "path": str(source_path.relative_to(ROOT)),
            "schema": campaign.get("schema"),
            "generated_at": campaign.get("generated_at"),
            "sha256": hashlib.sha256(source_raw).hexdigest(),
        },
        "candidate": status["candidate"],
        "proofs": {
            "allowlist": list(PROOFS),
            "passed": status["passed"],
            "failed": failed,
            "pending": missing,
            "candidate_errors": candidate_errors,
        },
        "supplemental": {
            "voice_fixtures": _voice_fixture_status(voice_fixture_path, status["candidate"]),
        },
        "checkpoint": {
            "valid": checkpoint_valid,
            "automatic_evidence_complete": automatic_complete,
            "manual_evidence_pending": [name for name in MANUAL_PROOFS if name in missing],
            "ready_for_stage_a_verify": ready_for_verify,
            "next_steps": next_steps,
        },
        "gate": {
            "checkpoint_saved": checkpoint_valid,
            "candidate_campaign_complete": status["complete"],
            "promotion_ready": False,
            "release_validation_pending": True,
            "release_complete": False,
            "production_activation": False,
        },
    }
    return report, 0 if checkpoint_valid else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--campaign", type=Path, default=DEFAULT_CAMPAIGN)
    parser.add_argument("--voice-fixtures", type=Path, default=DEFAULT_VOICE_FIXTURES)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    args = parser.parse_args(argv)

    campaign_path = _repo_path(args.campaign)
    voice_fixture_path = _repo_path(args.voice_fixtures)
    report_path = _repo_path(args.report)
    try:
        campaign, raw = _read_json(campaign_path)
        report, exit_code = build_checkpoint(
            campaign,
            source_path=campaign_path,
            source_raw=raw,
            voice_fixture_path=voice_fixture_path,
            now=datetime.now(timezone.utc),
        )
    except Exception as exc:
        report = {
            "schema": SCHEMA,
            "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "error": {
                "type": type(exc).__name__,
                "message": str(exc).replace("\r", " ").replace("\n", " ")[:500],
            },
            "checkpoint": {
                "valid": False,
                "automatic_evidence_complete": False,
                "manual_evidence_pending": [],
                "ready_for_stage_a_verify": False,
                "next_steps": ["Repair the campaign report before saving a checkpoint."],
            },
            "gate": {
                "checkpoint_saved": False,
                "candidate_campaign_complete": False,
                "promotion_ready": False,
                "release_validation_pending": True,
                "release_complete": False,
                "production_activation": False,
            },
        }
        exit_code = 2

    _write_json_atomic(report_path, report)
    checkpoint = report.get("checkpoint", {})
    print(f"report: {report_path.relative_to(ROOT)}")
    print("checkpoint: " + ("SAVED" if checkpoint.get("valid") else "BLOCKED"))
    if isinstance(report.get("proofs"), dict):
        proofs = report["proofs"]
        print("passed: " + ", ".join(proofs.get("passed", [])))
        print("pending: " + ", ".join(proofs.get("pending", [])))
        print("failed: " + ", ".join(proofs.get("failed", [])))
    print("promotion_ready=false; production_activation=false")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
