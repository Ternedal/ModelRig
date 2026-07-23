#!/usr/bin/env python3
"""Regression checks for scripts/agent3_model_eval.py."""
from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "agent3_model_eval.py"
SPEC = importlib.util.spec_from_file_location("agent3_model_eval", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class FakeClient:
    def __init__(self, plans: list[dict[str, Any]]):
        self.plans = list(plans)
        self.calls: list[tuple[str, str, dict[str, Any] | None]] = []

    def request(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self.calls.append((method, path, payload))
        if path.endswith("/status"):
            return {
                "enabled": True,
                "experimental": True,
                "code_sha256": "a" * 64,
                "version": "test",
            }
        assert path == "/api/v1/experimental/agent3/plan", path
        assert self.plans, "fake plan queue exhausted"
        return self.plans.pop(0)


def _one_task() -> dict[str, Any]:
    return {
        "schema": MODULE.TASK_SET_SCHEMA,
        "name": "test",
        "version": "1",
        "tasks": [
            {
                "id": "01-rig_status",
                "prompt": "Vis status",
                "category": "read/rig-status",
                "expected": {
                    "steps": [{"tool": "rig_status", "risk": "read", "args": {}}],
                    "max_steps": 1,
                    "forbidden_tools": ["note_append"],
                },
            }
        ],
    }


def test_frozen_task_set_has_30_unique_cases_and_all_current_tools() -> None:
    task_set = MODULE.load_task_set(ROOT / "eval" / "agent3_model_tasks.json")
    tasks = task_set["tasks"]
    assert len(tasks) == 30
    assert len({task["id"] for task in tasks}) == 30
    tools = {
        step["tool"]
        for task in tasks
        for step in task["expected"]["steps"]
    }
    assert tools == {
        "rig_status",
        "list_models",
        "current_datetime",
        "job_status",
        "cancel_job",
        "list_documents",
        "delete_model",
        "pull_model",
        "note_append",
    }
    assert all(task["expected"]["max_steps"] == 1 for task in tasks)


def test_compare_plan_requires_exact_tool_risk_args_and_budget() -> None:
    task = _one_task()["tasks"][0]
    exact = MODULE.compare_plan(
        task,
        {"plan": [{"tool": "rig_status", "risk": "read", "args": {}}]},
    )
    assert exact["exact_match"] is True
    assert exact["discipline_pass"] is True

    wrong_args = MODULE.compare_plan(
        task,
        {"plan": [{"tool": "rig_status", "risk": "read", "args": {"x": 1}}]},
    )
    assert wrong_args["exact_match"] is False
    assert wrong_args["tool_score"] == 1.0
    assert wrong_args["args_score"] == 0.0

    extra_write = MODULE.compare_plan(
        task,
        {
            "plan": [
                {"tool": "rig_status", "risk": "read", "args": {}},
                {"tool": "note_append", "risk": "write", "args": {"text": "x"}},
            ]
        },
    )
    assert extra_write["exact_match"] is False
    assert extra_write["discipline_pass"] is False
    assert any("step budget exceeded" in value for value in extra_write["findings"])
    assert any("forbidden tools" in value for value in extra_write["findings"])


def test_run_eval_is_plan_only_and_never_starts_or_confirms() -> None:
    client = FakeClient(
        [
            {
                "plan_id": "preview-only",
                "plan": [{"tool": "rig_status", "risk": "read", "args": {}}],
            }
        ]
    )
    report = MODULE.run_eval(client, _one_task(), planner_model="qwen3:14b")
    assert report["target"]["execution_mode"] == "plan-only"
    assert report["target"]["starts_plans"] is False
    assert report["target"]["executes_tools"] is False
    assert report["summary"]["exact_match_rate"] == 1.0
    assert [path for _, path, _ in client.calls] == [
        "/api/v1/experimental/agent3/status",
        "/api/v1/experimental/agent3/plan",
    ]
    payload = client.calls[1][2]
    assert payload is not None
    assert payload["rag"] is False
    assert payload["cloud_ready"] is False
    assert payload["proactive"] is False
    assert payload["use_memory"] is False
    assert payload["planner_model"] == "qwen3:14b"


def test_summary_counts_request_errors_against_the_gate() -> None:
    good = {
        "category": "read",
        "latency_ms": 10.0,
        "request_error": None,
        "evaluation": {"exact_match": True, "discipline_pass": True},
    }
    bad = {
        "category": "write",
        "latency_ms": 20.0,
        "request_error": "offline",
        "evaluation": {"exact_match": False, "discipline_pass": False},
    }
    summary = MODULE.summarize([good, bad])
    assert summary["tasks"] == 2
    assert summary["requests_completed"] == 1
    assert summary["request_errors"] == 1
    assert summary["exact_match_rate"] == 0.5
    assert summary["latency_ms"]["p50"] == 10.0
    assert summary["latency_ms"]["p95"] == 10.0


def test_atomic_report_writer_emits_valid_json() -> None:
    with tempfile.TemporaryDirectory() as temp:
        path = Path(temp) / "nested" / "report.json"
        MODULE._write_json_atomic(path, {"schema": MODULE.SCHEMA, "ok": True})
        assert json.loads(path.read_text(encoding="utf-8")) == {
            "schema": MODULE.SCHEMA,
            "ok": True,
        }
        assert not list(path.parent.glob("*.tmp"))


def test_stage_a_overrides_match_current_risk_contract() -> None:
    wrapper_path = ROOT / "scripts" / "stage_a_agent3_model_eval.py"
    spec = importlib.util.spec_from_file_location("stage_a_agent3_model_eval_test", wrapper_path)
    assert spec is not None and spec.loader is not None
    wrapper = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(wrapper)

    task_set = wrapper.load_stage_a_task_set(ROOT / "eval" / "agent3_model_tasks.json")
    assert task_set["version"] == "2026-07-23.1"
    tasks = {task["id"]: task for task in task_set["tasks"]}

    assert tasks["20-note_append"]["expected"]["steps"] == [
        {"tool": "note_append", "risk": "write", "args": {"text": "Test af lokal planner 20."}}
    ]
    for task_id in ("24-pull_model", "25-pull_model", "26-pull_model"):
        assert tasks[task_id]["expected"]["steps"][0]["risk"] == "admin"
    for task_id in ("27-delete_model", "28-delete_model", "29-delete_model", "30-delete_model"):
        assert tasks[task_id]["expected"]["steps"][0]["risk"] == "destructive"


def test_stage_a_loader_uses_overlay_and_keeps_checkout_clean() -> None:
    source = (ROOT / "scripts" / "stage_a_one_click.py").read_text(encoding="utf-8")
    assert "stage_a_agent3_model_eval.py" in source
    assert "-SkipReadinessRegeneration" in source
    assert "refusing an ambiguous replacement" in source


def test_deep_health_timeout_handles_a_cold_timeout_without_crashing() -> None:
    path = ROOT / "scripts" / "rig_preflight_substrate.py"
    spec = importlib.util.spec_from_file_location("rig_preflight_substrate_test", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.DEEP_HEALTH_TIMEOUT_SECONDS >= 60.0

    class Check:
        def __init__(self, name: str):
            self.name = name

        def ok(self, detail: str):
            return {"status": "ok", "detail": detail}

        def warn(self, detail: str, advice: str):
            return {"status": "warn", "detail": detail, "advice": advice}

        def fail(self, detail: str, advice: str):
            return {"status": "fail", "detail": detail, "advice": advice}

    def timeout_get(_url: str, *, token: str, timeout: float):
        assert token == "token"
        assert timeout == module.DEEP_HEALTH_TIMEOUT_SECONDS
        raise TimeoutError("timed out")

    checks = module.check_substrate(timeout_get, Check, "http://127.0.0.1:8080", "token", "qwen3:14b")
    assert checks[0]["status"] == "fail"
    assert "timed out" in checks[0]["detail"]


TESTS = [value for name, value in sorted(globals().items()) if name.startswith("test_")]
if __name__ == "__main__":
    for test in TESTS:
        test()
    print(f"agent3 model eval: {len(TESTS)} passed")
