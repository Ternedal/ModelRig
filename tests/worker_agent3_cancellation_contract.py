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
    Agent3Orchestrator,
    AgentRun,
    AgentRunStore,
    AgentStep,
    CapabilitySnapshot,
    ConfirmationError,
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


def test_blocked_run_is_terminal_and_never_offers_plan_stop() -> None:
    step = AgentStep(
        "rig_status",
        {},
        RiskClass.READ,
        state=StepState.BLOCKED,
        error="capability unavailable",
    )
    view = termination_view(run_with(step, RunState.BLOCKED))
    assert view["plan"] == {
        "state": "terminal",
        "can_request": False,
        "request_scope": "plan",
        "effect": "prevent_future_steps",
        "reason": "run_is_terminal",
    }
    assert view["active_tool"]["request_state"] == "not_active"
    assert view["active_tool"]["can_request"] is False


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


def _waiting_write_run(
    orch: Agent3Orchestrator,
    caps: CapabilitySnapshot,
    label: str,
) -> AgentRun:
    return orch.start_with_steps(
        TurnRequest(label, mode="rig", tools=True),
        caps,
        [AgentStep("write_once", {"label": label}, RiskClass.WRITE)],
    )


def test_cancel_wins_before_confirmation_approval_commit() -> None:
    temp = tempfile.mkdtemp(prefix="kaliv-agent3-confirm-race-")
    store = AgentRunStore(os.path.join(temp, "agent3.db"))
    executed = []

    def executor(step):
        executed.append((step.tool, dict(step.args)))
        return {"ok": True}

    orch = Agent3Orchestrator(store=store, executor=executor, confirmation_ttl_seconds=30)
    caps = CapabilitySnapshot(
        rig_reachable=True,
        worker_ready=True,
        tools_ready=True,
        cloud_ready=False,
        rag_ready=False,
    )
    run = _waiting_write_run(orch, caps, "cancel-before-approval-commit")
    assert run.state == RunState.WAITING_CONFIRMATION
    step = run.steps[0]
    real_cas = store.save_with_event_if_unchanged
    fired = {"value": False}

    def cancel_before_approval(run_arg, **kwargs):
        if kwargs.get("kind") == "confirmation_approved" and not fired["value"]:
            fired["value"] = True
            orch.cancel(run_arg.id)
        return real_cas(run_arg, **kwargs)

    store.save_with_event_if_unchanged = cancel_before_approval  # type: ignore[method-assign]
    try:
        try:
            orch.confirm(run.id, step.id, "approve", step.confirmation_digest)
        except ConfirmationError:
            blocked = True
        else:
            blocked = False
    finally:
        store.save_with_event_if_unchanged = real_cas  # type: ignore[method-assign]

    fresh = store.load(run.id)
    assert fired["value"]
    assert blocked
    assert fresh is not None and fresh.state == RunState.CANCELLED
    assert executed == []
    kinds = [event["kind"] for event in store.events(run.id)]
    assert "run_cancelled" in kinds
    assert "confirmation_approved" not in kinds


def test_cancel_wins_before_execution_start() -> None:
    temp = tempfile.mkdtemp(prefix="kaliv-agent3-step-start-race-")
    store = AgentRunStore(os.path.join(temp, "agent3.db"))
    executed = []

    def executor(step):
        executed.append((step.tool, dict(step.args)))
        return {"ok": True}

    orch = Agent3Orchestrator(store=store, executor=executor, confirmation_ttl_seconds=30)
    caps = CapabilitySnapshot(
        rig_reachable=True,
        worker_ready=True,
        tools_ready=True,
        cloud_ready=False,
        rag_ready=False,
    )
    run = _waiting_write_run(orch, caps, "cancel-before-step-start")
    step = run.steps[0]
    real_cas = store.save_with_event_if_unchanged
    fired = {"value": False}

    def cancel_before_step_started(run_arg, **kwargs):
        if kwargs.get("kind") == "step_started" and not fired["value"]:
            fired["value"] = True
            orch.cancel(run_arg.id)
        return real_cas(run_arg, **kwargs)

    store.save_with_event_if_unchanged = cancel_before_step_started  # type: ignore[method-assign]
    try:
        result = orch.confirm(run.id, step.id, "approve", step.confirmation_digest)
    finally:
        store.save_with_event_if_unchanged = real_cas  # type: ignore[method-assign]

    fresh = store.load(run.id)
    assert fired["value"]
    assert result.state == RunState.CANCELLED
    assert fresh is not None and fresh.state == RunState.CANCELLED
    assert executed == []
    kinds = [event["kind"] for event in store.events(run.id)]
    assert "confirmation_approved" in kinds
    assert "run_cancelled" in kinds
    assert "step_started" not in kinds


TESTS = [value for name, value in sorted(globals().items()) if name.startswith("test_")]

if __name__ == "__main__":
    for test_case in TESTS:
        test_case()
    print(f"agent3 cancellation contract: {len(TESTS)} passed")
