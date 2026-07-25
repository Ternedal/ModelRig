from __future__ import annotations

import tempfile
from pathlib import Path
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.agent3 import capability_probe
from app.agent3.core import Agent3Orchestrator, AgentRunStore
from app.agent3.integration import V2ToolAdapter
from app.agent3.plan_store import PlanStore
from app.agent3.planner import TypedPlanner
from app.agent3.task_surface import build_task_surface_router

capability_probe.measure = lambda **_kw: {  # type: ignore[assignment]
    "worker_ready": True,
    "rig_reachable": True,
    "rag_ready": True,
    "measured_at": 0.0,
}

passed = failed = 0


def check(condition: bool, label: str) -> None:
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS: {label}")
    else:
        failed += 1
        print(f"  FAIL: {label}")


class Tool:
    def __init__(self, name: str, risk: str, *, idempotent: bool) -> None:
        self.name = name
        self.risk = risk
        self.impact = risk
        self.sensitivity = "operational"
        self.idempotent = idempotent
        self.description = name
        self.params = {"type": "object", "properties": {}}

    def human_summary(self, _args):
        return self.name


class Gate:
    enabled = True
    state_error = None

    def __init__(self) -> None:
        self.proposals: list[str] = []

    def is_enabled(self, name: str) -> bool:
        return self.enabled and name in tools.REGISTRY

    def propose(self, name, _args, _conversation_id, **_kwargs):
        self.proposals.append(name)
        if name == "rig_status":
            return {"status": "executed", "result": {"ok": True}}
        return {
            "status": "confirmation_required",
            "confirmation_id": "must-not-be-consumed",
        }

    def confirm(self, *_args, **_kwargs):
        raise AssertionError("the normal read-only task surface must never confirm a write")


gate = Gate()
tools = SimpleNamespace(
    REGISTRY={
        "rig_status": Tool("rig_status", "read", idempotent=True),
        "note_append": Tool("note_append", "write", idempotent=False),
        "volatile_read": Tool("volatile_read", "read", idempotent=False),
    },
    GATE=gate,
)
adapter = V2ToolAdapter(tools)


def readiness(**overrides):
    value = {
        "schema": "kaliv-agent3-task-readiness/v1",
        "selected_surface": "agent3_readonly",
        "candidate_surface": "agent3_readonly",
        "fallback_surface": "agent2",
        "eligible_for_task_ui": True,
        "operator_enabled": True,
        "normal_chat_route_unchanged": True,
        "production_activation": False,
        "reason": "agent3_readonly_selected",
        "reasons": [],
        "pilot": {
            "report_sha256": "a" * 64,
            "candidate_git_sha": "b" * 40,
        },
        "rig_validation": {"report_sha256": "c" * 64},
    }
    value.update(overrides)
    return value


class Readiness:
    def __init__(self) -> None:
        self.value = readiness()

    def __call__(self):
        return self.value


class PlannerChat:
    def __init__(self, response: str) -> None:
        self.response = response
        self.calls = 0

    async def __call__(self, _messages, _model):
        self.calls += 1
        return self.response


def fixture(response: str):
    temp = tempfile.TemporaryDirectory(prefix="kaliv-task-surface-")
    root = Path(temp.name)
    store = AgentRunStore(str(root / "runs.db"))
    orchestrator = Agent3Orchestrator(store, adapter.execute)
    plans = PlanStore(str(root / "plans.db"))
    state = Readiness()
    chat = PlannerChat(response)
    app = FastAPI()
    app.include_router(
        build_task_surface_router(
            adapter,
            orchestrator,
            plans,
            state,
            planner=TypedPlanner(adapter, chat_fn=chat),
        )
    )
    return temp, TestClient(app), state, chat


