#!/usr/bin/env python3
"""Stage A entrypoint for the frozen Agent 3 model-eval task set.

The base task set predates the finer Agent 3 risk vocabulary. Physical validation
must compare against the current security contract without weakening the normal
standalone evaluator or rewriting the frozen source file in place. This wrapper
applies a small, version-bound and fail-closed override set, then delegates to the
normal evaluator.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import agent3_model_eval as _base

ROOT = Path(__file__).resolve().parents[1]
OVERRIDES = ROOT / "eval" / "agent3_model_tasks_stage_a_overrides.json"
ORIGINAL_LOAD = _base.load_task_set
ORIGINAL_CLIENT_REQUEST = _base.Client.request


def _require_object(value: Any, *, where: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise _base.EvalError(f"{where} must be an object")
    return value


def _load_overrides() -> dict[str, Any]:
    try:
        raw = json.loads(OVERRIDES.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise _base.EvalError(f"Stage A override file is missing: {OVERRIDES}") from exc
    except json.JSONDecodeError as exc:
        raise _base.EvalError(f"Stage A override file is invalid JSON: {exc}") from exc
    raw = _require_object(raw, where="override root")
    if raw.get("schema") != "kaliv-agent3-model-eval-overrides/v1":
        raise _base.EvalError("Stage A override file uses an unsupported schema")
    return raw


def load_stage_a_task_set(path: Path) -> dict[str, Any]:
    task_set = ORIGINAL_LOAD(path)
    if path.resolve() != _base.DEFAULT_TASK_SET.resolve():
        return task_set

    overrides = _load_overrides()
    base = _require_object(overrides.get("base_task_set"), where="base_task_set")
    if task_set.get("name") != base.get("name") or task_set.get("version") != base.get("version"):
        raise _base.EvalError(
            "Stage A overrides do not match the frozen base task set; review instead of guessing"
        )

    indexed = {task["id"]: task for task in task_set["tasks"]}
    records = overrides.get("overrides")
    if not isinstance(records, list) or not records:
        raise _base.EvalError("Stage A override file contains no overrides")

    seen: set[str] = set()
    for index, record_raw in enumerate(records):
        record = _require_object(record_raw, where=f"overrides[{index}]")
        task_id = record.get("id")
        if not isinstance(task_id, str) or not task_id or task_id in seen:
            raise _base.EvalError(f"overrides[{index}] has an invalid or duplicate id")
        seen.add(task_id)
        task = indexed.get(task_id)
        if task is None:
            raise _base.EvalError(f"Stage A override references unknown task {task_id!r}")

        old_step = _require_object(record.get("from"), where=f"overrides[{index}].from")
        new_step = _require_object(record.get("to"), where=f"overrides[{index}].to")
        current = task["expected"]["steps"]
        if current != [old_step]:
            raise _base.EvalError(
                f"Stage A override precondition drifted for {task_id!r}; review the task set"
            )
        task["expected"]["steps"] = [new_step]

    version = overrides.get("override_version")
    if not isinstance(version, str) or not version:
        raise _base.EvalError("Stage A override_version is missing")
    task_set["version"] = version
    return task_set


def normalize_stage_a_status(response: dict[str, Any]) -> dict[str, Any]:
    """Expose the worker's version under the evaluator's legacy version field."""
    version = response.get("version")
    if isinstance(version, str) and version.strip():
        return response

    worker_version = response.get("worker_version")
    if not isinstance(worker_version, str) or not worker_version.strip():
        raise _base.EvalError(
            "Agent 3 status is missing both version and worker_version; refusing unbound evidence"
        )

    normalized = dict(response)
    normalized["version"] = worker_version.strip()
    return normalized


def stage_a_client_request(
    self: _base.Client,
    method: str,
    path: str,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    response = ORIGINAL_CLIENT_REQUEST(self, method, path, payload)
    if path == "/api/v1/experimental/agent3/status":
        return normalize_stage_a_status(response)
    return response


_base.load_task_set = load_stage_a_task_set
_base.Client.request = stage_a_client_request

if __name__ == "__main__":
    raise SystemExit(_base.main())
