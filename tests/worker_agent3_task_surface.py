from __future__ import annotations

import tempfile
import threading
import time
from pathlib import Path
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.agent3 import capability_probe
from app.agent3.core import Agent3Orchestrator, AgentRunStore
from app.agent3.integration import V2ToolAdapter
from app.agent3.plan_store import PlanStore
from app.agent3.planner import TypedPlanner
from app.agent3.task_surface import TaskExecutionPool, build_task_surface_router

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
        # Current main validates the complete kaliv-capability/v2 descriptor
        # before a tool reaches the planner prompt. The fixture declares every
        # registry-owned axis instead of relying on the pre-v2 test double shape.
        self.isolate = False
        self.schedulable = True
        self.unschedulable_because = ""
        self.env_allow = ()
        self.network = "none"
        self.network_destinations = ()
        self.cancellation = "none"

    def human_summary(self, _args):
        return self.name


class Gate:
    enabled = True
    state_error = None

    def __init__(self) -> None:
        self.proposals: list[str] = []
        self.slow_started = threading.Event()
        self.slow_release = threading.Event()

    def reset(self) -> None:
        self.proposals.clear()
        self.slow_started.clear()
        self.slow_release.clear()

    def is_enabled(self, name: str) -> bool:
        return self.enabled and name in tools.REGISTRY

    def propose(self, name, _args, _conversation_id, **_kwargs):
        self.proposals.append(name)
        if name == "slow_read":
            self.slow_started.set()
            if not self.slow_release.wait(timeout=10):
                raise RuntimeError("slow read test was not released")
            return {"status": "executed", "result": {"ok": True, "slow": True}}
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
        "slow_read": Tool("slow_read", "read", idempotent=True),
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


class Fixture:
    def __init__(self, response: str, *, workers: int = 1) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="kaliv-task-surface-")
        root = Path(self.temp.name)
        self.store = AgentRunStore(str(root / "runs.db"))
        self.orchestrator = Agent3Orchestrator(self.store, adapter.execute)
        self.plans = PlanStore(str(root / "plans.db"))
        self.state = Readiness()
        self.chat = PlannerChat(response)
        self.pool = TaskExecutionPool(workers)
        app = FastAPI()
        app.include_router(
            build_task_surface_router(
                adapter,
                self.orchestrator,
                self.plans,
                self.state,
                self.pool,
                planner=TypedPlanner(adapter, chat_fn=self.chat),
            )
        )
        self.client = TestClient(app)

    def close(self) -> None:
        gate.slow_release.set()
        self.pool.shutdown()
        self.temp.cleanup()


def plan(fixture: Fixture, tool: str = "rig_status") -> str:
    response = fixture.client.post(
        "/experimental/agent3/task/plan",
        json={"message": tool},
    )
    check(response.status_code == 200, f"{tool} receives a read-only preview")
    return response.json()["plan_id"]


def wait_terminal(fixture: Fixture, run_id: str, timeout: float = 5.0) -> dict:
    deadline = time.time() + timeout
    latest: dict = {}
    while time.time() < deadline:
        response = fixture.client.get(f"/experimental/agent3/task/runs/{run_id}")
        if response.status_code != 200:
            return {"status_code": response.status_code, "body": response.json()}
        latest = response.json()
        if latest.get("terminal") is True:
            return latest
        time.sleep(0.02)
    return latest


# Exact, local, idempotent read plan: preview, accepted run, poll outcome.
gate.reset()
fixture = Fixture(
    '{"steps":[{"tool":"rig_status","args":{}}],"rationale":"read status"}'
)
preview = fixture.client.post("/experimental/agent3/task/plan", json={"message": "status"})
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
started = fixture.client.post(f"/experimental/agent3/task/plans/{plan_id}/start")
started_body = started.json()
check(started.status_code == 202, "start accepts the reviewed task without waiting for completion")
run_id = started_body["run"]["id"]
check(
    any(event["kind"] == "task_surface_bound" for event in started_body["events"]),
    "run journal records its readiness-bound task surface before execution",
)
completed = wait_terminal(fixture, run_id)
check(
    completed.get("run", {}).get("state") == "completed"
    and gate.proposals == ["rig_status"],
    "polling observes exactly the reviewed read step complete",
)
check(
    completed["production_activation"] is False
    and completed["normal_chat_route_unchanged"] is True,
    "task execution cannot claim activation or normal-chat changes",
)
reused = fixture.client.post(f"/experimental/agent3/task/plans/{plan_id}/start")
check(reused.status_code == 409, "task plan token is single-use")
fixture.close()


# Readiness is checked before the model and before consuming a plan token.
gate.reset()
fixture = Fixture(
    '{"steps":[{"tool":"rig_status","args":{}}],"rationale":"read status"}'
)
fixture.state.value = readiness(
    selected_surface="agent2",
    eligible_for_task_ui=False,
    reason="pilot_report_stale",
    reasons=["pilot_report_stale"],
)
blocked_preview = fixture.client.post("/experimental/agent3/task/plan", json={"message": "status"})
check(blocked_preview.status_code == 409 and fixture.chat.calls == 0, "Agent 2 fallback blocks before planner invocation")
fixture.state.value = readiness()
plan_id = plan(fixture)
fixture.state.value = readiness(
    selected_surface="agent2",
    eligible_for_task_ui=False,
    reason="operator_disabled",
    reasons=["operator_disabled"],
)
blocked_start = fixture.client.post(f"/experimental/agent3/task/plans/{plan_id}/start")
check(blocked_start.status_code == 409 and gate.proposals == [], "fallback blocks start before token consumption")
fixture.state.value = readiness()
restored_start = fixture.client.post(f"/experimental/agent3/task/plans/{plan_id}/start")
check(restored_start.status_code == 202, "unconsumed plan may start after exact readiness is restored")
wait_terminal(fixture, restored_start.json()["run"]["id"])
fixture.close()