# Exact, local, idempotent read plan: preview then one single-use start.
gate.proposals.clear()
temp, client, state, chat = fixture(
    '{"steps":[{"tool":"rig_status","args":{}}],"rationale":"read status"}'
)
preview = client.post("/experimental/agent3/task/plan", json={"message": "status"})
body = preview.json()
check(preview.status_code == 200, "ready task surface accepts a local read preview")
check(body["executed"] is False and gate.proposals == [], "preview never executes a tool")
check(
    body["task_surface"] == "agent3_readonly"
    and body["route"]["kind"] == "rig_tools_local"
    and body["plan"][0]["risk"] == "read"
    and body["plan"][0]["idempotent"] is True,
    "preview exposes only the promoted route and read contract",
)
plan_id = body["plan_id"]
started = client.post(f"/experimental/agent3/task/plans/{plan_id}/start")
started_body = started.json()
check(started.status_code == 200, "single-use task start succeeds while readiness is unchanged")
check(
    started_body["run"]["state"] == "completed"
    and gate.proposals == ["rig_status"],
    "start executes exactly the reviewed read step",
)
check(
    any(event["kind"] == "task_surface_bound" for event in started_body["events"]),
    "run journal records its readiness-bound task surface",
)
check(
    started_body["production_activation"] is False
    and started_body["normal_chat_route_unchanged"] is True,
    "task execution cannot claim activation or normal-chat changes",
)
reused = client.post(f"/experimental/agent3/task/plans/{plan_id}/start")
check(reused.status_code == 409, "task plan token is single-use")
temp.cleanup()


# Readiness is checked before the model and before consuming a plan token.
gate.proposals.clear()
temp, client, state, chat = fixture(
    '{"steps":[{"tool":"rig_status","args":{}}],"rationale":"read status"}'
)
state.value = readiness(
    selected_surface="agent2",
    eligible_for_task_ui=False,
    reason="pilot_report_stale",
    reasons=["pilot_report_stale"],
)
blocked_preview = client.post("/experimental/agent3/task/plan", json={"message": "status"})
check(blocked_preview.status_code == 409 and chat.calls == 0, "Agent 2 fallback blocks before planner invocation")
state.value = readiness()
preview = client.post("/experimental/agent3/task/plan", json={"message": "status"})
plan_id = preview.json()["plan_id"]
state.value = readiness(
    selected_surface="agent2",
    eligible_for_task_ui=False,
    reason="operator_disabled",
    reasons=["operator_disabled"],
)
blocked_start = client.post(f"/experimental/agent3/task/plans/{plan_id}/start")
check(blocked_start.status_code == 409 and gate.proposals == [], "fallback blocks start before token consumption")
state.value = readiness()
restored_start = client.post(f"/experimental/agent3/task/plans/{plan_id}/start")
check(restored_start.status_code == 200, "unconsumed plan may start after exact readiness is restored")
temp.cleanup()


# Same selected surface but changed physical evidence invalidates the reviewed token.
gate.proposals.clear()
temp, client, state, _chat = fixture(
    '{"steps":[{"tool":"rig_status","args":{}}],"rationale":"read status"}'
)
plan_id = client.post(
    "/experimental/agent3/task/plan",
    json={"message": "status"},
).json()["plan_id"]
changed = readiness()
changed["pilot"] = dict(changed["pilot"], report_sha256="d" * 64)
state.value = changed
changed_start = client.post(f"/experimental/agent3/task/plans/{plan_id}/start")
check(changed_start.status_code == 409 and gate.proposals == [], "plan is bound to the exact physical pilot report")
consumed_after_mismatch = client.post(f"/experimental/agent3/task/plans/{plan_id}/start")
check(consumed_after_mismatch.status_code == 409, "evidence-mismatched plan fails closed as consumed")
temp.cleanup()


# A write and a non-idempotent read are rejected after code-owned classification.
for tool_name, label in (
    ("note_append", "write"),
    ("volatile_read", "non-idempotent read"),
):
    gate.proposals.clear()
    temp, client, _state, _chat = fixture(
        '{"steps":[{"tool":"' + tool_name + '","args":{}}],"rationale":"unsafe"}'
    )
    response = client.post("/experimental/agent3/task/plan", json={"message": "unsafe"})
    check(response.status_code == 409 and gate.proposals == [], f"{label} never receives a task plan token")
    temp.cleanup()


# The request shape has no hidden routing knobs to escalate the pilot.
temp, client, _state, chat = fixture(
    '{"steps":[{"tool":"rig_status","args":{}}],"rationale":"read"}'
)
extra = client.post(
    "/experimental/agent3/task/plan",
    json={"message": "status", "mode": "cloud", "allow_rag_cloud": True},
)
check(extra.status_code == 422 and chat.calls == 0, "cloud and RAG knobs are forbidden by the task schema")
temp.cleanup()

print(f"\n===== AGENT3 READONLY TASK SURFACE: {passed} passed, {failed} failed =====")
raise SystemExit(1 if failed else 0)
