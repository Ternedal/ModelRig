from __future__ import annotations

import hashlib
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping

from fastapi import APIRouter

from .validation_gate import evaluate_configured_report

READINESS_SCHEMA = "kaliv-agent3-task-readiness/v1"
PILOT_SCHEMA = "kaliv-agent3-readonly-pilot/v1"
DEFAULT_MAX_AGE_HOURS = 168.0
MAX_MAX_AGE_HOURS = 720.0
MAX_REPORT_BYTES = 2_097_152


def _object(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _sha256(value: Any) -> str | None:
    if not isinstance(value, str) or len(value) != 64:
        return None
    try:
        int(value, 16)
    except ValueError:
        return None
    return value.lower()


def _git_sha(value: Any) -> str | None:
    if not isinstance(value, str) or len(value) != 40:
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


def _max_age_from_env(environ: Mapping[str, str]) -> tuple[float | None, str | None]:
    raw = (environ.get("KALIV_AGENT3_PILOT_MAX_AGE_HOURS") or "").strip()
    if not raw:
        return DEFAULT_MAX_AGE_HOURS, None
    try:
        value = float(raw)
    except ValueError:
        return None, "pilot_max_age_invalid"
    if value <= 0 or value > MAX_MAX_AGE_HOURS:
        return None, "pilot_max_age_out_of_range"
    return value, None


def _base(max_age_hours: float, *, operator_enabled: bool) -> dict[str, Any]:
    return {
        "schema": READINESS_SCHEMA,
        # This slice evaluates evidence only. It cannot alter the normal chat
        # router, so even a perfect report still selects Agent 2.
        "selected_surface": "agent2",
        "candidate_surface": "agent3_readonly",
        "fallback_surface": "agent2",
        "eligible_for_task_ui": False,
        "operator_enabled": operator_enabled,
        "normal_chat_route_unchanged": True,
        "production_activation": False,
        "reason": "pilot_report_path_not_configured",
        "reasons": [],
        "pilot": {
            "configured": False,
            "present": False,
            "schema": None,
            "structurally_valid": False,
            "fresh": False,
            "version_match": False,
            "code_match": False,
            "finished_at": None,
            "age_seconds": None,
            "max_age_hours": max_age_hours,
            "report_sha256": None,
            "candidate_git_sha": None,
            "tasks": None,
            "successes": None,
            "failures": None,
            "task_success_rate": None,
            "replans": None,
            "retry_events": None,
            "stop_fallback_proven": False,
        },
        "rig_validation": {
            "eligible_for_developer_preview": False,
            "version_match": False,
            "code_match": False,
            "report_sha256": None,
        },
        "ui_contract": {
            "route_source": "server_authoritative",
            "stop_visible": True,
            "fallback_visible": True,
            "receipts_visible": True,
            "replans_visible": True,
            "outcomes_visible": True,
        },
    }


def _finish(result: dict[str, Any], reasons: list[str]) -> dict[str, Any]:
    unique = list(dict.fromkeys(reasons))
    if not unique:
        unique = ["task_ui_integration_not_delivered"]
    result["reasons"] = unique
    result["reason"] = unique[0]
    return result


def assess_task_readiness(
    report: Any,
    *,
    validation: Any,
    current_version: str | None,
    current_code: str | None,
    operator_enabled: bool,
    now: float | None = None,
    max_age_hours: float = DEFAULT_MAX_AGE_HOURS,
    report_sha256: str | None = None,
) -> dict[str, Any]:
    """Assess physical read-only pilot evidence without activating any route.

    The returned object is deliberately redacted. It never contains prompts,
    model answers, tool results, hostnames, base URLs, run IDs or raw errors.
    """

    result = _base(max_age_hours, operator_enabled=operator_enabled)
    pilot = result["pilot"]
    pilot["configured"] = True
    pilot["present"] = True
    pilot["report_sha256"] = report_sha256

    validation_obj = _object(validation)
    validation_summary = result["rig_validation"]
    validation_summary["eligible_for_developer_preview"] = (
        validation_obj.get("eligible_for_developer_preview") is True
    )
    validation_summary["version_match"] = validation_obj.get("version_match") is True
    validation_summary["code_match"] = validation_obj.get("code_match") is True
    validation_summary["report_sha256"] = _sha256(validation_obj.get("report_sha256"))

    reasons: list[str] = []
    if not isinstance(report, dict):
        return _finish(result, ["pilot_report_must_be_an_object"])

    pilot["schema"] = report.get("schema") if isinstance(report.get("schema"), str) else None
    candidate = _object(report.get("candidate"))
    target = _object(report.get("target"))
    backend = _object(report.get("backend"))
    summary = _object(report.get("summary"))
    stop = _object(report.get("stop_fallback"))
    results = _list(report.get("results"))

    candidate_version = candidate.get("version")
    candidate_code = _sha256(candidate.get("code_sha256"))
    candidate_git = _git_sha(candidate.get("git_sha"))
    pilot["candidate_git_sha"] = candidate_git

    if report.get("schema") != PILOT_SCHEMA:
        reasons.append("pilot_schema_mismatch")
    if report.get("success") is not True:
        reasons.append("pilot_report_not_successful")
    if not isinstance(candidate_version, str) or not candidate_version.strip():
        reasons.append("pilot_candidate_version_missing")
    if candidate_code is None:
        reasons.append("pilot_candidate_code_missing")
    if candidate_git is None:
        reasons.append("pilot_candidate_git_sha_invalid")

    finished = _parse_timestamp(report.get("finished_at"))
    if finished is None:
        reasons.append("pilot_finished_at_invalid")
    else:
        pilot["finished_at"] = finished.isoformat()
        current_ts = time.time() if now is None else float(now)
        age_seconds = current_ts - finished.timestamp()
        pilot["age_seconds"] = max(0.0, age_seconds)
        if age_seconds < -300:
            reasons.append("pilot_report_from_future")
        elif age_seconds > max_age_hours * 3600:
            reasons.append("pilot_report_stale")
        else:
            pilot["fresh"] = True

    if current_version and candidate_version == current_version:
        pilot["version_match"] = True
    else:
        reasons.append("pilot_candidate_version_mismatch")

    if current_code and candidate_code == current_code:
        pilot["code_match"] = True
    else:
        reasons.append("pilot_candidate_code_mismatch")

    if target.get("execution_mode") != "experimental-read-only":
        reasons.append("pilot_execution_mode_invalid")
    if target.get("production_activation") is not False:
        reasons.append("pilot_target_activation_not_false")
    if backend.get("production_tools_path_untouched") is not True:
        reasons.append("pilot_production_tools_path_not_proven")
    if backend.get("production_activation") is not False:
        reasons.append("pilot_backend_activation_not_false")

    integer_fields = {
        "tasks": 20,
        "successes": 20,
        "failures": 0,
        "retry_events": 0,
    }
    for name, expected in integer_fields.items():
        value = summary.get(name)
        pilot[name] = value if isinstance(value, int) and not isinstance(value, bool) else None
        if value != expected or isinstance(value, bool):
            reasons.append(f"pilot_{name}_invalid")

    replans = summary.get("replans")
    pilot["replans"] = replans if isinstance(replans, int) and not isinstance(replans, bool) else None
    if isinstance(replans, bool) or not isinstance(replans, int) or replans < 0:
        reasons.append("pilot_replans_invalid")

    rate = summary.get("task_success_rate")
    pilot["task_success_rate"] = rate if isinstance(rate, (int, float)) and not isinstance(rate, bool) else None
    if not isinstance(rate, (int, float)) or isinstance(rate, bool) or float(rate) != 1.0:
        reasons.append("pilot_task_success_rate_invalid")
    if summary.get("error_types") != {}:
        reasons.append("pilot_error_types_not_empty")

    stop_proven = (
        stop.get("success") is True
        and stop.get("agent3_state") == "cancelled"
        and stop.get("completed_agent3_steps") == 1
        and stop.get("pending_steps_after_stop") == 1
        and stop.get("fallback_path") == "/api/v1/chat"
    )
    pilot["stop_fallback_proven"] = stop_proven
    if not stop_proven:
        reasons.append("pilot_stop_fallback_not_proven")

    if len(results) != 20:
        reasons.append("pilot_results_count_invalid")
    else:
        for item in results:
            if not isinstance(item, dict):
                reasons.append("pilot_result_invalid")
                break
            if item.get("success") is not True or item.get("route") != "rig_tools_local":
                reasons.append("pilot_result_not_successful_read_route")
                break
            if item.get("retry_events") != 0:
                reasons.append("pilot_result_retry_present")
                break
            kinds = item.get("event_kinds")
            if not isinstance(kinds, list) or any(
                value in {"confirmation_required", "confirmation_approved", "confirmation_denied"}
                for value in kinds
            ):
                reasons.append("pilot_result_confirmation_present")
                break

    pilot["structurally_valid"] = not reasons

    if validation_summary["eligible_for_developer_preview"] is not True:
        reasons.append("rig_validation_not_ready")
    if validation_summary["version_match"] is not True:
        reasons.append("rig_validation_version_mismatch")
    if validation_summary["code_match"] is not True:
        reasons.append("rig_validation_code_mismatch")
    if validation_obj.get("production_activation") is not False:
        reasons.append("rig_validation_activation_not_false")

    evidence_ready = not reasons
    result["eligible_for_task_ui"] = evidence_ready

    # Operator intent is visible but cannot activate this delivery. The actual
    # normal-chat/task-UI integration is a later T-021 slice after physical review.
    if not operator_enabled:
        reasons.append("operator_disabled")
    elif evidence_ready:
        reasons.append("task_ui_integration_not_delivered")

    return _finish(result, reasons)


def evaluate_configured_task_readiness(
    *,
    current_version: str | None,
    current_code: str | None,
    validation: Any | None = None,
    environ: Mapping[str, str] | None = None,
    now: float | None = None,
) -> dict[str, Any]:
    env = os.environ if environ is None else environ
    operator_enabled = (env.get("KALIV_AGENT3_TASK_UI") or "").strip() == "1"
    max_age_hours, age_error = _max_age_from_env(env)
    result = _base(max_age_hours or DEFAULT_MAX_AGE_HOURS, operator_enabled=operator_enabled)
    if age_error:
        return _finish(result, [age_error])

    validation_obj = validation
    if validation_obj is None:
        validation_obj = evaluate_configured_report(
            current_version=current_version,
            current_code=current_code,
            environ=env,
            now=now,
        )

    raw_path = (env.get("KALIV_AGENT3_PILOT_REPORT") or "").strip()
    if not raw_path:
        result["rig_validation"] = {
            "eligible_for_developer_preview": _object(validation_obj).get(
                "eligible_for_developer_preview"
            ) is True,
            "version_match": _object(validation_obj).get("version_match") is True,
            "code_match": _object(validation_obj).get("code_match") is True,
            "report_sha256": _sha256(_object(validation_obj).get("report_sha256")),
        }
        return _finish(result, ["pilot_report_path_not_configured"])

    result["pilot"]["configured"] = True
    path = Path(raw_path).expanduser()
    if path.is_symlink():
        return _finish(result, ["pilot_report_symlink_not_allowed"])
    if not path.is_file():
        return _finish(result, ["pilot_report_not_found"])
    result["pilot"]["present"] = True

    try:
        size = path.stat().st_size
    except OSError:
        return _finish(result, ["pilot_report_stat_failed"])
    if size <= 0:
        return _finish(result, ["pilot_report_empty"])
    if size > MAX_REPORT_BYTES:
        return _finish(result, ["pilot_report_too_large"])

    try:
        raw = path.read_bytes()
    except OSError:
        return _finish(result, ["pilot_report_read_failed"])
    digest = hashlib.sha256(raw).hexdigest()
    try:
        report = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        result["pilot"]["report_sha256"] = digest
        return _finish(result, ["pilot_report_invalid_json"])

    return assess_task_readiness(
        report,
        validation=validation_obj,
        current_version=current_version,
        current_code=current_code,
        operator_enabled=operator_enabled,
        now=now,
        max_age_hours=max_age_hours or DEFAULT_MAX_AGE_HOURS,
        report_sha256=digest,
    )


ReadinessProvider = Callable[[], dict[str, Any]]


def build_task_readiness_router(provider: ReadinessProvider) -> APIRouter:
    router = APIRouter(
        prefix="/experimental/agent3",
        tags=["experimental-agent3-readiness"],
    )

    @router.get("/task-readiness")
    def task_readiness() -> dict[str, Any]:
        value = provider()
        # A provider is server-owned, but fail closed if a future refactor returns
        # a shape that could claim activation.
        if value.get("production_activation") is not False:
            raise RuntimeError("task readiness may never activate production")
        if value.get("selected_surface") != "agent2":
            raise RuntimeError("dormant readiness contract may only select agent2")
        return value

    return router
