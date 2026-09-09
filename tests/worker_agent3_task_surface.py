from __future__ import annotations

import sqlite3
import tempfile
import threading
import time
from pathlib import Path
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.agent3 import capability_probe
from app.agent3.core import Agent3Orchestrator, AgentRunStore, StepState
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
    def __init__(
        self,
        response: str,
        *,
        workers: int = 1,
        root: Path | None = None,
    ) -> None:
        self.temp = None if root is not None else tempfile.TemporaryDirectory(prefix="kaliv-task-surface-")
        self.root = root if root is not None else Path(self.temp.name)
        self.store = AgentRunStore(str(self.root / "runs.db"))
        self.orchestrator = Agent3Orchestrator(self.store, adapter.execute)
        self.plans = PlanStore(str(self.root / "plans.db"))
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
        self.client.close()
        self.pool.shutdown()
        self.plans.close()
        self.store._conn.close()
        if self.temp is not None:
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
with sqlite3.connect(fixture.plans.path) as connection:
    terminal_retention = connection.execute(
        "SELECT start_terminal_at,expires_at FROM agent_plans WHERE id=?",
        (plan_id,),
    ).fetchone()
check(
    terminal_retention is not None
    and terminal_retention[0] is not None
    and float(terminal_retention[1]) > time.time(),
    "completed task retains same-plan Start recovery for a bounded grace",
)
check(
    completed["production_activation"] is False
    and completed["normal_chat_route_unchanged"] is True,
    "task execution cannot claim activation or normal-chat changes",
)
reused = fixture.client.post(f"/experimental/agent3/task/plans/{plan_id}/start")
check(
    reused.status_code == 202 and reused.json()["run"]["id"] == run_id,
    "accepted task Start replays the exact same task run",
)
check(gate.proposals == ["rig_status"], "accepted Start replay never executes the tool twice")
with sqlite3.connect(fixture.plans.path) as connection:
    replay_retention = connection.execute(
        "SELECT start_terminal_at,expires_at FROM agent_plans WHERE id=?",
        (plan_id,),
    ).fetchone()
check(
    replay_retention == terminal_retention,
    "same-plan replay does not extend terminal recovery grace forever",
)
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
check(
    changed_start.status_code == 409
    and changed_start.json().get("detail", {}).get("reason") == "task_start_refused"
    and gate.proposals == [],
    "plan is bound to the exact physical pilot report",
)
consumed_after_mismatch = fixture.client.post(f"/experimental/agent3/task/plans/{plan_id}/start")
check(
    consumed_after_mismatch.status_code == 409
    and consumed_after_mismatch.json().get("detail", {}).get("reason") == "task_start_refused",
    "evidence-mismatched plan remains definitively refused on replay",
)
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
with sqlite3.connect(fixture.plans.path) as connection:
    connection.execute(
        "UPDATE agent_plans SET expires_at=? WHERE id=?",
        (time.time() - 1, plan_id),
    )
    connection.commit()
check(
    fixture.plans.purge() == 0
    and fixture.plans.start_recovery(plan_id) is not None,
    "cleanup never drops an active Start recovery record solely on TTL",
)
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
with sqlite3.connect(fixture.plans.path) as connection:
    cancelled_retention = connection.execute(
        "SELECT start_terminal_at,expires_at FROM agent_plans WHERE id=?",
        (plan_id,),
    ).fetchone()
check(
    cancelled_retention is not None
    and cancelled_retention[0] is not None
    and float(cancelled_retention[1]) > time.time(),
    "cancelled task starts bounded same-plan recovery retention",
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


# Executor-submit failure happens after run acceptance. Replay returns that same
# cancelled run instead of consuming the plan into an unrecoverable ambiguity.
gate.reset()
fixture = Fixture(
    '{"steps":[{"tool":"rig_status","args":{}}],"rationale":"read status"}'
)
executor_plan = plan(fixture)
fixture.pool.submit_reserved = lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("executor unavailable"))  # type: ignore[method-assign]
executor_failed = fixture.client.post(f"/experimental/agent3/task/plans/{executor_plan}/start")
check(executor_failed.status_code == 503, "executor-submit failure is reported on the first Start")
executor_replay = fixture.client.post(f"/experimental/agent3/task/plans/{executor_plan}/start")
check(
    executor_replay.status_code == 409
    and executor_replay.json().get("detail", {}).get("reason") == "task_start_refused",
    "executor-submit failure remains definitively refused on replay",
)
check(gate.proposals == [], "executor-submit failure never executes the task")
fixture.close()




