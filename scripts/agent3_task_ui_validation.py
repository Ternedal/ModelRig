#!/usr/bin/env python3
"""Produce candidate-bound physical evidence for the normal Agent 3 task UI.

The harness performs one live read-only task through the same backend routes used
by Android and desktop, then combines that machine proof with compact,
hash-bound physical observations from both clients. It never changes feature
flags, never calls generic Agent 3 routes, never confirms writes and never copies
the device token into the report.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import platform
import re
import socket
import tempfile
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPORT_SCHEMA = "kaliv-agent3-task-ui-validation/v1"
OBSERVATIONS_SCHEMA = "kaliv-agent3-task-ui-observations/v1"
DEFAULT_REPORT = Path("validation/agent3-task-ui-validation-latest.json")
DEFAULT_OBSERVATIONS = Path("validation/agent3-task-ui-observations.json")
EVIDENCE_ROOT = Path("validation/agent3-task-ui-evidence")
MAX_ARTIFACT_BYTES = 32 * 1024 * 1024
SURFACE = "agent3_readonly"
FALLBACK = "agent2"
SELECTED_REASON = "agent3_readonly_selected"
ROUTE = "rig_tools_local"
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
GIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
OPAQUE_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,200}$")
TERMINAL_STATES = {"completed", "failed", "cancelled", "blocked"}
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


class TaskUiValidationError(RuntimeError):
    """The physical task-UI report cannot be trusted."""


def _safe_error(exc: Exception) -> dict[str, str]:
    return {
        "type": type(exc).__name__,
        "message": str(exc).replace("\r", " ").replace("\n", " ")[:500],
    }


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
        temp = Path(handle.name)
    temp.replace(path)


def _load_campaign_module():
    path = Path(__file__).resolve().parent / "physical_validation_campaign.py"
    spec = importlib.util.spec_from_file_location("task_ui_campaign_identity", path)
    if spec is None or spec.loader is None:
        raise TaskUiValidationError("physical validation campaign cannot be loaded")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def candidate_identity(root: Path) -> dict[str, Any]:
    try:
        value = _load_campaign_module().candidate_identity(root)
    except Exception as exc:
        raise TaskUiValidationError(f"candidate identity failed: {exc}") from exc
    required = ("version", "git_sha", "code_sha256")
    if not isinstance(value, dict) or any(not value.get(key) for key in required):
        raise TaskUiValidationError("candidate identity is incomplete")
    return value


def _load_json(path: Path, label: str) -> dict[str, Any]:
    if path.is_symlink():
        raise TaskUiValidationError(f"{label} must not be a symlink")
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise TaskUiValidationError(f"{label} cannot be read: {path}") from exc
    if not raw:
        raise TaskUiValidationError(f"{label} is empty")
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise TaskUiValidationError(f"{label} is not valid UTF-8 JSON") from exc
    if not isinstance(value, dict):
        raise TaskUiValidationError(f"{label} must be a JSON object")
    return value


def _parse_time(value: Any, label: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise TaskUiValidationError(f"{label} must be a timezone-aware ISO-8601 timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise TaskUiValidationError(f"{label} is not valid ISO-8601") from exc
    if parsed.tzinfo is None:
        raise TaskUiValidationError(f"{label} must include a timezone")
    return parsed.astimezone(timezone.utc)


def _expect(value: Any, expected: Any, label: str) -> None:
    if value != expected:
        raise TaskUiValidationError(f"{label} mismatch: expected {expected!r}, got {value!r}")


def _nonempty(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise TaskUiValidationError(f"{label} must be a non-empty string")
    return value.strip()


def _artifact(root: Path, *, path_value: Any, digest_value: Any, label: str) -> dict[str, Any]:
    raw_path = Path(_nonempty(path_value, f"{label}.evidence_path"))
    if raw_path.is_absolute() or ".." in raw_path.parts:
        raise TaskUiValidationError(f"{label}.evidence_path must be repository-relative")
    unresolved = root / raw_path
    if unresolved.is_symlink():
        raise TaskUiValidationError(f"{label}.evidence_path must not be a symlink")
    resolved = unresolved.resolve()
    try:
        relative = resolved.relative_to(root.resolve())
    except ValueError as exc:
        raise TaskUiValidationError(f"{label}.evidence_path escapes the repository") from exc
    if relative.parts[:2] != EVIDENCE_ROOT.parts:
        raise TaskUiValidationError(
            f"{label}.evidence_path must be under {EVIDENCE_ROOT.as_posix()}"
        )
    if not resolved.is_file():
        raise TaskUiValidationError(f"{label}.evidence artifact is missing")
    size = resolved.stat().st_size
    if size <= 0 or size > MAX_ARTIFACT_BYTES:
        raise TaskUiValidationError(
            f"{label}.evidence artifact must be 1..{MAX_ARTIFACT_BYTES} bytes"
        )
    raw = resolved.read_bytes()
    actual = hashlib.sha256(raw).hexdigest()
    if not isinstance(digest_value, str) or not SHA256_RE.fullmatch(digest_value):
        raise TaskUiValidationError(f"{label}.evidence_sha256 is invalid")
    if actual != digest_value:
        raise TaskUiValidationError(f"{label}.evidence_sha256 does not match the artifact")
    return {"path": relative.as_posix(), "sha256": actual, "bytes": size}


def load_observations(
    path: Path,
    *,
    root: Path,
    candidate: dict[str, Any],
    now: datetime,
    max_observation_age_hours: float,
) -> dict[str, Any]:
    value = _load_json(path, "task UI observations")
    _expect(value.get("schema"), OBSERVATIONS_SCHEMA, "observations.schema")
    observed = _parse_time(value.get("observed_at"), "observations.observed_at")
    age_hours = (now - observed).total_seconds() / 3600.0
    if age_hours < -0.25 or age_hours > max_observation_age_hours:
        raise TaskUiValidationError(
            f"observations are {age_hours:.2f}h old; allowed 0..{max_observation_age_hours:.2f}h"
        )
    operator = _nonempty(value.get("operator"), "observations.operator")
    clients = value.get("clients")
    if not isinstance(clients, dict) or set(clients) != {"android", "desktop"}:
        raise TaskUiValidationError("observations.clients must contain exactly android and desktop")

    summaries: dict[str, Any] = {}
    for name, expected_platform in (("android", "android"), ("desktop", "windows")):
        client = clients.get(name)
        if not isinstance(client, dict):
            raise TaskUiValidationError(f"clients.{name} must be an object")
        _expect(client.get("platform"), expected_platform, f"clients.{name}.platform")
        device = _nonempty(client.get("device"), f"clients.{name}.device")
        build = client.get("candidate")
        if not isinstance(build, dict):
            raise TaskUiValidationError(f"clients.{name}.candidate is missing")
        for key in ("version", "git_sha", "code_sha256"):
            _expect(build.get(key), candidate[key], f"clients.{name}.candidate.{key}")
        _expect(client.get("selected_surface"), SURFACE, f"clients.{name}.selected_surface")
        _expect(client.get("fallback_surface"), FALLBACK, f"clients.{name}.fallback_surface")
        _expect(client.get("server_reason"), SELECTED_REASON, f"clients.{name}.server_reason")
        _expect(client.get("stop_terminal_state"), "cancelled", f"clients.{name}.stop_terminal_state")
        _expect(client.get("normal_chat_surface"), FALLBACK, f"clients.{name}.normal_chat_surface")
        checks = client.get("checks")
        if not isinstance(checks, dict):
            raise TaskUiValidationError(f"clients.{name}.checks is missing")
        missing = [check for check in REQUIRED_CLIENT_CHECKS if checks.get(check) is not True]
        if missing:
            raise TaskUiValidationError(
                f"clients.{name}.checks are not all true: {', '.join(missing)}"
            )
        artifact = _artifact(
            root,
            path_value=client.get("evidence_path"),
            digest_value=client.get("evidence_sha256"),
            label=f"clients.{name}",
        )
        summaries[name] = {
            "platform": expected_platform,
            "device": device,
            "candidate": {key: build[key] for key in ("version", "git_sha", "code_sha256")},
            "selected_surface": client["selected_surface"],
            "fallback_surface": client["fallback_surface"],
            "server_reason": client["server_reason"],
            "stop_terminal_state": client["stop_terminal_state"],
            "normal_chat_surface": client["normal_chat_surface"],
            "checks": {key: True for key in REQUIRED_CLIENT_CHECKS},
            "artifact": artifact,
        }
    return {
        "observed_at": observed.isoformat(),
        "age_hours": round(age_hours, 3),
        "operator": operator,
        "clients": summaries,
    }


def _request_json(
    base_url: str,
    token: str,
    method: str,
    path: str,
    *,
    payload: dict[str, Any] | None = None,
    timeout_s: float,
) -> tuple[int, dict[str, Any]]:
    body = None
    headers = {
        "Accept": "application/json",
        "Authorization": f"Bearer {token}",
    }
    if payload is not None:
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(
        base_url.rstrip("/") + path,
        data=body,
        headers=headers,
        method=method,
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_s) as response:
            status = response.status
            raw = response.read()
    except urllib.error.HTTPError as exc:
        detail = exc.read(4096).decode("utf-8", errors="replace")
        raise TaskUiValidationError(f"{method} {path} returned HTTP {exc.code}: {detail[:500]}") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise TaskUiValidationError(f"{method} {path} failed: {exc}") from exc
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise TaskUiValidationError(f"{method} {path} returned invalid JSON") from exc
    if not isinstance(value, dict):
        raise TaskUiValidationError(f"{method} {path} did not return a JSON object")
    return status, value


def _validate_readiness(value: dict[str, Any], candidate: dict[str, Any]) -> dict[str, Any]:
    _expect(value.get("schema"), "kaliv-agent3-task-readiness/v1", "readiness.schema")
    _expect(value.get("selected_surface"), SURFACE, "readiness.selected_surface")
    _expect(value.get("candidate_surface"), SURFACE, "readiness.candidate_surface")
    _expect(value.get("fallback_surface"), FALLBACK, "readiness.fallback_surface")
    _expect(value.get("eligible_for_task_ui"), True, "readiness.eligible_for_task_ui")
    _expect(value.get("operator_enabled"), True, "readiness.operator_enabled")
    _expect(value.get("normal_chat_route_unchanged"), True, "readiness.normal_chat_route_unchanged")
    _expect(value.get("production_activation"), False, "readiness.production_activation")
    _expect(value.get("reason"), SELECTED_REASON, "readiness.reason")
    _expect(value.get("reasons"), [], "readiness.reasons")
    pilot = value.get("pilot")
    rig = value.get("rig_validation")
    ui = value.get("ui_contract")
    if not isinstance(pilot, dict) or not isinstance(rig, dict) or not isinstance(ui, dict):
        raise TaskUiValidationError("readiness evidence or UI contract is missing")
    for key in (
        "configured", "present", "structurally_valid", "fresh",
        "version_match", "code_match", "stop_fallback_proven",
    ):
        _expect(pilot.get(key), True, f"readiness.pilot.{key}")
    _expect(pilot.get("tasks"), 20, "readiness.pilot.tasks")
    _expect(pilot.get("successes"), 20, "readiness.pilot.successes")
    _expect(pilot.get("failures"), 0, "readiness.pilot.failures")
    _expect(pilot.get("retry_events"), 0, "readiness.pilot.retry_events")
    _expect(pilot.get("candidate_git_sha"), candidate["git_sha"], "readiness.pilot.candidate_git_sha")
    for key in ("eligible_for_developer_preview", "version_match", "code_match"):
        _expect(rig.get(key), True, f"readiness.rig_validation.{key}")
    pilot_sha = pilot.get("report_sha256")
    rig_sha = rig.get("report_sha256")
    if not isinstance(pilot_sha, str) or not SHA256_RE.fullmatch(pilot_sha):
        raise TaskUiValidationError("readiness.pilot.report_sha256 is invalid")
    if not isinstance(rig_sha, str) or not SHA256_RE.fullmatch(rig_sha):
        raise TaskUiValidationError("readiness.rig_validation.report_sha256 is invalid")
    expected_ui = {
        "route_source": "server_authoritative",
        "stop_visible": True,
        "fallback_visible": True,
        "receipts_visible": True,
        "replans_visible": True,
        "outcomes_visible": True,
    }
    for key, expected in expected_ui.items():
        _expect(ui.get(key), expected, f"readiness.ui_contract.{key}")
    return {
        "selected_surface": SURFACE,
        "fallback_surface": FALLBACK,
        "reason": SELECTED_REASON,
        "pilot_report_sha256": pilot_sha,
        "pilot_candidate_git_sha": pilot["candidate_git_sha"],
        "rig_validation_report_sha256": rig_sha,
        "pilot_tasks": pilot["tasks"],
        "pilot_successes": pilot["successes"],
        "pilot_replans": pilot.get("replans"),
        "pilot_retry_events": pilot["retry_events"],
        "stop_fallback_proven": True,
    }


def _validate_binding(value: Any, expected: dict[str, Any], label: str) -> dict[str, str]:
    if not isinstance(value, dict):
        raise TaskUiValidationError(f"{label} is missing")
    binding = {
        "pilot_report_sha256": value.get("pilot_report_sha256"),
        "pilot_candidate_git_sha": value.get("pilot_candidate_git_sha"),
        "rig_validation_report_sha256": value.get("rig_validation_report_sha256"),
    }
    if not SHA256_RE.fullmatch(str(binding["pilot_report_sha256"] or "")):
        raise TaskUiValidationError(f"{label}.pilot_report_sha256 is invalid")
    if not GIT_SHA_RE.fullmatch(str(binding["pilot_candidate_git_sha"] or "")):
        raise TaskUiValidationError(f"{label}.pilot_candidate_git_sha is invalid")
    if not SHA256_RE.fullmatch(str(binding["rig_validation_report_sha256"] or "")):
        raise TaskUiValidationError(f"{label}.rig_validation_report_sha256 is invalid")
    for key, actual in binding.items():
        _expect(actual, expected[key], f"{label}.{key}")
    return {key: str(item) for key, item in binding.items()}


def _validate_receipt(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise TaskUiValidationError(f"{label} is missing")
    _expect(value.get("schema"), "kaliv-agent3-capability-receipt/v1", f"{label}.schema")
    _expect(value.get("route"), ROUTE, f"{label}.route")
    _expect(value.get("allowed"), True, f"{label}.allowed")
    _expect(value.get("blockers"), [], f"{label}.blockers")
    _expect(value.get("production_activation"), False, f"{label}.production_activation")
    graph = value.get("graph_sha256")
    plan = value.get("plan_sha256")
    if not isinstance(graph, str) or not SHA256_RE.fullmatch(graph):
        raise TaskUiValidationError(f"{label}.graph_sha256 is invalid")
    if not isinstance(plan, str) or not SHA256_RE.fullmatch(plan):
        raise TaskUiValidationError(f"{label}.plan_sha256 is invalid")
    return {
        "schema": value["schema"],
        "route": value["route"],
        "allowed": True,
        "blockers": [],
        "production_activation": False,
        "graph_sha256": graph,
        "plan_sha256": plan,
    }


def _validate_preview(value: dict[str, Any], readiness: dict[str, Any]) -> dict[str, Any]:
    for key, expected in (
        ("task_surface", SURFACE),
        ("selected_surface", SURFACE),
        ("fallback_surface", FALLBACK),
        ("reason", SELECTED_REASON),
        ("executed", False),
        ("production_activation", False),
        ("normal_chat_route_unchanged", True),
    ):
        _expect(value.get(key), expected, f"preview.{key}")
    route = value.get("route")
    if not isinstance(route, dict):
        raise TaskUiValidationError("preview.route is missing")
    for key, expected in (
        ("kind", ROUTE), ("uses_cloud", False), ("uses_rig", True),
        ("uses_tools", True), ("uses_rag", False),
    ):
        _expect(route.get(key), expected, f"preview.route.{key}")
    plan = value.get("plan")
    if not isinstance(plan, list) or not plan:
        raise TaskUiValidationError("preview.plan must contain at least one step")
    tools: list[str] = []
    for index, step in enumerate(plan):
        if not isinstance(step, dict):
            raise TaskUiValidationError(f"preview.plan[{index}] is invalid")
        _expect(step.get("risk"), "read", f"preview.plan[{index}].risk")
        _expect(step.get("egress"), "local", f"preview.plan[{index}].egress")
        _expect(step.get("idempotent"), True, f"preview.plan[{index}].idempotent")
        tools.append(_nonempty(step.get("tool"), f"preview.plan[{index}].tool"))
    plan_id = value.get("plan_id")
    if not isinstance(plan_id, str) or not OPAQUE_ID_RE.fullmatch(plan_id):
        raise TaskUiValidationError("preview.plan_id is invalid")
    binding = _validate_binding(value.get("readiness_binding"), readiness, "preview.readiness_binding")
    receipt = _validate_receipt(value.get("capability_receipt"), "preview.capability_receipt")
    return {
        "plan_id": plan_id,
        "steps": len(plan),
        "tools": tools,
        "route": ROUTE,
        "executed": False,
        "readiness_binding": binding,
        "capability_receipt": receipt,
    }


def _validate_snapshot(
    value: dict[str, Any],
    *,
    expected_binding: dict[str, str],
    expected_receipt: dict[str, Any],
    expected_run_id: str | None = None,
) -> dict[str, Any]:
    for key, expected in (
        ("task_surface", SURFACE),
        ("selected_surface", SURFACE),
        ("fallback_surface", FALLBACK),
        ("reason", SELECTED_REASON),
        ("production_activation", False),
        ("normal_chat_route_unchanged", True),
    ):
        _expect(value.get(key), expected, f"snapshot.{key}")
    binding = _validate_binding(value.get("readiness_binding"), expected_binding, "snapshot.readiness_binding")
    receipt = _validate_receipt(value.get("capability_receipt"), "snapshot.capability_receipt")
    _expect(receipt, expected_receipt, "snapshot.capability_receipt")
    run = value.get("run")
    if not isinstance(run, dict):
        raise TaskUiValidationError("snapshot.run is missing")
    run_id = run.get("id")
    if not isinstance(run_id, str) or not OPAQUE_ID_RE.fullmatch(run_id):
        raise TaskUiValidationError("snapshot.run.id is invalid")
    if expected_run_id is not None:
        _expect(run_id, expected_run_id, "snapshot.run.id")
    route = run.get("route")
    if not isinstance(route, dict):
        raise TaskUiValidationError("snapshot.run.route is missing")
    _expect(route.get("kind"), ROUTE, "snapshot.run.route.kind")
    state = run.get("state")
    if not isinstance(state, str):
        raise TaskUiValidationError("snapshot.run.state is invalid")
    terminal = value.get("terminal")
    _expect(terminal, state in TERMINAL_STATES, "snapshot.terminal")
    if state == "waiting_confirmation":
        raise TaskUiValidationError("read-only task requested confirmation")
    steps = run.get("steps")
    if not isinstance(steps, list) or not steps:
        raise TaskUiValidationError("snapshot.run.steps is missing")
    events = value.get("events")
    if not isinstance(events, list):
        raise TaskUiValidationError("snapshot.events is missing")
    kinds = [
        item.get("kind")
        for item in events
        if isinstance(item, dict) and isinstance(item.get("kind"), str)
    ]
    if any(kind in {"confirmation_required", "confirmation_approved", "confirmation_denied"} for kind in kinds):
        raise TaskUiValidationError("read-only task emitted a confirmation event")
    return {
        "run_id": run_id,
        "state": state,
        "terminal": bool(terminal),
        "steps": len(steps),
        "step_states": [item.get("state") if isinstance(item, dict) else None for item in steps],
        "event_kinds": kinds,
        "answer_present": isinstance(run.get("answer"), str) and bool(run.get("answer").strip()),
        "error": run.get("error"),
        "readiness_binding": binding,
        "capability_receipt": receipt,
    }


def live_probe(
    *,
    base_url: str,
    token: str,
    candidate: dict[str, Any],
    message: str,
    timeout_s: float,
    poll_interval_s: float,
) -> dict[str, Any]:
    started = time.monotonic()
    status, readiness_raw = _request_json(
        base_url, token, "GET", "/api/v1/experimental/agent3/task-readiness",
        timeout_s=min(timeout_s, 20.0),
    )
    _expect(status, 200, "readiness.http_status")
    readiness = _validate_readiness(readiness_raw, candidate)

    status, preview_raw = _request_json(
        base_url, token, "POST", "/api/v1/experimental/agent3/task/plan",
        payload={"message": message},
        timeout_s=timeout_s,
    )
    _expect(status, 200, "preview.http_status")
    preview = _validate_preview(preview_raw, readiness)

    status, start_raw = _request_json(
        base_url, token, "POST",
        f"/api/v1/experimental/agent3/task/plans/{preview['plan_id']}/start",
        payload={},
        timeout_s=timeout_s,
    )
    _expect(status, 202, "start.http_status")
    snapshot = _validate_snapshot(
        start_raw,
        expected_binding=preview["readiness_binding"],
        expected_receipt=preview["capability_receipt"],
    )
    run_id = snapshot["run_id"]
    deadline = time.monotonic() + timeout_s
    polls = 0
    try:
        while not snapshot["terminal"]:
            if time.monotonic() >= deadline:
                raise TaskUiValidationError(
                    "read-only task did not reach a terminal state before timeout"
                )
            time.sleep(poll_interval_s)
            polls += 1
            status, current = _request_json(
                base_url, token, "GET",
                f"/api/v1/experimental/agent3/task/runs/{run_id}",
                timeout_s=min(timeout_s, 20.0),
            )
            _expect(status, 200, "status.http_status")
            snapshot = _validate_snapshot(
                current,
                expected_binding=preview["readiness_binding"],
                expected_receipt=preview["capability_receipt"],
                expected_run_id=run_id,
            )
        _expect(snapshot["state"], "completed", "terminal run state")
        if any(state != "succeeded" for state in snapshot["step_states"]):
            raise TaskUiValidationError("not every live-probe step succeeded")
        if snapshot["error"] not in {None, ""}:
            raise TaskUiValidationError("live probe completed with an error")
    except Exception:
        if not snapshot.get("terminal"):
            try:
                _request_json(
                    base_url, token, "POST",
                    f"/api/v1/experimental/agent3/task/runs/{run_id}/cancel",
                    payload={},
                    timeout_s=min(timeout_s, 20.0),
                )
            except Exception:
                pass
        raise
    return {
        "completed": True,
        "duration_ms": round((time.monotonic() - started) * 1000.0, 3),
        "polls": polls,
        "readiness": readiness,
        "preview": {key: value for key, value in preview.items() if key != "plan_id"},
        "run": {key: value for key, value in snapshot.items() if key != "run_id"},
        "run_id_sha256": hashlib.sha256(run_id.encode("utf-8")).hexdigest(),
        "message_sha256": hashlib.sha256(message.encode("utf-8")).hexdigest(),
    }


def build_report(args: argparse.Namespace) -> tuple[dict[str, Any], int]:
    root = Path(__file__).resolve().parents[1]
    now = datetime.now(timezone.utc)
    candidate = candidate_identity(root)
    if candidate.get("working_tree_clean") is False:
        raise TaskUiValidationError("candidate working tree is not clean")
    if candidate.get("version_stamps_consistent") is not True:
        raise TaskUiValidationError("candidate version stamps are inconsistent")
    observations = load_observations(
        args.manual_observations,
        root=root,
        candidate=candidate,
        now=now,
        max_observation_age_hours=args.max_observation_age_hours,
    )
    token = os.getenv("MODELRIG_TOKEN", "")
    if not token.strip():
        raise TaskUiValidationError("MODELRIG_TOKEN is required")
    probe = live_probe(
        base_url=args.base_url,
        token=token.strip(),
        candidate=candidate,
        message=args.message,
        timeout_s=args.timeout_seconds,
        poll_interval_s=args.poll_interval_seconds,
    )
    report = {
        "schema": REPORT_SCHEMA,
        "generated_at": now.isoformat(),
        "candidate": candidate,
        "host": {
            "hostname": socket.gethostname(),
            "platform": platform.platform(),
            "python": platform.python_version(),
        },
        "configuration": {
            "base_url": args.base_url.rstrip("/"),
            "timeout_seconds": args.timeout_seconds,
            "poll_interval_seconds": args.poll_interval_seconds,
            "max_observation_age_hours": args.max_observation_age_hours,
            "token_recorded": False,
            "production_activation": False,
        },
        "machine_probe": probe,
        "physical_clients": observations,
        "summary": {
            "machine_probe_completed": True,
            "android_passed": True,
            "desktop_passed": True,
            "clients": 2,
            "artifacts": 2,
        },
        "gate": {
            "passed": True,
            "production_activation": False,
            "normal_chat_route_unchanged": True,
        },
    }
    return report, 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8080")
    parser.add_argument("--manual-observations", type=Path, default=DEFAULT_OBSERVATIONS)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--message", default="Læs riggens status og opsummér forbindelsen.")
    parser.add_argument("--timeout-seconds", type=float, default=120.0)
    parser.add_argument("--poll-interval-seconds", type=float, default=0.5)
    parser.add_argument("--max-observation-age-hours", type=float, default=24.0)
    args = parser.parse_args(argv)
    if not args.message.strip() or len(args.message) > 20_000:
        parser.error("--message must contain 1..20000 characters")
    if args.timeout_seconds <= 0 or args.timeout_seconds > 900:
        parser.error("--timeout-seconds must be greater than 0 and at most 900")
    if args.poll_interval_seconds <= 0 or args.poll_interval_seconds > 10:
        parser.error("--poll-interval-seconds must be greater than 0 and at most 10")
    if args.max_observation_age_hours <= 0 or args.max_observation_age_hours > 168:
        parser.error("--max-observation-age-hours must be greater than 0 and at most 168")
    try:
        report, exit_code = build_report(args)
    except Exception as exc:
        report = {
            "schema": REPORT_SCHEMA,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "error": _safe_error(exc),
            "summary": {
                "machine_probe_completed": False,
                "android_passed": False,
                "desktop_passed": False,
                "clients": 0,
                "artifacts": 0,
            },
            "gate": {
                "passed": False,
                "production_activation": False,
                "normal_chat_route_unchanged": True,
            },
        }
        exit_code = 1
    _write_json_atomic(args.report, report)
    print(f"report: {args.report}")
    print("gate: " + ("PASS" if report.get("gate", {}).get("passed") else "BLOCKED"))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
