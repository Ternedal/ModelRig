from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

TASK_UI_SCHEMA = "kaliv-agent3-task-ui-validation/v1"
EVIDENCE_ROOT = ("validation", "agent3-task-ui-evidence")
MAX_EVIDENCE_BYTES = 32 * 1024 * 1024
SURFACE = "agent3_readonly"
FALLBACK = "agent2"
SELECTED_REASON = "agent3_readonly_selected"
ROUTE = "rig_tools_local"
REQUIRED_CLIENT_CHECKS = (
    "selected_surface_visible",
    "server_reason_visible",
    "plan_review_visible",
    "preview_did_not_execute",
    "tool_status_visible",
    "stop_visible",
    "stop_after_fallback",
    "receipts_visible",
    "replans_visible",
    "terminal_outcome_visible",
    "fallback_visible",
    "normal_chat_round_trip",
    "no_write_controls",
)


def _nested(value: Any, *keys: str) -> Any:
    current = value
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def _expect(errors: list[str], label: str, actual: Any, expected: Any) -> None:
    if actual != expected:
        errors.append(f"{label} mismatch: expected {expected!r}, got {actual!r}")


def _digest(value: Any, length: int) -> bool:
    return isinstance(value, str) and re.fullmatch(rf"[0-9a-f]{{{length}}}", value) is not None