class SimulatedWorkerRestart(BaseException):
    pass


def leave_bound_start_without_executor(fixture: Fixture) -> tuple[str, str, str | None]:
    plan_id = plan(fixture)
    original_submit = fixture.pool.submit_reserved

    def crash_before_submit(*_args, **_kwargs) -> None:
        raise SimulatedWorkerRestart()

    fixture.pool.submit_reserved = crash_before_submit  # type: ignore[method-assign]
    crashed = False
    try:
        # BaseException bypasses normal Start cleanup, matching abrupt process
        # death after the claimed run is persisted and task-bound but pre-submit.
        fixture.client.post(f"/experimental/agent3/task/plans/{plan_id}/start")
    except SimulatedWorkerRestart:
        crashed = True
    finally:
        fixture.pool.submit_reserved = original_submit  # type: ignore[method-assign]
    check(crashed, "simulated worker restart lands after pending run binding")
    recovery = fixture.plans.start_recovery(plan_id)
    check(
        recovery is not None and recovery[0] == "pending" and bool(recovery[1]),
        "crash leaves one persisted pending run and no executor acceptance",
    )
    assert recovery is not None and recovery[1] is not None
    return plan_id, recovery[1], recovery[2]


def leave_claim_without_run(fixture: Fixture) -> tuple[str, str, str | None]:
    plan_id = plan(fixture)
    original_claim = fixture.plans.claim_task_start

    def claim_then_crash(bound_plan_id: str, run_id: str, prepared_run: str) -> None:
        original_claim(bound_plan_id, run_id, prepared_run)
        raise SimulatedWorkerRestart()

    fixture.plans.claim_task_start = claim_then_crash  # type: ignore[method-assign]
    crashed = False
    try:
        fixture.client.post(f"/experimental/agent3/task/plans/{plan_id}/start")
    except SimulatedWorkerRestart:
        crashed = True
    finally:
        fixture.plans.claim_task_start = original_claim  # type: ignore[method-assign]
    check(crashed, "simulated worker restart lands immediately after atomic Start claim")
    recovery = fixture.plans.start_recovery(plan_id)
    check(
        recovery is not None
        and recovery[0] == "pending"
        and bool(recovery[1])
        and fixture.store.load(recovery[1]) is None,
        "atomic claim persists one run id before RunStore materialization",
    )
    assert recovery is not None and recovery[1] is not None
    return plan_id, recovery[1], recovery[2]


# Same-generation replay cannot parallel-materialize a Start that crashed just
# after the atomic claim; a new worker generation can recover that exact run id.
gate.reset()
shared = tempfile.TemporaryDirectory(prefix="kaliv-task-restart-prebind-")
root = Path(shared.name)
first = Fixture(
    '{"steps":[{"tool":"rig_status","args":{}}],"rationale":"restart prebind"}',
    root=root,
)
prebind_plan, prebind_run, prebind_owner = leave_claim_without_run(first)
same_generation = first.client.post(f"/experimental/agent3/task/plans/{prebind_plan}/start")
check(
    same_generation.status_code == 409
    and same_generation.json().get("detail", {}).get("reason") == "task_start_pending"
    and first.store.load(prebind_run) is None
    and gate.proposals == [],
    "same worker generation leaves claimed-but-unmaterialized Start pending",
)
first.close()
second = Fixture(
    '{"steps":[{"tool":"rig_status","args":{}}],"rationale":"restart prebind"}',
    root=root,
)
check(second.plans.start_owner != prebind_owner, "prebind recovery sees a new worker generation")
prebind_recovered = second.client.post(f"/experimental/agent3/task/plans/{prebind_plan}/start")
check(
    prebind_recovered.status_code == 202
    and prebind_recovered.json()["run"]["id"] == prebind_run,
    "new worker materializes the exact server-generated run id from atomic claim",
)
terminal = wait_terminal(second, prebind_run)
check(
    terminal.get("run", {}).get("state") == "completed"
    and gate.proposals == ["rig_status"],
    "prebind crash recovery executes the reviewed read exactly once",
)
second.close()
shared.cleanup()


