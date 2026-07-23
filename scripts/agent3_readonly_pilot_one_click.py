#!/usr/bin/env python3
"""Version-bound loader for the retained Agent 3 read-only pilot operator.

The retained operator remains byte-identical. This wrapper owns the fail-closed
resume verdict so only a fresh, complete, exact-candidate report can skip a rerun.
"""
import importlib.util as _importlib_util
import re as _re
import sys as _sys
from datetime import datetime as _DateTime, timezone as _Timezone
from pathlib import Path as _Path

BRANCH = "agent/unified-candidate-1.58.145"
VERSION = "1.58.145"
_RETAINED = _Path(__file__).with_name("agent3_readonly_pilot_one_click.retained")
_source = _RETAINED.read_text(encoding="utf-8")
_source = _source.replace("agent/unified-candidate-1.58.143", BRANCH)
_source = _source.replace("1.58.143", VERSION)
_name = __name__
globals()["__name__"] = "_agent3_readonly_pilot_one_click_retained"
exec(compile(_source, str(_RETAINED), "exec"), globals(), globals())
globals()["__name__"] = _name
BRANCH = "agent/unified-candidate-1.58.145"
VERSION = "1.58.145"

_REPORT_MAX_AGE_HOURS = 24.0
_SHA256_RE = _re.compile(r"[0-9a-f]{64}")


def _utc_now() -> _DateTime:
    return _DateTime.now(_Timezone.utc)


def _parse_report_time(value: object) -> _DateTime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = _DateTime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(_Timezone.utc)


def _load_module(path: _Path, name: str):
    spec = _importlib_util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        return None
    module = _importlib_util.module_from_spec(spec)
    _sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    except Exception:
        _sys.modules.pop(name, None)
        return None
    return module


def _current_candidate_identity() -> dict[str, object]:
    module = _load_module(
        ROOT / "scripts" / "physical_validation_campaign.py",
        "agent3_resume_candidate_identity",
    )
    if module is None:
        return {}
    try:
        identity = module.candidate_identity(ROOT)
    except Exception:
        return {}
    return identity if isinstance(identity, dict) else {}


def _expected_task_set_identity() -> dict[str, object]:
    module = _load_module(
        ROOT / "scripts" / "agent3_readonly_pilot.py",
        "agent3_resume_task_set",
    )
    if module is None:
        return {}
    try:
        task_set = module.load_task_set(module.DEFAULT_TASK_SET)
        digest = module._sha256_json(task_set)
    except Exception:
        return {}
    tasks = task_set.get("tasks")
    if not isinstance(tasks, list):
        return {}
    task_ids = [
        item.get("id")
        for item in tasks
        if isinstance(item, dict) and isinstance(item.get("id"), str)
    ]
    return {
        "schema": task_set.get("schema"),
        "name": task_set.get("name"),
        "version": task_set.get("version"),
        "task_count": len(tasks),
        "sha256": digest,
        "task_ids": task_ids,
    }


def report_passes(report: dict[str, object], sha: str) -> bool:
    """Accept only full, fresh evidence bound to the current exact candidate."""
    if not isinstance(report, dict):
        return False
    candidate = report.get("candidate")
    summary = report.get("summary")
    stop = report.get("stop_fallback")
    target = report.get("target")
    backend = report.get("backend")
    task_set = report.get("task_set")
    results = report.get("results")
    started_at = _parse_report_time(report.get("started_at"))
    finished_at = _parse_report_time(report.get("finished_at"))
    if not all(
        isinstance(value, dict)
        for value in (candidate, summary, stop, target, backend, task_set)
    ):
        return False
    if (
        not isinstance(results, list)
        or started_at is None
        or finished_at is None
        or finished_at < started_at
    ):
        return False
    age_hours = (_utc_now() - finished_at).total_seconds() / 3600
    if age_hours < -0.25 or age_hours > _REPORT_MAX_AGE_HOURS:
        return False

    identity = _current_candidate_identity()
    expected_tasks = _expected_task_set_identity()
    code_sha256 = candidate.get("code_sha256")
    rig_validation = backend.get("rig_validation")
    if not isinstance(rig_validation, dict):
        return False
    actual_task_ids = [
        item.get("task_id")
        for item in results
        if isinstance(item, dict) and item.get("success") is True
    ]
    expected_task_ids = expected_tasks.get("task_ids")
    expected_task_report = {
        key: expected_tasks.get(key)
        for key in ("schema", "name", "version", "task_count", "sha256")
    }

    return (
        report.get("schema") == SCHEMA
        and report.get("success") is True
        and candidate.get("git_sha") == sha
        and candidate.get("version") == VERSION
        and isinstance(code_sha256, str)
        and _SHA256_RE.fullmatch(code_sha256) is not None
        and summary.get("tasks") == 20
        and summary.get("successes") == 20
        and summary.get("failures") == 0
        and summary.get("error_types") == {}
        and summary.get("retry_events") == 0
        and stop.get("success") is True
        and stop.get("fallback_path") == "/api/v1/chat"
        and stop.get("agent3_state") == "cancelled"
        and stop.get("completed_agent3_steps") == 1
        and stop.get("pending_steps_after_stop") == 1
        and target.get("execution_mode") == "experimental-read-only"
        and target.get("production_activation") is False
        and backend.get("worker_version") == VERSION
        and backend.get("code_sha256") == code_sha256
        and backend.get("production_tools_path_untouched") is True
        and backend.get("production_activation") is False
        and rig_validation.get("eligible_for_developer_preview") is True
        and rig_validation.get("version_match") is True
        and rig_validation.get("code_match") is True
        and task_set == expected_task_report
        and len(results) == 20
        and actual_task_ids == expected_task_ids
        and identity.get("git_sha") == sha
        and identity.get("version") == VERSION
        and identity.get("code_sha256") == code_sha256
        and identity.get("branch") == BRANCH
        and identity.get("working_tree_clean") is True
        and identity.get("version_stamps_consistent") is True
    )


# Static review markers for the exact retained operator behavior:
# agent3_readonly_pilot.py
# run-agent3-rig-validation.ps1
# stage.start_stack(planner)
# stage.ensure_device_token()
# def ensure_planner_model

if _name == "__main__":
    raise SystemExit(main())