# Same selected surface but changed physical evidence invalidates the reviewed token.
gate.reset()
fixture = Fixture(
    '{"steps":[{"tool":"rig_status","args":{}}],"rationale":"read status"}'
)
plan_id = plan(fixture)
changed = readiness()
changed["pilot"] = dict(changed["pilot"], report_sha256="d" * 64)
fixture.state.value = changed
changed_start = fixture.client.post(f"/experimental/agent3/task/plans/{plan_id}/start")
check(changed_start.status_code == 409 and gate.proposals == [], "plan is bound to the exact physical pilot report")
consumed_after_mismatch = fixture.client.post(f"/experimental/agent3/task/plans/{plan_id}/start")
check(consumed_after_mismatch.status_code == 409, "evidence-mismatched plan fails closed as consumed")
fixture.close()


# A write and a non-idempotent read are rejected after code-owned classification.
for tool_name, label in (
    ("note_append", "write"),
    ("volatile_read", "non-idempotent read"),
):
    gate.reset()
    fixture = Fixture(
        '{"steps":[{"tool":"' + tool_name + '","args":{}}],"rationale":"unsafe"}'
    )
    response = fixture.client.post("/experimental/agent3/task/plan", json={"message": "unsafe"})
    check(response.status_code == 409 and gate.proposals == [], f"{label} never receives a task plan token")
    fixture.close()


# The request shape has no hidden routing knobs to escalate the pilot.
gate.reset()
fixture = Fixture(
    '{"steps":[{"tool":"rig_status","args":{}}],"rationale":"read"}'
)
extra = fixture.client.post(
    "/experimental/agent3/task/plan",
    json={"message": "status", "mode": "cloud", "allow_rag_cloud": True},
)
check(extra.status_code == 422 and fixture.chat.calls == 0, "cloud and RAG knobs are forbidden by the task schema")
fixture.close()


# Stop targets the rig run and remains reachable after readiness falls back.
gate.reset()
fixture = Fixture(
    '{"steps":[{"tool":"slow_read","args":{}}],"rationale":"slow read"}'
)
plan_id = plan(fixture, "slow_read")
started = fixture.client.post(f"/experimental/agent3/task/plans/{plan_id}/start")
check(started.status_code == 202, "slow read returns a run id before the tool completes")
run_id = started.json()["run"]["id"]
check(gate.slow_started.wait(timeout=2), "background worker actually entered the slow read")
fixture.state.value = readiness(
    selected_surface="agent2",
    eligible_for_task_ui=False,
    reason="pilot_report_stale",
    reasons=["pilot_report_stale"],
)
cancelled = fixture.client.post(f"/experimental/agent3/task/runs/{run_id}/cancel")
check(
    cancelled.status_code == 200 and cancelled.json()["run"]["state"] == "cancelled",
    "Stop remains reachable and cancels the task after readiness fallback",
)
gate.slow_release.set()
terminal = wait_terminal(fixture, run_id)
check(
    terminal.get("run", {}).get("state") == "cancelled"
    and any(event["kind"] == "run_cancelled" for event in terminal.get("events", [])),
    "late read completion cannot resurrect a cancelled task",
)
fixture.close()


# Capacity is non-queuing and does not burn the next reviewed token.
gate.reset()
fixture = Fixture(
    '{"steps":[{"tool":"slow_read","args":{}}],"rationale":"slow read"}',
    workers=1,
)
first_plan = plan(fixture, "slow_read")
first = fixture.client.post(f"/experimental/agent3/task/plans/{first_plan}/start")
first_run = first.json()["run"]["id"]
check(gate.slow_started.wait(timeout=2), "the only task worker is occupied")
second_plan = plan(fixture, "slow_read")
busy = fixture.client.post(f"/experimental/agent3/task/plans/{second_plan}/start")
check(busy.status_code == 503, "busy task workers reject instead of queueing hidden work")
fixture.client.post(f"/experimental/agent3/task/runs/{first_run}/cancel")
gate.slow_release.set()
wait_terminal(fixture, first_run)
# A terminal run is persisted inside execute_task(); the worker semaphore is
# released immediately afterwards by TaskExecutionPool's executor wrapper. A
# client can therefore observe terminal state during that tiny hand-off and
# legitimately receive another 503. The API contract says that busy rejection
# preserves the plan token, so retry that same token within a bounded window.
deadline = time.time() + 2.0
second = fixture.client.post(f"/experimental/agent3/task/plans/{second_plan}/start")
while second.status_code == 503 and time.time() < deadline:
    time.sleep(0.01)
    second = fixture.client.post(f"/experimental/agent3/task/plans/{second_plan}/start")
check(
    second.status_code == 202,
    "busy rejection preserves the single-use task token until worker capacity returns",
)
if second.status_code == 202:
    wait_terminal(fixture, second.json()["run"]["id"])
fixture.close()


print(f"\n===== AGENT3 READONLY TASK SURFACE: {passed} passed, {failed} failed =====")
raise SystemExit(1 if failed else 0)