# Crash after run_created but before task_surface_bound is repaired by adding
# only the missing binding to the exact prepared run, then executing once.
gate.reset()
shared = tempfile.TemporaryDirectory(prefix="kaliv-task-restart-run-created-")
root = Path(shared.name)
first = Fixture(
    '{"steps":[{"tool":"rig_status","args":{}}],"rationale":"restart run created"}',
    root=root,
)
run_created_plan = plan(first)
original_event = first.store.event

def crash_before_binding(run_id: str, kind: str, payload) -> None:
    if kind == "task_surface_bound":
        raise SimulatedWorkerRestart()
    original_event(run_id, kind, payload)

first.store.event = crash_before_binding  # type: ignore[method-assign]
crashed = False
try:
    first.client.post(f"/experimental/agent3/task/plans/{run_created_plan}/start")
except SimulatedWorkerRestart:
    crashed = True
finally:
    first.store.event = original_event  # type: ignore[method-assign]
recovery = first.plans.start_recovery(run_created_plan)
assert recovery is not None and recovery[1] is not None
run_created_run = recovery[1]
check(
    crashed
    and first.store.load(run_created_run) is not None
    and not any(event.get("kind") == "task_surface_bound" for event in first.store.events(run_created_run))
    and gate.proposals == [],
    "worker crash can leave exact run_created truth without task binding or execution",
)
first.close()
second = Fixture(
    '{"steps":[{"tool":"rig_status","args":{}}],"rationale":"restart run created"}',
    root=root,
)
run_created_recovered = second.client.post(
    f"/experimental/agent3/task/plans/{run_created_plan}/start"
)
check(
    run_created_recovered.status_code == 202
    and run_created_recovered.json()["run"]["id"] == run_created_run,
    "restart binds and resumes the exact already-created run",
)
terminal = wait_terminal(second, run_created_run)
events = terminal.get("events", [])
check(
    terminal.get("run", {}).get("state") == "completed"
    and gate.proposals == ["rig_status"]
    and sum(event.get("kind") == "run_created" for event in events) == 1
    and sum(event.get("kind") == "task_surface_bound" for event in events) == 1,
    "run-created crash recovery adds one binding and never duplicates run/tool execution",
)
second.close()
shared.cleanup()


# A new worker generation reclaims the exact pending run; no second run is created.
gate.reset()
shared = tempfile.TemporaryDirectory(prefix="kaliv-task-restart-pending-")
root = Path(shared.name)
first = Fixture(
    '{"steps":[{"tool":"rig_status","args":{}}],"rationale":"restart"}',
    root=root,
)
pending_plan, pending_run, pending_owner = leave_bound_start_without_executor(first)
check(gate.proposals == [], "pre-submit worker crash executes no tool")
first.close()
second = Fixture(
    '{"steps":[{"tool":"rig_status","args":{}}],"rationale":"restart"}',
    root=root,
)
check(second.plans.start_owner != pending_owner, "restarted task store has a distinct generation")
recovered = second.client.post(f"/experimental/agent3/task/plans/{pending_plan}/start")
check(
    recovered.status_code == 202 and recovered.json()["run"]["id"] == pending_run,
    "same-plan replay after worker restart reclaims the exact existing run",
)
terminal = wait_terminal(second, pending_run)
check(
    terminal.get("run", {}).get("state") == "completed" and gate.proposals == ["rig_status"],
    "reclaimed pending run executes the reviewed read exactly once",
)
replayed = second.client.post(f"/experimental/agent3/task/plans/{pending_plan}/start")
check(
    replayed.status_code == 202
    and replayed.json()["run"]["id"] == pending_run
    and gate.proposals == ["rig_status"],
    "post-recovery replay returns the same run without a second execution",
)
second.close()
shared.cleanup()


