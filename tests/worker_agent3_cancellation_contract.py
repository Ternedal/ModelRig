from __future__ import annotations

import dataclasses
import os
import tempfile

_tmp = tempfile.mkdtemp(prefix="kaliv-cancel-contract-")
os.environ.setdefault("KALIV_AUDIT_DB", os.path.join(_tmp, "audit.db"))
os.environ.setdefault("KALIV_TOOLS_STATE", os.path.join(_tmp, "tools.json"))
os.environ.setdefault("KALIV_JOBS_DB", os.path.join(_tmp, "jobs.db"))
os.environ.setdefault("KALIV_TOOLS_DIR", _tmp)

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import tools
from app.agent3.cancellation_status import (
    SCHEMA,
    install_termination_contract,
    termination_view,
)
from app.agent3.core import (
    AgentRun,
    AgentStep,
    RiskClass,
    RouteKind,
    RoutePlan,
    RunState,
    StepState,
    TurnRequest,
)


def route() -> RoutePlan:
    return RoutePlan(RouteKind.RIG_TOOLS_LOCAL, "test", False, True, True, False)


def run_with(step: AgentStep, state: RunState = RunState.RUNNING) -> AgentRun:
    return AgentRun(TurnRequest("test", tools=True), route(), [step], state=state)


def test_executing_none_tool_exposes_plan_only_stop() -> None:
    step = AgentStep(
        "note_append",
        {"text": "x"},
        RiskClass.WRITE,
        state=StepState.EXECUTING,
    )
    view = termination_view(run_with(step))
    assert view["schema"] == SCHEMA
    assert view["production_activation"] is False
    assert view["plan"]["can_request"] is True
    assert view["plan"]["effect"] == "prevent_future_steps_active_tool_continues"
    assert view["model_stream"]["can_request"] is False
    assert view["active_tool"]["semantics"] == "none"
    assert view["active_tool"]["can_request"] is False
    assert view["active_tool"]["handle_present"] is False


def test_cooperative_declaration_is_not_a_handle() -> None:
    step = AgentStep(
        "pull_model",
        {"name": "qwen3:8b"},
        RiskClass.ADMIN,
        state=StepState.EXECUTING,
    )
    active = termination_view(run_with(step))["active_tool"]
    assert tools.REGISTRY["pull_model"].cancellation == "cooperative"
    assert active["semantics"] == "cooperative"
    assert active["can_request"] is False
    assert active["reason"] == "declared_semantics_but_runtime_handle_not_bound"


def test_unknown_tool_or_semantics_fail_closed() -> None:
    unknown = AgentStep("not_registered", {}, RiskClass.READ, state=StepState.EXECUTING)
    active = termination_view(run_with(unknown))["active_tool"]
    assert active["semantics"] is None
    assert active["can_request"] is False
    assert active["reason"] == "tool_is_not_in_registry"

    original = tools.REGISTRY["rig_status"]
    tools.REGISTRY["rig_status"] = dataclasses.replace(original, cancellation="magic")
    try:
        odd = AgentStep("rig_status", {}, RiskClass.READ, state=StepState.EXECUTING)
        active = termination_view(run_with(odd))["active_tool"]
        assert active["semantics"] is None
        assert active["can_request"] is False
        assert active["reason"] == "unknown_registry_cancellation_semantics"
    finally:
        tools.REGISTRY["rig_status"] = original


def test_terminal_and_late_completion_are_truthful() -> None:
    step = AgentStep(
        "note_append",
        {"text": "x"},
        RiskClass.WRITE,
        state=StepState.COMPLETED_AFTER_CANCEL,
        result={"ok": True},
    )
    view = termination_view(run_with(step, RunState.CANCELLED))
    assert view["plan"]["can_request"] is False
    assert view["active_tool"]["request_state"] == "terminal"
    assert view["active_tool"]["reason"] == "tool_completed_after_plan_cancel"


def test_http_contract_is_attached_only_to_agent3_run_envelopes() -> None:
    step = AgentStep("rig_status", {}, RiskClass.READ, state=StepState.EXECUTING)
    run = run_with(step)
    app = FastAPI()
    install_termination_contract(app)
    install_termination_contract(app)

    @app.get("/experimental/agent3/runs/demo")
    def agent3_run():
        return {"run": __import__("json").loads(run.to_json())}

    @app.get("/ordinary")
    def ordinary():
        return {"run": __import__("json").loads(run.to_json())}

    client = TestClient(app)
    agent3 = client.get("/experimental/agent3/runs/demo")
    assert agent3.status_code == 200
    assert agent3.json()["termination"]["schema"] == SCHEMA
    assert agent3.json()["termination"]["active_tool"]["can_request"] is False
    assert "termination" not in client.get("/ordinary").json()


TESTS = [value for name, value in sorted(globals().items()) if name.startswith("test_")]

if __name__ == "__main__":
    for test_case in TESTS:
        test_case()
    print(f"agent3 cancellation contract: {len(TESTS)} passed")