def _parse_time(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def _validate_binding(
    errors: list[str],
    label: str,
    value: Any,
    expected: dict[str, str],
) -> dict[str, str] | None:
    if not isinstance(value, dict):
        errors.append(f"{label} is missing")
        return None
    binding = {
        "pilot_report_sha256": value.get("pilot_report_sha256"),
        "pilot_candidate_git_sha": value.get("pilot_candidate_git_sha"),
        "rig_validation_report_sha256": value.get("rig_validation_report_sha256"),
    }
    if not _digest(binding["pilot_report_sha256"], 64):
        errors.append(f"{label}.pilot_report_sha256 is invalid")
    if not _digest(binding["pilot_candidate_git_sha"], 40):
        errors.append(f"{label}.pilot_candidate_git_sha is invalid")
    if not _digest(binding["rig_validation_report_sha256"], 64):
        errors.append(f"{label}.rig_validation_report_sha256 is invalid")
    for key, expected_value in expected.items():
        _expect(errors, f"{label}.{key}", binding.get(key), expected_value)
    return {key: str(item) for key, item in binding.items()}


def _validate_receipt(
    errors: list[str],
    label: str,
    value: Any,
) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        errors.append(f"{label} is missing")
        return None
    _expect(errors, f"{label}.schema", value.get("schema"), "kaliv-agent3-capability-receipt/v1")
    _expect(errors, f"{label}.route", value.get("route"), ROUTE)
    _expect(errors, f"{label}.allowed", value.get("allowed"), True)
    _expect(errors, f"{label}.blockers", value.get("blockers"), [])
    _expect(errors, f"{label}.production_activation", value.get("production_activation"), False)
    if not _digest(value.get("graph_sha256"), 64):
        errors.append(f"{label}.graph_sha256 is invalid")
    if not _digest(value.get("plan_sha256"), 64):
        errors.append(f"{label}.plan_sha256 is invalid")
    return value


def _validate_artifact(
    errors: list[str],
    *,
    root: Path,
    label: str,
    value: Any,
) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        errors.append(f"{label}.artifact is missing")
        return None
    raw_path = value.get("path")
    expected_sha = value.get("sha256")
    expected_bytes = value.get("bytes")
    if not isinstance(raw_path, str) or not raw_path.strip():
        errors.append(f"{label}.artifact.path must be a non-empty string")
        return None
    relative = Path(raw_path)
    if relative.is_absolute() or ".." in relative.parts:
        errors.append(f"{label}.artifact.path must be repository-relative")
        return None
    unresolved = root / relative
    if unresolved.is_symlink():
        errors.append(f"{label}.artifact.path must not be a symlink")
        return None
    try:
        resolved = unresolved.resolve()
        normalized = resolved.relative_to(root.resolve())
    except ValueError:
        errors.append(f"{label}.artifact.path escapes the repository")
        return None
    if normalized.parts[:2] != EVIDENCE_ROOT:
        errors.append(
            f"{label}.artifact.path must be under {'/'.join(EVIDENCE_ROOT)}"
        )
        return None
    if not resolved.is_file():
        errors.append(f"{label}.artifact file is missing")
        return None
    try:
        raw = resolved.read_bytes()
    except OSError as exc:
        errors.append(f"{label}.artifact cannot be read: {type(exc).__name__}")
        return None
    if len(raw) <= 0 or len(raw) > MAX_EVIDENCE_BYTES:
        errors.append(f"{label}.artifact size is invalid: {len(raw)} bytes")
        return None
    actual_sha = hashlib.sha256(raw).hexdigest()
    if not _digest(expected_sha, 64):
        errors.append(f"{label}.artifact.sha256 is invalid")
    elif actual_sha != expected_sha:
        errors.append(f"{label}.artifact.sha256 does not match the artifact")
    if not isinstance(expected_bytes, int) or isinstance(expected_bytes, bool):
        errors.append(f"{label}.artifact.bytes is invalid")
    elif expected_bytes != len(raw):
        errors.append(f"{label}.artifact.bytes does not match the artifact")
    return {
        "path": normalized.as_posix(),
        "sha256": actual_sha,
        "bytes": len(raw),
    }


def validate_task_ui(
    report: dict[str, Any],
    result: dict[str, Any],
    candidate: dict[str, Any],
    thresholds: dict[str, Any],
) -> None:
    """Independently re-prove the producer's T-021 physical evidence."""
    errors: list[str] = result["errors"]
    root = thresholds.get("root")
    if not isinstance(root, Path):
        errors.append("task UI validator has no repository root")
        return

    _expect(errors, "schema", report.get("schema"), TASK_UI_SCHEMA)
    for key in ("version", "git_sha", "code_sha256"):
        _expect(
            errors,
            f"candidate.{key}",
            _nested(report, "candidate", key),
            candidate[key],
        )
    _expect(errors, "gate.passed", _nested(report, "gate", "passed"), True)
    _expect(
        errors,
        "gate.production_activation",
        _nested(report, "gate", "production_activation"),
        False,
    )
    _expect(
        errors,
        "gate.normal_chat_route_unchanged",
        _nested(report, "gate", "normal_chat_route_unchanged"),
        True,
    )
    _expect(
        errors,
        "configuration.token_recorded",
        _nested(report, "configuration", "token_recorded"),
        False,
    )
    _expect(
        errors,
        "configuration.production_activation",
        _nested(report, "configuration", "production_activation"),
        False,
    )
    _expect(
        errors,
        "summary.machine_probe_completed",
        _nested(report, "summary", "machine_probe_completed"),
        True,
    )
    _expect(errors, "summary.android_passed", _nested(report, "summary", "android_passed"), True)
    _expect(errors, "summary.desktop_passed", _nested(report, "summary", "desktop_passed"), True)
    _expect(errors, "summary.clients", _nested(report, "summary", "clients"), 2)
    _expect(errors, "summary.artifacts", _nested(report, "summary", "artifacts"), 2)

    machine = report.get("machine_probe")
    if not isinstance(machine, dict):
        errors.append("machine_probe is missing")
        machine = {}
    _expect(errors, "machine_probe.completed", machine.get("completed"), True)
    readiness = machine.get("readiness")
    if not isinstance(readiness, dict):
        errors.append("machine_probe.readiness is missing")
        readiness = {}
    _expect(errors, "readiness.selected_surface", readiness.get("selected_surface"), SURFACE)
    _expect(errors, "readiness.fallback_surface", readiness.get("fallback_surface"), FALLBACK)
    _expect(errors, "readiness.reason", readiness.get("reason"), SELECTED_REASON)
    _expect(errors, "readiness.pilot_candidate_git_sha", readiness.get("pilot_candidate_git_sha"), candidate["git_sha"])
    _expect(errors, "readiness.pilot_tasks", readiness.get("pilot_tasks"), 20)
    _expect(errors, "readiness.pilot_successes", readiness.get("pilot_successes"), 20)
    _expect(errors, "readiness.pilot_retry_events", readiness.get("pilot_retry_events"), 0)
    _expect(errors, "readiness.stop_fallback_proven", readiness.get("stop_fallback_proven"), True)
    expected_binding = {
        "pilot_report_sha256": readiness.get("pilot_report_sha256"),
        "pilot_candidate_git_sha": readiness.get("pilot_candidate_git_sha"),
        "rig_validation_report_sha256": readiness.get("rig_validation_report_sha256"),
    }
    if not _digest(expected_binding["pilot_report_sha256"], 64):
        errors.append("readiness.pilot_report_sha256 is invalid")
    if not _digest(expected_binding["pilot_candidate_git_sha"], 40):
        errors.append("readiness.pilot_candidate_git_sha is invalid")
    if not _digest(expected_binding["rig_validation_report_sha256"], 64):
        errors.append("readiness.rig_validation_report_sha256 is invalid")

    preview = machine.get("preview")
    if not isinstance(preview, dict):
        errors.append("machine_probe.preview is missing")
        preview = {}
    _expect(errors, "preview.executed", preview.get("executed"), False)
    _expect(errors, "preview.route", preview.get("route"), ROUTE)
    steps = preview.get("steps")
    if not isinstance(steps, int) or isinstance(steps, bool) or steps < 1:
        errors.append("preview.steps must be a positive integer")
    tools = preview.get("tools")
    if not isinstance(tools, list) or not tools or any(
        not isinstance(tool, str) or not tool for tool in tools
    ):
        errors.append("preview.tools must contain non-empty tool names")
    elif isinstance(steps, int) and len(tools) != steps:
        errors.append("preview.tools count does not match preview.steps")
    preview_binding = _validate_binding(
        errors,
        "preview.readiness_binding",
        preview.get("readiness_binding"),
        expected_binding,
    )
    preview_receipt = _validate_receipt(
        errors,
        "preview.capability_receipt",
        preview.get("capability_receipt"),
    )

    run = machine.get("run")
    if not isinstance(run, dict):
        errors.append("machine_probe.run is missing")
        run = {}
    _expect(errors, "run.state", run.get("state"), "completed")
    _expect(errors, "run.terminal", run.get("terminal"), True)
    _expect(errors, "run.answer_present", run.get("answer_present"), True)
    if run.get("error") not in {None, ""}:
        errors.append("run.error is not empty")
    run_steps = run.get("steps")
    if not isinstance(run_steps, int) or isinstance(run_steps, bool) or run_steps < 1:
        errors.append("run.steps must be a positive integer")
    elif isinstance(steps, int) and run_steps != steps:
        errors.append("run.steps does not match preview.steps")
    states = run.get("step_states")
    if not isinstance(states, list) or not states or any(state != "succeeded" for state in states):
        errors.append("not every task UI machine-probe step succeeded")
    elif isinstance(run_steps, int) and len(states) != run_steps:
        errors.append("run.step_states count does not match run.steps")
    kinds = run.get("event_kinds")
    if not isinstance(kinds, list):
        errors.append("run.event_kinds is missing")
        kinds = []
    forbidden = {"confirmation_required", "confirmation_approved", "confirmation_denied"}
    if any(kind in forbidden for kind in kinds):
        errors.append("run contains a confirmation event")
    if "run_completed" not in kinds:
        errors.append("run does not contain run_completed")
    run_binding = _validate_binding(
        errors,
        "run.readiness_binding",
        run.get("readiness_binding"),
        expected_binding,
    )
    run_receipt = _validate_receipt(
        errors,
        "run.capability_receipt",
        run.get("capability_receipt"),
    )
    if preview_binding is not None and run_binding is not None and preview_binding != run_binding:
        errors.append("preview and run readiness bindings differ")
    if preview_receipt is not None and run_receipt is not None and preview_receipt != run_receipt:
        errors.append("preview and run capability receipts differ")
    if not _digest(machine.get("run_id_sha256"), 64):
        errors.append("machine_probe.run_id_sha256 is invalid")
    if not _digest(machine.get("message_sha256"), 64):
        errors.append("machine_probe.message_sha256 is invalid")

    physical = report.get("physical_clients")
    if not isinstance(physical, dict):
        errors.append("physical_clients is missing")
        physical = {}
    observed = _parse_time(physical.get("observed_at"))
    generated = _parse_time(report.get("generated_at"))
    if observed is None:
        errors.append("physical_clients.observed_at is invalid")
    if generated is None:
        errors.append("generated_at is invalid")
    if observed is not None and generated is not None:
        age_hours = (generated - observed).total_seconds() / 3600.0
        if age_hours < -0.25 or age_hours > 24.0:
            errors.append(
                f"physical client observations are {age_hours:.2f}h from report generation; allowed 0..24h"
            )
    operator = physical.get("operator")
    if not isinstance(operator, str) or not operator.strip():
        errors.append("physical_clients.operator must be a non-empty string")
    clients = physical.get("clients")
    if not isinstance(clients, dict) or set(clients) != {"android", "desktop"}:
        errors.append("physical_clients.clients must contain exactly android and desktop")
        clients = {}
    artifact_summaries: dict[str, Any] = {}
    for name, expected_platform in (("android", "android"), ("desktop", "windows")):
        client = clients.get(name)
        if not isinstance(client, dict):
            errors.append(f"physical_clients.clients.{name} is missing")
            continue
        label = f"physical_clients.clients.{name}"
        _expect(errors, f"{label}.platform", client.get("platform"), expected_platform)
        if not isinstance(client.get("device"), str) or not client["device"].strip():
            errors.append(f"{label}.device must be a non-empty string")
        for key in ("version", "git_sha", "code_sha256"):
            _expect(errors, f"{label}.candidate.{key}", _nested(client, "candidate", key), candidate[key])
        _expect(errors, f"{label}.selected_surface", client.get("selected_surface"), SURFACE)
        _expect(errors, f"{label}.fallback_surface", client.get("fallback_surface"), FALLBACK)
        _expect(errors, f"{label}.server_reason", client.get("server_reason"), SELECTED_REASON)
        _expect(errors, f"{label}.stop_terminal_state", client.get("stop_terminal_state"), "cancelled")
        _expect(errors, f"{label}.normal_chat_surface", client.get("normal_chat_surface"), FALLBACK)
        checks = client.get("checks")
        if not isinstance(checks, dict):
            errors.append(f"{label}.checks is missing")
        else:
            missing_checks = [check for check in REQUIRED_CLIENT_CHECKS if checks.get(check) is not True]
            if missing_checks:
                errors.append(f"{label}.checks are not all true: {', '.join(missing_checks)}")
        artifact = _validate_artifact(errors, root=root, label=label, value=client.get("artifact"))
        if artifact is not None:
            artifact_summaries[name] = artifact

    result["summary"] = {
        "machine_probe_completed": machine.get("completed"),
        "selected_surface": readiness.get("selected_surface"),
        "fallback_surface": readiness.get("fallback_surface"),
        "pilot_candidate_git_sha": readiness.get("pilot_candidate_git_sha"),
        "steps": run.get("steps"),
        "terminal_state": run.get("state"),
        "android_passed": _nested(report, "summary", "android_passed"),
        "desktop_passed": _nested(report, "summary", "desktop_passed"),
        "artifacts": artifact_summaries,
        "production_activation": _nested(report, "gate", "production_activation"),
    }