# Persisted EXECUTING idempotent read is atomically reset and resumed on restart.
gate.reset()
shared = tempfile.TemporaryDirectory(prefix="kaliv-task-restart-executing-")
root = Path(shared.name)
first = Fixture(
    '{"steps":[{"tool":"rig_status","args":{}}],"rationale":"restart executing"}',
    root=root,
)
executing_plan, executing_run, _ = leave_bound_start_without_executor(first)
run = first.store.load(executing_run)
assert run is not None
run.steps[run.current_step].state = StepState.EXECUTING
first.store.save_with_event(
    run,
    "step_started",
    {"step_id": run.steps[run.current_step].id, "tool": run.steps[run.current_step].tool},
)
first.close()
second = Fixture(
    '{"steps":[{"tool":"rig_status","args":{}}],"rationale":"restart executing"}',
    root=root,
)
executing_recovery = second.client.post(f"/experimental/agent3/task/plans/{executing_plan}/start")
check(
    executing_recovery.status_code == 202
    and executing_recovery.json()["run"]["id"] == executing_run,
    "dead-owner EXECUTING run keeps its original run id",
)
terminal = wait_terminal(second, executing_run)
check(
    terminal.get("run", {}).get("state") == "completed"
    and gate.proposals == ["rig_status"]
    and any(
        event.get("kind") == "task_interrupted_execution_replayable"
        for event in terminal.get("events", [])
    ),
    "idempotent EXECUTING state is CAS-reset before one resumed read",
)
second.close()
shared.cleanup()


# Persisted SUCCEEDED result advances after restart without invoking the tool again.
gate.reset()
shared = tempfile.TemporaryDirectory(prefix="kaliv-task-restart-succeeded-")
root = Path(shared.name)
first = Fixture(
    '{"steps":[{"tool":"rig_status","args":{}}],"rationale":"restart succeeded"}',
    root=root,
)
succeeded_plan, succeeded_run, _ = leave_bound_start_without_executor(first)
run = first.store.load(succeeded_run)
assert run is not None
step = run.steps[run.current_step]
step.state = StepState.SUCCEEDED
step.result = {"status": "executed", "result": {"ok": True}}
first.store.save_with_event(
    run,
    "step_succeeded",
    {"step_id": step.id, "tool": step.tool},
)
first.close()
second = Fixture(
    '{"steps":[{"tool":"rig_status","args":{}}],"rationale":"restart succeeded"}',
    root=root,
)
succeeded_recovery = second.client.post(f"/experimental/agent3/task/plans/{succeeded_plan}/start")
check(
    succeeded_recovery.status_code == 202
    and succeeded_recovery.json()["run"]["id"] == succeeded_run,
    "SUCCEEDED crash recovery retains the original run",
)
terminal = wait_terminal(second, succeeded_run)
check(
    terminal.get("run", {}).get("state") == "completed" and gate.proposals == [],
    "persisted SUCCEEDED step advances without duplicate tool execution",
)
second.close()
shared.cleanup()


# Even an already-accepted nonterminal run is reattached by scoped status after restart.
gate.reset()
shared = tempfile.TemporaryDirectory(prefix="kaliv-task-restart-accepted-")
root = Path(shared.name)
first = Fixture(
    '{"steps":[{"tool":"rig_status","args":{}}],"rationale":"accepted restart"}',
    root=root,
)
accepted_plan, accepted_run, _ = leave_bound_start_without_executor(first)
first.plans.mark_start_accepted(accepted_plan, accepted_run)
first.close()
second = Fixture(
    '{"steps":[{"tool":"rig_status","args":{}}],"rationale":"accepted restart"}',
    root=root,
)
status = second.client.get(f"/experimental/agent3/task/runs/{accepted_run}")
check(
    status.status_code == 200 and status.json()["run"]["id"] == accepted_run,
    "retained run-id status authority reattaches accepted work after worker restart",
)
terminal = wait_terminal(second, accepted_run)
check(
    terminal.get("run", {}).get("state") == "completed" and gate.proposals == ["rig_status"],
    "accepted restart recovery resumes the same idempotent read exactly once",
)
second.close()
shared.cleanup()


print(f"\n===== AGENT3 READONLY TASK SURFACE: {passed} passed, {failed} failed =====")
raise SystemExit(1 if failed else 0)
