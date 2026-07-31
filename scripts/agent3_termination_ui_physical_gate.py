#!/usr/bin/env python3
"""Independently validate candidate-bound physical T-023 UI evidence.

This reader does not trust the producer's ``success`` bit. It rechecks the
candidate, observation sheet, capability inventory, platform/case matrix and
every evidence artifact. It performs no network request and changes no runtime
state.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

SCHEMA = "kaliv-agent3-termination-ui-physical/v1"
OBSERVATIONS_SCHEMA = "kaliv-agent3-termination-ui-observations/v1"
DEFAULT_REPORT = Path("validation/agent3-termination-ui-physical-latest.json")
MAX_EVIDENCE_BYTES = 32 * 1024 * 1024
MAX_AGE_HOURS = 24.0
MAX_WINDOW_HOURS = 12.0
PLATFORMS = ("android", "windows")
BASE_CASES = ("non_interruptible", "cooperative_declaration", "late_completion")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_GIT_SHA = re.compile(r"^[0-9a-f]{40}$")
_TERMINAL_TOOL_STATES = {"succeeded", "failed", "cancelled", "completed_after_cancel"}


class TerminationPhysicalGateError(RuntimeError):
    """The T-023 evidence cannot be read safely."""


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


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


def _resolve_under(root: Path, raw: Path) -> Path:
    unresolved = raw if raw.is_absolute() else root / raw
    if unresolved.is_symlink():
        raise TerminationPhysicalGateError(f"evidence path is a symlink: {raw}")
    resolved = unresolved.resolve()
    try:
        resolved.relative_to(root.resolve())
    except ValueError as exc:
        raise TerminationPhysicalGateError(f"evidence path escapes repository: {raw}") from exc
    return resolved


def _load_json(root: Path, raw_path: Path) -> tuple[dict[str, Any], bytes, Path]:
    path = _resolve_under(root, raw_path)
    if not path.exists():
        raise FileNotFoundError(path)
    if not path.is_file() or path.is_symlink():
        raise TerminationPhysicalGateError(f"evidence file is irregular: {raw_path}")
    size = path.stat().st_size
    if size <= 0 or size > MAX_EVIDENCE_BYTES:
        raise TerminationPhysicalGateError(f"evidence size is invalid: {raw_path} ({size})")
    raw = path.read_bytes()
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise TerminationPhysicalGateError(f"evidence is not UTF-8 JSON: {raw_path}") from exc
    if not isinstance(value, dict):
        raise TerminationPhysicalGateError(f"evidence is not a JSON object: {raw_path}")
    return value, raw, path


def _same_candidate(
    errors: list[str], label: str, actual: Any, expected: Mapping[str, Any]
) -> None:
    if not isinstance(actual, Mapping):
        errors.append(f"{label} candidate is missing")
        return
    for key in ("version", "git_sha", "code_sha256", "identity_source"):
        if actual.get(key) != expected.get(key):
            errors.append(f"{label} candidate.{key} mismatch")


def _require_true(errors: list[str], label: str, value: Any) -> None:
    if value is not True:
        errors.append(f"{label} must be true")


def _require_false(errors: list[str], label: str, value: Any) -> None:
    if value is not False:
        errors.append(f"{label} must be false")


def _fresh(
    errors: list[str], label: str, value: Any, *, now: datetime, hours: float
) -> datetime | None:
    observed = _timestamp(value)
    if observed is None:
        errors.append(f"{label} is not a timezone-aware timestamp")
        return None
    age = (now - observed).total_seconds() / 3600.0
    if age < -0.25:
        errors.append(f"{label} is in the future")
    elif age > hours:
        errors.append(f"{label} is {age:.1f}h old; max is {hours:.1f}h")
    return observed


def _validate_inventory(errors: list[str], value: Any) -> dict[str, list[str]]:
    if not isinstance(value, Mapping):
        errors.append("capability_inventory is missing")
        return {"none": [], "cooperative": [], "runtime": []}
    if set(value) != {"none", "cooperative", "runtime"}:
        errors.append("capability_inventory modes mismatch")
    result: dict[str, list[str]] = {}
    all_tools: list[str] = []
    for mode in ("none", "cooperative", "runtime"):
        tools = value.get(mode)
        if not isinstance(tools, list) or any(
            not isinstance(item, str) or not item for item in tools
        ):
            errors.append(f"capability_inventory.{mode} is invalid")
            tools = []
        if len(tools) != len(set(tools)) or tools != sorted(tools):
            errors.append(f"capability_inventory.{mode} is not unique and sorted")
        result[mode] = list(tools)
        all_tools.extend(tools)
    if len(all_tools) != len(set(all_tools)):
        errors.append("capability inventory assigns a tool to multiple modes")
    return result


def _artifact(
    *,
    root: Path,
    platform: str,
    case_name: str,
    metadata: Any,
    errors: list[str],
) -> dict[str, Any] | None:
    label = f"{platform}.{case_name}.artifact"
    if not isinstance(metadata, Mapping):
        errors.append(f"{label} metadata is missing")
        return None
    path_value = metadata.get("path")
    digest_value = metadata.get("sha256")
    bytes_value = metadata.get("bytes")
    if not isinstance(path_value, str) or not path_value:
        errors.append(f"{label}.path is missing")
        return None
    relative = Path(path_value)
    required = ("validation", "agent3-termination-ui-evidence", platform)
    if relative.is_absolute() or ".." in relative.parts:
        errors.append(f"{label}.path escapes the repository")
        return None
    if relative.parts[:3] != required:
        errors.append(
            f"{label}.path must be under validation/agent3-termination-ui-evidence/{platform}"
        )
        return None
    path = _resolve_under(root, relative)
    if not path.is_file() or path.is_symlink():
        errors.append(f"{label} is missing or irregular")
        return None
    size = path.stat().st_size
    if size <= 0 or size > MAX_EVIDENCE_BYTES:
        errors.append(f"{label}.bytes is outside the allowed range")
        return None
    raw = path.read_bytes()
    actual = _sha(raw)
    if not isinstance(digest_value, str) or _SHA256.fullmatch(digest_value) is None:
        errors.append(f"{label}.sha256 is invalid")
    elif digest_value != actual:
        errors.append(f"{label}.sha256 does not match the artifact")
    if bytes_value != size:
        errors.append(f"{label}.bytes does not match the artifact")
    return {"path": str(relative), "sha256": actual, "bytes": size}


def _case_maps(value: Any) -> dict[str, Mapping[str, Any]]:
    if not isinstance(value, list):
        return {}
    return {
        item.get("name"): item
        for item in value
        if isinstance(item, Mapping) and isinstance(item.get("name"), str)
    }


def validate_report(
    *,
    root: Path,
    report: Mapping[str, Any],
    candidate: Mapping[str, Any],
    now: datetime,
    max_age_hours: float,
) -> tuple[list[str], dict[str, Any]]:
    errors: list[str] = []
    if report.get("schema") != SCHEMA:
        errors.append("termination UI report schema mismatch")
    if report.get("success") is not True:
        errors.append("termination UI report success is not true")
    if report.get("errors") not in ([], None):
        errors.append("termination UI report contains producer errors")
    _require_false(errors, "termination UI production_activation", report.get("production_activation"))
    _same_candidate(errors, "termination UI report", report.get("candidate"), candidate)
    strict_age = min(max_age_hours, MAX_AGE_HOURS)
    generated = _fresh(
        errors,
        "termination UI generated_at",
        report.get("generated_at"),
        now=now,
        hours=strict_age,
    )

    inventory = _validate_inventory(errors, report.get("capability_inventory"))
    expected_inventory_hash = _sha(_canonical(inventory))
    if report.get("capability_inventory_sha256") != expected_inventory_hash:
        errors.append("termination UI capability inventory digest mismatch")
    required_cases = BASE_CASES + (("runtime_bound",) if inventory["runtime"] else ())

    observations_path_value = report.get("observations_path")
    observations: dict[str, Any] = {}
    observations_raw = b""
    observations_file: Path | None = None
    if not isinstance(observations_path_value, str) or not observations_path_value:
        errors.append("termination UI observations_path is missing")
    else:
        raw_path = Path(observations_path_value)
        if raw_path.is_absolute() or ".." in raw_path.parts or raw_path.parts[:1] != ("validation",):
            errors.append("termination UI observations_path must remain under validation")
        else:
            try:
                observations, observations_raw, observations_file = _load_json(root, raw_path)
            except Exception as exc:
                errors.append(f"termination UI observations cannot be read: {type(exc).__name__}")
    if observations_raw:
        if report.get("observations_sha256") != _sha(observations_raw):
            errors.append("termination UI observations digest mismatch")
        if observations.get("schema") != OBSERVATIONS_SCHEMA:
            errors.append("termination UI observations schema mismatch")
        _same_candidate(errors, "termination UI observations", observations.get("candidate"), candidate)
        if observations.get("capability_inventory_sha256") != expected_inventory_hash:
            errors.append("termination UI observations inventory digest mismatch")
        _require_false(
            errors,
            "termination UI observations production_activation",
            observations.get("production_activation"),
        )

    summary = report.get("summary") if isinstance(report.get("summary"), Mapping) else {}
    _require_false(errors, "termination UI summary production_activation", summary.get("production_activation"))
    if summary.get("required_cases") != list(required_cases):
        errors.append("termination UI required case inventory mismatch")
    if summary.get("runtime_capabilities") != inventory["runtime"]:
        errors.append("termination UI runtime capability summary mismatch")
    expected_runtime_coverage = (
        "required" if inventory["runtime"] else "not_applicable_no_runtime_capability"
    )
    if summary.get("runtime_handle_coverage") != expected_runtime_coverage:
        errors.append("termination UI runtime handle coverage mismatch")

    report_platforms = (
        summary.get("platforms") if isinstance(summary.get("platforms"), Mapping) else {}
    )
    observation_platforms = (
        observations.get("platforms")
        if isinstance(observations.get("platforms"), Mapping)
        else {}
    )
    if set(report_platforms) != set(PLATFORMS):
        errors.append("termination UI report platform inventory mismatch")
    if observations and set(observation_platforms) != set(PLATFORMS):
        errors.append("termination UI observation platform inventory mismatch")

    timestamps: list[datetime] = []
    prepared = _timestamp(observations.get("prepared_at")) if observations else None
    if prepared is None:
        errors.append("termination UI observations prepared_at is invalid")
    else:
        timestamps.append(prepared)

    platform_details: dict[str, Any] = {}
    for platform in PLATFORMS:
        report_platform = report_platforms.get(platform)
        observation_platform = observation_platforms.get(platform)
        if not isinstance(report_platform, Mapping):
            errors.append(f"termination UI {platform} report is missing")
            continue
        if not isinstance(observation_platform, Mapping):
            errors.append(f"termination UI {platform} observations are missing")
            continue
        for field in ("device_name", "os_version"):
            value = report_platform.get(field)
            observed_value = observation_platform.get(field)
            if not isinstance(value, str) or not value.strip():
                errors.append(f"termination UI {platform}.{field} is missing")
            if value != observed_value:
                errors.append(f"termination UI {platform}.{field} differs from observations")
        if observation_platform.get("app_surface") != "Kaliv Opgaver":
            errors.append(f"termination UI {platform}.app_surface mismatch")

        report_cases = _case_maps(report_platform.get("cases"))
        observation_cases = _case_maps(observation_platform.get("cases"))
        if set(report_cases) != set(required_cases) or len(report_cases) != len(required_cases):
            errors.append(f"termination UI {platform} report cases mismatch")
        if set(observation_cases) != set(required_cases) or len(observation_cases) != len(required_cases):
            errors.append(f"termination UI {platform} observation cases mismatch")
        run_hashes: list[str] = []
        details: list[dict[str, Any]] = []
        for name in required_cases:
            report_case = report_cases.get(name)
            observed_case = observation_cases.get(name)
            if not isinstance(report_case, Mapping) or not isinstance(observed_case, Mapping):
                continue
            label = f"termination UI {platform}.{name}"
            run_hash = report_case.get("run_id_sha256")
            if not isinstance(run_hash, str) or _SHA256.fullmatch(run_hash) is None:
                errors.append(f"{label}.run_id_sha256 is invalid")
            elif run_hash != observed_case.get("run_id_sha256"):
                errors.append(f"{label}.run identity differs from observations")
            else:
                run_hashes.append(run_hash)
            observed_at = _fresh(
                errors,
                f"{label}.observed_at",
                observed_case.get("observed_at"),
                now=now,
                hours=strict_age,
            )
            if observed_at:
                timestamps.append(observed_at)

            expected_semantics = {
                "non_interruptible": "none",
                "cooperative_declaration": "cooperative",
                "late_completion": "none",
                "runtime_bound": "runtime",
            }[name]
            if report_case.get("semantics") != expected_semantics:
                errors.append(f"{label}.semantics mismatch")
            tool = report_case.get("tool")
            if tool not in inventory[expected_semantics]:
                errors.append(f"{label}.tool is not in the candidate inventory")
            if report_case.get("request_state_after") != "terminal":
                errors.append(f"{label}.request_state_after is not terminal")
            state_after = report_case.get("state_after")
            if name == "late_completion":
                if state_after != "completed_after_cancel":
                    errors.append(f"{label}.state_after is not completed_after_cancel")
            elif state_after not in _TERMINAL_TOOL_STATES:
                errors.append(f"{label}.state_after is not terminal")

            receipt = (
                observed_case.get("receipt")
                if isinstance(observed_case.get("receipt"), Mapping)
                else {}
            )
            plan = receipt.get("plan") if isinstance(receipt.get("plan"), Mapping) else {}
            stream = (
                receipt.get("model_stream")
                if isinstance(receipt.get("model_stream"), Mapping)
                else {}
            )
            active = (
                receipt.get("active_tool")
                if isinstance(receipt.get("active_tool"), Mapping)
                else {}
            )
            if plan.get("state_before") != "available" or plan.get("can_request_before") is not True:
                errors.append(f"{label}.plan was not requestable before Stop plan")
            if plan.get("state_after") != "terminal" or plan.get("can_request_after") is not False:
                errors.append(f"{label}.plan did not become terminal")
            expected_effect = (
                "prevent_future_steps" if name == "runtime_bound"
                else "prevent_future_steps_active_tool_continues"
            )
            if plan.get("effect_before") != expected_effect:
                errors.append(f"{label}.plan effect mismatch")
            if (
                stream.get("state") != "not_active"
                or stream.get("active") is not False
                or stream.get("handle_present") is not False
                or stream.get("can_request") is not False
            ):
                errors.append(f"{label}.model stream truth mismatch")
            handle_present = active.get("handle_present")
            can_request = active.get("can_request")
            if handle_present != report_case.get("handle_present"):
                errors.append(f"{label}.handle differs from report")
            if can_request is True and handle_present is not True:
                errors.append(f"{label}.direct control has no handle")
            if name == "runtime_bound" and (handle_present is not True or can_request is not True):
                errors.append(f"{label}.runtime capability lacks a bound handle")
            cleanup_ms = active.get("cleanup_ms")
            if handle_present is True:
                if (
                    not isinstance(cleanup_ms, (int, float))
                    or isinstance(cleanup_ms, bool)
                    or cleanup_ms < 0
                    or cleanup_ms > 5000
                ):
                    errors.append(f"{label}.cleanup_ms is not bounded")
            elif cleanup_ms is not None:
                errors.append(f"{label}.cleanup_ms exists without a handle")

            ui = observed_case.get("ui") if isinstance(observed_case.get("ui"), Mapping) else {}
            for field in (
                "shows_plan_scope",
                "shows_model_stream_scope",
                "shows_active_tool_scope",
                "shows_stop_plan",
                "warns_active_tool_continues",
                "polls_after_plan_cancel",
                "shows_final_tool_state",
                "normal_chat_unchanged",
            ):
                _require_true(errors, f"{label}.ui.{field}", ui.get(field))
            _require_false(errors, f"{label}.ui.shows_bare_stop", ui.get("shows_bare_stop"))
            expected_direct = handle_present is True and can_request is True
            if ui.get("shows_direct_tool_stop") != expected_direct:
                errors.append(f"{label}.ui direct-tool control mismatch")

            artifact = _artifact(
                root=root,
                platform=platform,
                case_name=name,
                metadata=report_case.get("artifact"),
                errors=errors,
            )
            details.append(
                {
                    "name": name,
                    "run_id_sha256": run_hash,
                    "tool": tool,
                    "semantics": expected_semantics,
                    "handle_present": handle_present,
                    "state_after": state_after,
                    "artifact": artifact,
                }
            )
        if len(run_hashes) != len(set(run_hashes)):
            errors.append(f"termination UI {platform} reuses a run identity")
        platform_details[platform] = {
            "device_name": report_platform.get("device_name"),
            "os_version": report_platform.get("os_version"),
            "cases": details,
        }

    valid_times = [value for value in timestamps if value is not None]
    if valid_times:
        first = min(valid_times)
        last = max(valid_times)
        span = (last - first).total_seconds() / 3600.0
        age = (now - last).total_seconds() / 3600.0
        if span > MAX_WINDOW_HOURS:
            errors.append(f"termination UI evidence spans {span:.1f}h; max is 12h")
        if age < -0.25:
            errors.append("termination UI evidence window is in the future")
        elif age > strict_age:
            errors.append(f"termination UI evidence is {age:.1f}h old; max is {strict_age:.1f}h")
    else:
        first = last = None
        span = age = None
        errors.append("termination UI evidence has no valid timestamps")

    return errors, {
        "generated_at": report.get("generated_at"),
        "candidate": dict(report.get("candidate") or {}),
        "capability_inventory_sha256": expected_inventory_hash,
        "required_cases": list(required_cases),
        "runtime_handle_coverage": expected_runtime_coverage,
        "observations": {
            "path": (
                str(observations_file.relative_to(root.resolve()))
                if observations_file is not None
                else None
            ),
            "sha256": _sha(observations_raw) if observations_raw else None,
            "bytes": len(observations_raw),
        },
        "window_started_at": first.isoformat().replace("+00:00", "Z") if first else None,
        "window_finished_at": last.isoformat().replace("+00:00", "Z") if last else None,
        "window_hours": round(span, 3) if span is not None else None,
        "age_hours": round(age, 3) if age is not None else None,
        "platforms": platform_details,
        "production_activation": False,
    }


def validate_path(
    *,
    root: Path,
    path: Path,
    candidate: Mapping[str, Any],
    now: datetime,
    max_age_hours: float,
) -> tuple[dict[str, Any], bytes, Path, list[str]]:
    report, raw, resolved = _load_json(root, path)
    errors, summary = validate_report(
        root=root,
        report=report,
        candidate=candidate,
        now=now,
        max_age_hours=max_age_hours,
    )
    return summary, raw, resolved, errors


def campaign_evidence(
    *,
    root: Path,
    path: Path,
    candidate: Mapping[str, Any],
    now: datetime,
    max_age_hours: float,
) -> dict[str, Any]:
    try:
        summary, raw, resolved, errors = validate_path(
            root=root,
            path=path,
            candidate=candidate,
            now=now,
            max_age_hours=max_age_hours,
        )
    except FileNotFoundError:
        return {
            "name": "termination_ui",
            "path": str(path),
            "present": False,
            "sha256": None,
            "bytes": 0,
            "status": "missing",
            "errors": ["evidence file is missing"],
            "summary": {},
        }
    except Exception as exc:
        return {
            "name": "termination_ui",
            "path": str(path),
            "present": True,
            "sha256": None,
            "bytes": None,
            "status": "fail",
            "errors": [f"{type(exc).__name__}: {str(exc)[:300]}"],
            "summary": {},
        }
    return {
        "name": "termination_ui",
        "path": str(resolved.relative_to(root.resolve())),
        "present": True,
        "sha256": _sha(raw),
        "bytes": len(raw),
        "status": "pass" if not errors else "fail",
        "errors": errors,
        "summary": summary,
    }
