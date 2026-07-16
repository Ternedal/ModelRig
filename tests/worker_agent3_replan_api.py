from __future__ import annotations

import os
import tempfile
from copy import deepcopy
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.agent3.api import build_router
from app.agent3.core import (
    Agent3Orchestrator,
    AgentRun,
    AgentRunStore,
    AgentStep,
    EgressClass,
    RiskClass,
    RouteKind,
    RoutePlan,
    Sensitivity,
    StepState,
    TurnRequest,
)
from app.agent3.integration import V2ToolAdapter
from app.agent3.replan_runtime import (
    PersistentReadReplanner,
    ReplanJournal,
    plan_digest,
)
from app.agent3.replanner import ReadSuffixReplanner


class Tool:
    def __init__(self, name, risk):
        self.name = name
        self.risk = risk
        self.description = name
        self.params = {"type": "object", "properties": {}}

    def human_summary(self, args):
        return f"{self.name}: {args}"


class Gate:
    enabled = True
    state_error = None

    def __init__(self):
        self.proposals = 0

    @staticmethod
    def is_enabled(name):
        return name in {"rig_status", "list_models", "current_datetime", "note_append"}

    def propose(self, name, args, conversation_id=None, origin="local"):
        self.proposals += 1
        return {"status": "executed", "result": f"{origin}:{name}"}


gate = Gate()
tools = SimpleNamespace(
    REGISTRY={
        "rig_status": Tool("rig_status", "read"),
        "list_models": Tool("list_models", "read"),
        "current_datetime": Tool("current_datetime", "read"),
        "note_append": Tool("note_append", "write"),
    },
    GATE=gate,
)
adapter = V2ToolAdapter(tools)
root = tempfile.mkdtemp(prefix="agent3-replan-api-")
store = AgentRunStore(os.path.join(root, "runs.db"))
journal = ReplanJournal(os.path.join(root, "replans.db"))
service = PersistentReadReplanner(
    store,
    journal,
    ReadSuffixReplanner(max_steps=8, max_replans=3),
)
orch = Agent3Orchestrator(store, adapter.execute, max_steps=8)
app = FastAPI()
app.include_router(build_router(orch, adapter, replan_service=service, worker_version="test"))
client = TestClient(app)


def step(tool, risk=RiskClass.READ, *, state=StepState.PENDING, args=None):
    item = AgentStep(
        tool=tool,
        args={} if args is None else dict(args),
        risk=risk,
        sensitivity=Sensitivity.OPERATIONAL,
        egress=EgressClass.LOCAL,
        origin="local",
        conversation_id="conv-1",
        summary=f"summary:{tool}",
        state=state,
    )
    return item


def make_run(label):
    done = step("rig_status", state=StepState.SUCCEEDED)
    done.result = "online"
    return AgentRun(
        request=TurnRequest(label, mode="rig", tools=True, conversation_id="conv-1"),
        route=RoutePlan(
            RouteKind.RIG_TOOLS_LOCAL,
            "test",
            uses_cloud=False,
            uses_rig=True,
            uses_tools=True,
            uses_rag=False,
        ),
        steps=[
            done,
            step("list_models"),
            step("current_datetime"),
            step("note_append", RiskClass.WRITE, args={"text": label}),
        ],
        current_step=1,
    )


# Explicit developer replan: registry classifies the replacement, journal persists it.
run = make_run("api")
write_id = run.steps[-1].id
store.save(run)
response = client.post(
    f"/experimental/agent3/runs/{run.id}/replan",
    json={
        "reason": "One fresh status read is enough",
        "plan": [{"tool": "rig_status", "args": {"detail": True}}],
    },
)
assert response.status_code == 200, response.text
body = response.json()
assert [item["tool"] for item in body["run"]["steps"]] == [
    "rig_status",
    "rig_status",
    "note_append",
]
assert body["run"]["steps"][-1]["id"] == write_id
assert body["run"]["steps"][-1]["args"] == {"text": "api"}
assert body["replan"]["to_revision"] == 1
assert body["replan"]["added_tools"] == ["rig_status"]
assert gate.proposals == 0, "replanning must not execute replacement tools"

history = client.get(f"/experimental/agent3/runs/{run.id}/replans")
assert history.status_code == 200, history.text
assert history.json()["revision"] == 1
assert history.json()["replan_count"] == 1
assert history.json()["transactions"][0]["state"] == "committed"
assert history.json()["transactions"][0]["receipt"]["reason"] == "One fresh status read is enough"

# Registry may classify a proposed write, but replanner policy refuses it.
blocked = client.post(
    f"/experimental/agent3/runs/{run.id}/replan",
    json={
        "reason": "Attempt to replace reads with a write",
        "plan": [{"tool": "note_append", "args": {"text": "must not happen"}}],
    },
)
assert blocked.status_code == 409, blocked.text
assert gate.proposals == 0
assert store.load(run.id).steps[-1].args == {"text": "api"}

unknown = client.post(
    f"/experimental/agent3/runs/{run.id}/replan",
    json={"reason": "unknown", "plan": [{"tool": "shell", "args": {}}]},
)
assert unknown.status_code == 400, unknown.text

status = client.get("/experimental/agent3/status")
assert status.status_code == 200
assert status.json()["replanner"] == "explicit-pending-read-window"
assert status.json()["production_activation"] is False

# A prepared transaction whose run still matches BEFORE is recovered as aborted
# by an ordinary GET, making recovery visible without mutating the plan.
abort_run = make_run("abort")
store.save(abort_run)
expected_abort = deepcopy(abort_run)
abort_receipt = service.policy.apply(
    expected_abort,
    [step("rig_status")],
    reason="prepared only",
    revision=0,
    replan_count=0,
)
abort_tx = journal.prepare(
    abort_run.id,
    abort_receipt,
    before_digest=plan_digest(abort_run),
    after_digest=plan_digest(expected_abort),
)
recovered = client.get(f"/experimental/agent3/runs/{abort_run.id}")
assert recovered.status_code == 200, recovered.text
assert recovered.json()["replan_recovery"] == [
    {"transaction_id": abort_tx, "outcome": "aborted"}
]
assert [item["tool"] for item in recovered.json()["run"]["steps"]] == [
    "rig_status",
    "list_models",
    "current_datetime",
    "note_append",
]

# A persisted third shape becomes a conflict. Resume must return 409 BEFORE the
# orchestrator/executor can advance the run.
conflict_run = make_run("conflict")
store.save(conflict_run)
expected = deepcopy(conflict_run)
conflict_receipt = service.policy.apply(
    expected,
    [step("rig_status")],
    reason="expected",
    revision=0,
    replan_count=0,
)
journal.prepare(
    conflict_run.id,
    conflict_receipt,
    before_digest=plan_digest(conflict_run),
    after_digest=plan_digest(expected),
)
tampered = deepcopy(conflict_run)
tampered.steps[1:3] = [step("list_models", args={"third": True})]
store.save(tampered)
proposals_before = gate.proposals
resume = client.post(f"/experimental/agent3/runs/{conflict_run.id}/resume")
assert resume.status_code == 409, resume.text
assert gate.proposals == proposals_before, "resume must not execute through a replan conflict"
assert journal.conflicts(conflict_run.id)

cancel = client.post(f"/experimental/agent3/runs/{conflict_run.id}/cancel", json={})
assert cancel.status_code == 409, cancel.text

print("22 passed, 0 failed")
