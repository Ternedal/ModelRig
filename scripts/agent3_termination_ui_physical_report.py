#!/usr/bin/env python3
"""Prepare and verify candidate-bound physical T-023 termination UI evidence.

The tool never sends an HTTP request and never executes or cancels a tool. It
binds an observation sheet to the exact candidate and registry termination
inventory, then verifies Android/Windows observations and their local artifacts.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from agent3_write_pilot_common import (  # noqa: E402
    PilotEvidenceError,
    _atomic_json,
    _load_json,
    _parse_time,
    _sha_bytes,
    _utc_now,
    candidate_identity,
)

OBSERVATIONS_SCHEMA = "kaliv-agent3-termination-ui-observations/v1"
REPORT_SCHEMA = "kaliv-agent3-termination-ui-physical/v1"
PLATFORMS = ("android", "windows")
BASE_CASES = ("non_interruptible", "cooperative_declaration", "late_completion")
MAX_AGE_HOURS = 24.0
MAX_WINDOW_HOURS = 12.0
MAX_ARTIFACT_BYTES = 32 * 1024 * 1024
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
TERMINAL_TOOL_STATES = {"succeeded", "failed", "cancelled", "completed_after_cancel"}


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def capability_inventory(root: Path = ROOT) -> dict[str, list[str]]:
    """Read termination modes from the strict capability registry in a subprocess."""
    tmp = tempfile.mkdtemp(prefix="kaliv-t023-inventory-")
    env = dict(os.environ)
    env.update(
        {
            "KALIV_AUDIT_DB": str(Path(tmp) / "audit.db"),
            "KALIV_TOOLS_STATE": str(Path(tmp) / "tools.json"),
            "KALIV_JOBS_DB": str(Path(tmp) / "jobs.db"),
            "KALIV_TOOLS_DIR": tmp,
            "PYTHONPATH": str(root / "worker"),
            "PYTHONDONTWRITEBYTECODE": "1",
        }
    )
    code = (
        "import json\n"
        "from app.capability_schema import descriptors_from_registry\n"
        "from app.tools import REGISTRY\n"
        "out = {'none': [], 'cooperative': [], 'runtime': []}\n"
        "for d in descriptors_from_registry(REGISTRY):\n"
        "    mode = d.termination.mode.value\n"
        "    out.setdefault(mode, []).append(d.capability_id)\n"
        "print(json.dumps({k: sorted(v) for k, v in out.items()}, sort_keys=True))\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=root / "worker",
        env=env,
        text=True,
        capture_output=True,
        timeout=60,
        check=False,
    )
    if result.returncode != 0:
        raise PilotEvidenceError(
            "termination capability inventory cannot be read: "
            + (result.stderr or result.stdout)[-500:]
        )
    try:
        value = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise PilotEvidenceError("termination capability inventory is invalid JSON") from exc
    if not isinstance(value, dict):
        raise PilotEvidenceError("termination capability inventory is not an object")
    inventory: dict[str, list[str]] = {}
    for mode in ("none", "cooperative", "runtime"):
        tools = value.get(mode)
        if not isinstance(tools, list) or any(
            not isinstance(item, str) or not item for item in tools
        ):
            raise PilotEvidenceError(f"termination inventory mode {mode} is invalid")
        inventory[mode] = sorted(tools)
    return inventory


def inventory_sha256(inventory: dict[str, list[str]]) -> str:
    return _sha_bytes(_canonical(inventory))


def _required_cases(inventory: dict[str, list[str]]) -> tuple[str, ...]:
    return BASE_CASES + (("runtime_bound",) if inventory.get("runtime") else ())


def prepare_observations(
    *,
    operator: str,
    identity: dict[str, Any],
    inventory: dict[str, list[str]],
    now: datetime | None = None,
) -> dict[str, Any]:
    if not operator.strip():
        raise PilotEvidenceError("operator is required")
    observed = _iso(now or _utc_now())
    cases = _required_cases(inventory)

    def empty_case(name: str, platform: str) -> dict[str, Any]:
        semantics = {
            "non_interruptible": "none",
            "cooperative_declaration": "cooperative",
            "late_completion": "none",
            "runtime_bound": "runtime",
        }[name]
        return {
            "name": name,
            "surface": (
                "developer_agent3"
                if name in {"cooperative_declaration", "runtime_bound"}
                else "normal_task"
            ),
            "observed_at": observed,
            "run_id_sha256": "",
            "receipt": {
                "plan": {
                    "state_before": "",
                    "can_request_before": False,
                    "effect_before": "",
                    "state_after": "",
                    "can_request_after": False,
                },
                "model_stream": {
                    "state": "",
                    "active": False,
                    "handle_present": False,
                    "can_request": False,
                },
                "active_tool": {
                    "tool": "",
                    "semantics": semantics,
                    "handle_present": False,
                    "can_request": False,
                    "request_state_before": "",
                    "state_before": "",
                    "request_state_after": "",
                    "state_after": "",
                    "cleanup_ms": None,
                    "reason": "",
                },
            },
            "ui": {
                "shows_plan_scope": False,
                "shows_model_stream_scope": False,
                "shows_active_tool_scope": False,
                "shows_stop_plan": False,
                "shows_bare_stop": False,
                "shows_direct_tool_stop": False,
                "warns_active_tool_continues": False,
                "polls_after_plan_cancel": False,
                "shows_final_tool_state": False,
                "normal_chat_unchanged": False,
            },
            "artifact_path": (
                f"validation/agent3-termination-ui-evidence/{platform}/"
                f"{name}.json"
            ),
            "artifact_sha256": "",
        }

    return {
        "schema": OBSERVATIONS_SCHEMA,
        "prepared_at": observed,
        "operator": operator.strip(),
        "candidate": {
            key: identity.get(key)
            for key in ("version", "git_sha", "code_sha256", "identity_source")
        },
        "capability_inventory_sha256": inventory_sha256(inventory),
        "platforms": {
            platform: {
                "device_name": "",
                "os_version": "",
                "app_surface": "Kaliv Opgaver",
                "cases": [empty_case(name, platform) for name in cases],
            }
            for platform in PLATFORMS
        },
        "production_activation": False,
    }


def _expect(errors: list[str], label: str, actual: Any, expected: Any) -> None:
    if actual != expected:
        errors.append(f"{label} mismatch: expected {expected!r}, got {actual!r}")


def _require_true(errors: list[str], label: str, value: Any) -> None:
    if value is not True:
        errors.append(f"{label} must be true")


def _require_false(errors: list[str], label: str, value: Any) -> None:
    if value is not False:
        errors.append(f"{label} must be false")


def _artifact(
    *,
    root: Path,
    platform: str,
    case_name: str,
    path_value: Any,
    digest_value: Any,
    errors: list[str],
) -> dict[str, Any] | None:
    label = f"{platform}.{case_name}.artifact"
    if not isinstance(path_value, str) or not path_value:
        errors.append(f"{label}_path is missing")
        return None
    relative = Path(path_value)
    if relative.is_absolute() or ".." in relative.parts:
        errors.append(f"{label}_path escapes the repository")
        return None
    required_prefix = ("validation", "agent3-termination-ui-evidence", platform)
    if relative.parts[:3] != required_prefix:
        errors.append(
            f"{label}_path must be under "
            f"validation/agent3-termination-ui-evidence/{platform}"
        )
        return None
    path = root / relative
    if path.is_symlink() or not path.is_file():
        errors.append(f"{label} is missing or not a regular file")
        return None
    size = path.stat().st_size
    if size <= 0 or size > MAX_ARTIFACT_BYTES:
        errors.append(f"{label} size is invalid: {size}")
        return None
    raw = path.read_bytes()
    actual = _sha_bytes(raw)
    if not isinstance(digest_value, str) or not _SHA256.fullmatch(digest_value):
        errors.append(f"{label}_sha256 is invalid")
    elif digest_value != actual:
        errors.append(f"{label}_sha256 does not match the artifact")
    return {"path": str(relative), "sha256": actual, "bytes": size}


def _validate_case(
    *,
    case: dict[str, Any],
    platform: str,
    inventory: dict[str, list[str]],
    root: Path,
    errors: list[str],
) -> tuple[dict[str, Any], datetime | None]:
    name = case.get("name")
    label = f"{platform}.{name}"
    surface = case.get("surface")
    expected_surface = (
        "developer_agent3"
        if name in {"cooperative_declaration", "runtime_bound"}
        else "normal_task"
    )
    _expect(errors, f"{label}.surface", surface, expected_surface)
    observed_at = _parse_time(case.get("observed_at"))
    if observed_at is None:
        errors.append(f"{label}.observed_at is invalid")
    run_hash = case.get("run_id_sha256")
    if not isinstance(run_hash, str) or not _SHA256.fullmatch(run_hash):
        errors.append(f"{label}.run_id_sha256 is invalid")

    receipt = case.get("receipt")
    if not isinstance(receipt, dict):
        errors.append(f"{label}.receipt is missing")
        receipt = {}
    plan = receipt.get("plan") if isinstance(receipt.get("plan"), dict) else {}
    stream = (
        receipt.get("model_stream")
        if isinstance(receipt.get("model_stream"), dict)
        else {}
    )
    active = (
        receipt.get("active_tool")
        if isinstance(receipt.get("active_tool"), dict)
        else {}
    )
    ui = case.get("ui") if isinstance(case.get("ui"), dict) else {}

    _expect(errors, f"{label}.plan.state_before", plan.get("state_before"), "available")
    _require_true(errors, f"{label}.plan.can_request_before", plan.get("can_request_before"))
    _expect(errors, f"{label}.plan.state_after", plan.get("state_after"), "terminal")
    _require_false(errors, f"{label}.plan.can_request_after", plan.get("can_request_after"))

    active_continues = name in {
        "non_interruptible",
        "cooperative_declaration",
        "late_completion",
    }
    expected_effect = (
        "prevent_future_steps_active_tool_continues"
        if active_continues
        else "prevent_future_steps"
    )
    _expect(errors, f"{label}.plan.effect_before", plan.get("effect_before"), expected_effect)

    _expect(errors, f"{label}.model_stream.state", stream.get("state"), "not_active")
    for field in ("active", "handle_present", "can_request"):
        _require_false(errors, f"{label}.model_stream.{field}", stream.get(field))

    semantics = {
        "non_interruptible": "none",
        "cooperative_declaration": "cooperative",
        "late_completion": "none",
        "runtime_bound": "runtime",
    }.get(str(name))
    _expect(errors, f"{label}.active_tool.semantics", active.get("semantics"), semantics)
    _expect(errors, f"{label}.active_tool.state_before", active.get("state_before"), "executing")
    if not isinstance(active.get("reason"), str) or not active.get("reason", "").strip():
        errors.append(f"{label}.active_tool.reason is missing")
    tool = active.get("tool")
    mode_tools = inventory.get(str(semantics), [])
    if not isinstance(tool, str) or tool not in mode_tools:
        errors.append(
            f"{label}.active_tool.tool is not a {semantics!r} capability in the candidate"
        )

    if name in {"non_interruptible", "late_completion"}:
        _require_false(errors, f"{label}.active_tool.handle_present", active.get("handle_present"))
        _require_false(errors, f"{label}.active_tool.can_request", active.get("can_request"))
        _expect(
            errors,
            f"{label}.active_tool.request_state_before",
            active.get("request_state_before"),
            "unavailable",
        )
    elif name == "cooperative_declaration":
        handle = active.get("handle_present")
        can_request = active.get("can_request")
        if handle is True:
            _require_true(errors, f"{label}.active_tool.can_request", can_request)
            if active.get("request_state_before") not in {"available", "pending"}:
                errors.append(
                    f"{label}.active_tool.request_state_before must be available/pending with a handle"
                )
        else:
            _require_false(errors, f"{label}.active_tool.handle_present", handle)
            _require_false(errors, f"{label}.active_tool.can_request", can_request)
            _expect(
                errors,
                f"{label}.active_tool.request_state_before",
                active.get("request_state_before"),
                "unavailable",
            )
    elif name == "runtime_bound":
        _require_true(errors, f"{label}.active_tool.handle_present", active.get("handle_present"))
        _require_true(errors, f"{label}.active_tool.can_request", active.get("can_request"))
        if active.get("request_state_before") not in {"available", "pending"}:
            errors.append(
                f"{label}.active_tool.request_state_before must be available/pending"
            )

    state_after = active.get("state_after")
    request_after = active.get("request_state_after")
    if name == "late_completion":
        _expect(
            errors,
            f"{label}.active_tool.state_after",
            state_after,
            "completed_after_cancel",
        )
    elif state_after not in TERMINAL_TOOL_STATES:
        errors.append(f"{label}.active_tool.state_after is not terminal")
    _expect(
        errors,
        f"{label}.active_tool.request_state_after",
        request_after,
        "terminal",
    )

    cleanup_ms = active.get("cleanup_ms")
    if active.get("handle_present") is True:
        if (
            not isinstance(cleanup_ms, (int, float))
            or isinstance(cleanup_ms, bool)
            or cleanup_ms < 0
            or cleanup_ms > 5000
        ):
            errors.append(f"{label}.active_tool.cleanup_ms must be within 0..5000")
    elif cleanup_ms is not None:
        errors.append(f"{label}.active_tool.cleanup_ms must be null without a handle")

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
    expected_direct = name == "runtime_bound" or (
        name == "cooperative_declaration" and active.get("handle_present") is True
    )
    _expect(
        errors,
        f"{label}.ui.shows_direct_tool_stop",
        ui.get("shows_direct_tool_stop"),
        expected_direct,
    )

    artifact = _artifact(
        root=root,
        platform=platform,
        case_name=str(name),
        path_value=case.get("artifact_path"),
        digest_value=case.get("artifact_sha256"),
        errors=errors,
    )
    return {
        "name": name,
        "surface": surface,
        "run_id_sha256": run_hash,
        "tool": tool,
        "semantics": semantics,
        "handle_present": active.get("handle_present"),
        "state_after": state_after,
        "request_state_after": request_after,
        "artifact": artifact,
    }, observed_at


def judge(
    *,
    observations: dict[str, Any],
    identity: dict[str, Any],
    inventory: dict[str, list[str]],
    root: Path,
    now: datetime | None = None,
) -> tuple[list[str], dict[str, Any]]:
    errors: list[str] = []
    _expect(errors, "schema", observations.get("schema"), OBSERVATIONS_SCHEMA)
    _require_false(
        errors,
        "production_activation",
        observations.get("production_activation"),
    )
    if not isinstance(observations.get("operator"), str) or not observations["operator"].strip():
        errors.append("operator is missing")
    prepared = _parse_time(observations.get("prepared_at"))
    if prepared is None:
        errors.append("prepared_at is invalid")

    target = (
        observations.get("candidate")
        if isinstance(observations.get("candidate"), dict)
        else {}
    )
    for field in ("version", "git_sha", "code_sha256", "identity_source"):
        _expect(errors, f"candidate.{field}", target.get(field), identity.get(field))
    _expect(
        errors,
        "capability_inventory_sha256",
        observations.get("capability_inventory_sha256"),
        inventory_sha256(inventory),
    )

    platforms = (
        observations.get("platforms")
        if isinstance(observations.get("platforms"), dict)
        else {}
    )
    if set(platforms) != set(PLATFORMS):
        errors.append(
            f"platforms mismatch: expected {sorted(PLATFORMS)}, got {sorted(platforms)}"
        )

    required_cases = _required_cases(inventory)
    details: dict[str, Any] = {}
    times = [prepared] if prepared else []
    for platform in PLATFORMS:
        value = platforms.get(platform)
        if not isinstance(value, dict):
            errors.append(f"{platform} observations are missing")
            continue
        for field in ("device_name", "os_version"):
            if not isinstance(value.get(field), str) or not value[field].strip():
                errors.append(f"{platform}.{field} is missing")
        _expect(errors, f"{platform}.app_surface", value.get("app_surface"), "Kaliv Opgaver")
        cases = value.get("cases")
        if not isinstance(cases, list):
            errors.append(f"{platform}.cases is missing")
            continue
        by_name = {
            case.get("name"): case
            for case in cases
            if isinstance(case, dict) and isinstance(case.get("name"), str)
        }
        if set(by_name) != set(required_cases) or len(cases) != len(required_cases):
            errors.append(
                f"{platform}.cases mismatch: expected {list(required_cases)}, "
                f"got {sorted(by_name)}"
            )
        run_hashes: list[str] = []
        platform_details: list[dict[str, Any]] = []
        for name in required_cases:
            case = by_name.get(name)
            if not isinstance(case, dict):
                continue
            detail, observed = _validate_case(
                case=case,
                platform=platform,
                inventory=inventory,
                root=root,
                errors=errors,
            )
            platform_details.append(detail)
            if observed:
                times.append(observed)
            if isinstance(case.get("run_id_sha256"), str):
                run_hashes.append(case["run_id_sha256"])
        if len(run_hashes) != len(set(run_hashes)):
            errors.append(f"{platform} reuses a run_id_sha256 across physical cases")
        details[platform] = {
            "device_name": value.get("device_name"),
            "os_version": value.get("os_version"),
            "cases": platform_details,
        }

    current = now or _utc_now()
    valid_times = [value for value in times if value is not None]
    if valid_times:
        first = min(valid_times)
        last = max(valid_times)
        window_hours = (last - first).total_seconds() / 3600
        age_hours = (current - last).total_seconds() / 3600
        if window_hours > MAX_WINDOW_HOURS:
            errors.append(
                f"physical observation window is {window_hours:.1f}h; max is {MAX_WINDOW_HOURS:.1f}h"
            )
        if age_hours < -0.25:
            errors.append("physical observations are from the future")
        elif age_hours > MAX_AGE_HOURS:
            errors.append(
                f"physical observations are {age_hours:.1f}h old; max is {MAX_AGE_HOURS:.1f}h"
            )
    else:
        first = last = None
        window_hours = age_hours = None
        errors.append("physical observations have no valid timestamps")

    return errors, {
        "required_cases": list(required_cases),
        "runtime_capabilities": inventory.get("runtime", []),
        "runtime_handle_coverage": (
            "required" if inventory.get("runtime") else "not_applicable_no_runtime_capability"
        ),
        "window_started_at": _iso(first) if first else None,
        "window_finished_at": _iso(last) if last else None,
        "window_hours": round(window_hours, 3) if window_hours is not None else None,
        "age_hours": round(age_hours, 3) if age_hours is not None else None,
        "platforms": details,
        "production_activation": False,
    }


def verify_report(
    *,
    observations_path: Path,
    report_path: Path,
    root: Path = ROOT,
    now: datetime | None = None,
) -> dict[str, Any]:
    observations, raw = _load_json(observations_path)
    identity = candidate_identity(root)
    inventory = capability_inventory(root)
    errors, details = judge(
        observations=observations,
        identity=identity,
        inventory=inventory,
        root=root,
        now=now,
    )
    report = {
        "schema": REPORT_SCHEMA,
        "generated_at": _iso(now or _utc_now()),
        "success": not errors,
        "candidate": {
            key: identity.get(key)
            for key in ("version", "git_sha", "code_sha256", "identity_source")
        },
        "capability_inventory": inventory,
        "capability_inventory_sha256": inventory_sha256(inventory),
        "observations_path": str(observations_path),
        "observations_sha256": _sha_bytes(raw),
        "summary": details,
        "errors": errors,
        "production_activation": False,
    }
    _atomic_json(report_path, report)
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    prepare = sub.add_parser("prepare")
    prepare.add_argument("--operator", required=True)
    prepare.add_argument(
        "--observations",
        type=Path,
        default=Path("validation/agent3-termination-ui-observations.json"),
    )

    verify = sub.add_parser("verify")
    verify.add_argument(
        "--observations",
        type=Path,
        default=Path("validation/agent3-termination-ui-observations.json"),
    )
    verify.add_argument(
        "--report",
        type=Path,
        default=Path("validation/agent3-termination-ui-physical-latest.json"),
    )

    args = parser.parse_args(argv)
    try:
        if args.command == "prepare":
            identity = candidate_identity(ROOT)
            inventory = capability_inventory(ROOT)
            value = prepare_observations(
                operator=args.operator,
                identity=identity,
                inventory=inventory,
            )
            _atomic_json(args.observations, value)
            print(f"prepared pending observations: {args.observations}")
            return 0
        report = verify_report(
            observations_path=args.observations,
            report_path=args.report,
        )
        print(
            f"termination UI physical report: "
            f"{'PASS' if report['success'] else 'FAIL'} -> {args.report}"
        )
        for error in report["errors"]:
            print(f"  - {error}")
        return 0 if report["success"] else 2
    except (OSError, PilotEvidenceError, subprocess.TimeoutExpired) as exc:
        print(f"termination UI physical evidence error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
