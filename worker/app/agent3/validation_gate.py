from __future__ import annotations

import hashlib
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping


REPORT_SCHEMA = "kaliv-agent3-rig-validation/v1"
DEFAULT_MAX_AGE_HOURS = 168.0
MAX_MAX_AGE_HOURS = 720.0
MAX_REPORT_BYTES = 1_048_576


def _ordered_contains(values: list[str], required: tuple[str, ...]) -> bool:
    cursor = 0
    for item in required:
        try:
            cursor = values.index(item, cursor) + 1
        except ValueError:
            return False
    return True


def _strings(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]


def _object(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _sha256(value: Any) -> str | None:
    if not isinstance(value, str) or len(value) != 64:
        return None
    try:
        int(value, 16)
    except ValueError:
        return None
    return value.lower()


def _parse_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def _base_assessment(max_age_hours: float) -> dict[str, Any]:
    return {
        "configured": False,
        "present": False,
        "schema": None,
        "structurally_valid": False,
        "fresh": False,
        "version_match": False,
        "eligible_for_developer_preview": False,
        "eligible_for_write_pilot": False,
        # Evidence is advisory only in this draft. It never toggles routes,
        # tools, memory or UI by itself.
        "production_activation": False,
        "current_version": None,
        "validated_version": None,
        "planner_model": None,
        "write_decision": None,
        "finished_at": None,
        "age_seconds": None,
        "max_age_hours": max_age_hours,
        "report_sha256": None,
        "proofs": {
            "status": False,
            "memory_binding": False,
            "read_path": False,
            "confirmation_path": False,
            "write_execution": False,
            "single_use": False,
            "cleanup": False,
        },
        "reasons": [],
        "write_pilot_reasons": [],
        "warnings": [],
    }


def assess_report(
    report: Any,
    *,
    current_version: str | None,
    now: float | None = None,
    max_age_hours: float = DEFAULT_MAX_AGE_HOURS,
    report_sha256: str | None = None,
) -> dict[str, Any]:
    """Evaluate one already-parsed on-rig validation report.

    The returned object is deliberately redacted: it never includes hostnames,
    base URLs, memory values, run IDs, step IDs, source references or the marker.
    """

    assessment = _base_assessment(max_age_hours)
    assessment["configured"] = True
    assessment["present"] = True
    assessment["current_version"] = current_version
    assessment["report_sha256"] = report_sha256

    if not isinstance(report, dict):
        assessment["reasons"] = ["report_must_be_an_object"]
        assessment["write_pilot_reasons"] = list(assessment["reasons"])
        return assessment

    assessment["schema"] = report.get("schema") if isinstance(report.get("schema"), str) else None
    target = _object(report.get("target"))
    checks = _object(report.get("checks"))
    cleanup = _object(report.get("cleanup"))

    validated_version = target.get("modelrig_version")
    worker_version = target.get("worker_version")
    assessment["validated_version"] = (
        validated_version if isinstance(validated_version, str) else None
    )
    assessment["planner_model"] = (
        target.get("planner_model") if isinstance(target.get("planner_model"), str) else None
    )
    assessment["write_decision"] = (
        target.get("write_decision") if target.get("write_decision") in {"deny", "approve"} else None
    )

    structural_reasons: list[str] = []
    if report.get("schema") != REPORT_SCHEMA:
        structural_reasons.append("schema_mismatch")
    if report.get("success") is not True:
        structural_reasons.append("report_not_successful")
    if not isinstance(validated_version, str) or not validated_version.strip():
        structural_reasons.append("validated_version_missing")
    if not isinstance(worker_version, str) or not worker_version.strip():
        structural_reasons.append("worker_version_missing")
    elif isinstance(validated_version, str) and worker_version != validated_version:
        structural_reasons.append("backend_worker_version_mismatch")

    finished = _parse_timestamp(report.get("finished_at"))
    if finished is None:
        structural_reasons.append("finished_at_invalid")
    else:
        assessment["finished_at"] = finished.isoformat()
        current_ts = time.time() if now is None else float(now)
        age_seconds = current_ts - finished.timestamp()
        assessment["age_seconds"] = max(0.0, age_seconds)
        if age_seconds < -300:
            structural_reasons.append("report_from_future")
        elif age_seconds > max_age_hours * 3600:
            structural_reasons.append("report_stale")
        else:
            assessment["fresh"] = True

    if not current_version:
        structural_reasons.append("current_version_unavailable")
    elif isinstance(validated_version, str) and validated_version == current_version:
        assessment["version_match"] = True
    else:
        structural_reasons.append("validated_version_mismatch")

    status = _object(checks.get("status"))
    status_proven = (
        status.get("enabled") is True
        and status.get("experimental") is True
        and status.get("production_tools_path_untouched") is True
    )

    context = _object(checks.get("context_preview"))
    read_run = _object(checks.get("read_run"))
    write_preview = _object(checks.get("write_preview"))
    read_receipt = _object(read_run.get("receipt"))
    write_receipt = _object(write_preview.get("receipt"))
    context_sha = _sha256(context.get("sha256"))
    read_sha = _sha256(read_receipt.get("sha256"))
    write_sha = _sha256(write_receipt.get("sha256"))
    context_ids = _strings(context.get("included_ids"))
    read_ids = _strings(read_receipt.get("included_ids"))
    write_ids = _strings(write_receipt.get("included_ids"))
    memory_binding_proven = (
        context.get("sent_to_model") is False
        and bool(context_ids)
        and context_sha is not None
        and context_sha == read_sha == write_sha
        and context_ids == read_ids == write_ids
        and read_receipt.get("requested") is True
        and read_receipt.get("sent_to_model") is True
        and read_receipt.get("target") == "local"
        and write_receipt.get("requested") is True
        and write_receipt.get("sent_to_model") is True
        and write_receipt.get("target") == "local"
    )

    read_events = _strings(read_run.get("event_kinds"))
    read_path_proven = (
        read_run.get("state") == "completed"
        and _ordered_contains(
            read_events,
            (
                "run_created",
                "policy_decision",
                "step_started",
                "step_succeeded",
                "run_completed",
            ),
        )
    )

    confirmation = _object(checks.get("confirmation_card"))
    pre_events = _strings(confirmation.get("pre_confirmation_events"))
    confirmation_pre_proven = (
        _ordered_contains(
            pre_events,
            ("run_created", "policy_decision", "confirmation_required"),
        )
        and "step_started" not in pre_events
        and "step_succeeded" not in pre_events
        and _sha256(confirmation.get("digest_sha256")) is not None
    )

    write = _object(checks.get("write_confirmation"))
    decision = write.get("decision")
    write_events = _strings(write.get("event_kinds"))
    denied_path = (
        decision == "deny"
        and write.get("state") == "cancelled"
        and write.get("mutation_expected") is False
        and _ordered_contains(
            write_events,
            (
                "run_created",
                "policy_decision",
                "confirmation_required",
                "confirmation_denied",
            ),
        )
        and "step_started" not in write_events
        and "step_succeeded" not in write_events
    )
    approved_path = (
        decision == "approve"
        and write.get("state") == "completed"
        and write.get("mutation_expected") is True
        and _ordered_contains(
            write_events,
            (
                "run_created",
                "policy_decision",
                "confirmation_required",
                "confirmation_approved",
                "step_started",
                "step_succeeded",
                "run_completed",
            ),
        )
    )
    confirmation_path_proven = confirmation_pre_proven and (denied_path or approved_path)

    single_use = _object(checks.get("single_use"))
    single_use_proven = single_use.get("replay_blocked") is True
    cleanup_proven = (
        cleanup.get("deleted") is True
        and cleanup.get("content_erased") is True
        and cleanup.get("source_ref_erased") is True
    )

    assessment["proofs"] = {
        "status": status_proven,
        "memory_binding": memory_binding_proven,
        "read_path": read_path_proven,
        "confirmation_path": confirmation_path_proven,
        "write_execution": approved_path,
        "single_use": single_use_proven,
        "cleanup": cleanup_proven,
    }

    proof_reasons: list[str] = []
    for key, proven in assessment["proofs"].items():
        if key == "write_execution":
            continue
        if not proven:
            proof_reasons.append(f"{key}_not_proven")

    assessment["structurally_valid"] = not structural_reasons
    developer_reasons = structural_reasons + proof_reasons
    assessment["reasons"] = developer_reasons
    assessment["eligible_for_developer_preview"] = not developer_reasons

    write_reasons = list(developer_reasons)
    if not approved_path:
        write_reasons.append("write_execution_not_proven")
        if denied_path:
            assessment["warnings"].append(
                "standard_deny_report_proves_confirmation_but_not_write_execution"
            )
    assessment["write_pilot_reasons"] = write_reasons
    assessment["eligible_for_write_pilot"] = not write_reasons
    return assessment


def _max_age_from_env(environ: Mapping[str, str]) -> tuple[float | None, str | None]:
    raw = (environ.get("KALIV_AGENT3_VALIDATION_MAX_AGE_HOURS") or "").strip()
    if not raw:
        return DEFAULT_MAX_AGE_HOURS, None
    try:
        value = float(raw)
    except ValueError:
        return None, "validation_max_age_invalid"
    if value <= 0 or value > MAX_MAX_AGE_HOURS:
        return None, "validation_max_age_out_of_range"
    return value, None


def evaluate_configured_report(
    *,
    current_version: str | None,
    environ: Mapping[str, str] | None = None,
    now: float | None = None,
) -> dict[str, Any]:
    """Read and assess the explicitly configured validation report.

    No default file is trusted. The operator must set
    KALIV_AGENT3_VALIDATION_REPORT to opt into evidence evaluation.
    """

    env = os.environ if environ is None else environ
    max_age_hours, age_error = _max_age_from_env(env)
    assessment = _base_assessment(max_age_hours or DEFAULT_MAX_AGE_HOURS)
    assessment["current_version"] = current_version
    if age_error:
        assessment["reasons"] = [age_error]
        assessment["write_pilot_reasons"] = [age_error]
        return assessment

    raw_path = (env.get("KALIV_AGENT3_VALIDATION_REPORT") or "").strip()
    if not raw_path:
        assessment["reasons"] = ["report_path_not_configured"]
        assessment["write_pilot_reasons"] = list(assessment["reasons"])
        return assessment

    assessment["configured"] = True
    path = Path(raw_path).expanduser()
    if path.is_symlink():
        assessment["reasons"] = ["report_symlink_not_allowed"]
        assessment["write_pilot_reasons"] = list(assessment["reasons"])
        return assessment
    if not path.is_file():
        assessment["reasons"] = ["report_not_found"]
        assessment["write_pilot_reasons"] = list(assessment["reasons"])
        return assessment

    assessment["present"] = True
    try:
        size = path.stat().st_size
    except OSError:
        assessment["reasons"] = ["report_stat_failed"]
        assessment["write_pilot_reasons"] = list(assessment["reasons"])
        return assessment
    if size <= 0:
        assessment["reasons"] = ["report_empty"]
        assessment["write_pilot_reasons"] = list(assessment["reasons"])
        return assessment
    if size > MAX_REPORT_BYTES:
        assessment["reasons"] = ["report_too_large"]
        assessment["write_pilot_reasons"] = list(assessment["reasons"])
        return assessment

    try:
        raw = path.read_bytes()
    except OSError:
        assessment["reasons"] = ["report_read_failed"]
        assessment["write_pilot_reasons"] = list(assessment["reasons"])
        return assessment
    digest = hashlib.sha256(raw).hexdigest()
    try:
        report = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        assessment["report_sha256"] = digest
        assessment["reasons"] = ["report_invalid_json"]
        assessment["write_pilot_reasons"] = list(assessment["reasons"])
        return assessment

    return assess_report(
        report,
        current_version=current_version,
        now=now,
        max_age_hours=max_age_hours or DEFAULT_MAX_AGE_HOURS,
        report_sha256=digest,
    )
