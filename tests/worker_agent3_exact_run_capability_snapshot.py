from __future__ import annotations

import json
import os
import tempfile
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.agent3 import capability_probe
from app.agent3.api import build_router
from app.agent3.capability_graph_api import build_runtime_capability_graph
from app.agent3.capability_receipt import agent_run_plan_sha256
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
from app.agent3.replan_runtime import PersistentReadReplanner, ReplanJournal
from app.agent3.replanner import ReadSuffixReplanner


class Tool:
    def __init__(self, name: str, risk: str):
        self.name = name
        self.risk = risk
        self.impact = risk
        self.description = f"description:{name}"
        self.params = {"type": "object", "properties": {}}
        self.isolate = False
        self.env_allow = ()
        self.schedulable = True
        self.unschedulable_because = ""
        self.sensitivity = "operational"
        self.cancellation = "none"
        self.idempotent = risk == "read"
        self.network = "none"
        self.network_destinations = ()

    def human_summary(self, args):
        return f"{self.name}: {args}"


class Gate:
    enabled = True
    state_error = None
    disabled: set[str] = set()

    @classmethod
    def is_enabled(cls, name: str) -> bool:
        return name not in cls.disabled

    @staticmethod
    def propose(name, args, conversation_id=None, origin="local"):
        return {"status": "executed", "result": f"{origin}:{name}"}


capability_probe.measure = lambda **_kw: {  # type: ignore[assignment]
    "worker_ready": True,
    "rig_reachable": True,
    "rag_ready": True,
    "measured_at": 0.0,
}

adapter = V2ToolAdapter(
    SimpleNamespace(
        REGISTRY={
            "rig_status": Tool("rig_status", "read"),
            "list_models": Tool("list_models", "read"),
            "note_append": Tool("note_append", "write"),
        },
        GATE=Gate(),
    )
)
root = tempfile.mkdtemp(prefix="agent3-exact-run-capability-snapshot-")
store = AgentRunStore(os.path.join(root, "runs.db"))
journal = ReplanJournal(os.path.join(root, "replans.db"))
service = PersistentReadReplanner(
    store,
    journal,
    ReadSuffixReplanner(max_steps=8, max_replans=3),
)
orch = Agent3Orchestrator(store, adapter.execute, max_steps=8)


def graph_provider():
    return build_runtime_capability_graph(
        adapter,
        worker_version="test-version",
        planner_mounted=True,
        memory_mounted=True,
        replanner_mounted=True,
        review_mounted=True,
    )


app = FastAPI()
app.include_router(
    build_router(
        orch,
        adapter,
        replan_service=service,
        worker_version="test-version",
        allow_client_plans=True,
        exact_run_capability_graph_provider=graph_provider,
    )
)
client = TestClient(app)


def step(tool: str, *, state=StepState.PENDING, args=None, risk=RiskClass.READ):
    item = AgentStep(
        tool=tool,
        args={} if args is None else dict(args),
        risk=risk,
        sensitivity=Sensitivity.OPERATIONAL,
        egress=EgressClass.LOCAL,
        origin="local",
        conversation_id="conv-snapshot",
        summary=f"summary:{tool}",
        state=state,
    )
    return item


done = step("rig_status", state=StepState.SUCCEEDED)
done.result = "online"
run = AgentRun(
    request=TurnRequest(
        "same snapshot",
        mode="rig",
        tools=True,
        conversation_id="conv-snapshot",
    ),
    route=RoutePlan(
        RouteKind.RIG_TOOLS_LOCAL,
        "test route",
        uses_cloud=False,
        uses_rig=True,
        uses_tools=True,
        uses_rag=False,
    ),
    steps=[
        done,
        step("list_models"),
        step("rig_status", args={"before": True}),
        step("note_append", risk=RiskClass.WRITE, args={"text": "tail"}),
    ],
    current_step=1,
)
store.save(run)

before_response = client.get(f"/experimental/agent3/runs/{run.id}")
assert before_response.status_code == 200, before_response.text
before_body = before_response.json()
assert "capability_receipt" in before_body
before_snapshot = AgentRun.from_json(json.dumps(before_body["run"]))
before_digest = before_body["capability_receipt"]["plan_sha256"]
assert before_digest == agent_run_plan_sha256(before_snapshot)
assert before_body["capability_receipt"]["production_activation"] is False

# The additive evidence belongs only to exact GET; other run responses keep their
# established response shape.
listed = client.get("/experimental/agent3/runs")
assert listed.status_code == 200, listed.text
assert "capability_receipt" not in listed.json()

replanned = client.post(
    f"/experimental/agent3/runs/{run.id}/replan",
    json={
        "reason": "change the pending read plan",
        "plan": [{"tool": "rig_status", "args": {"after": True}}],
    },
)
assert replanned.status_code == 200, replanned.text
assert "capability_receipt" not in replanned.json()

after_response = client.get(f"/experimental/agent3/runs/{run.id}")
assert after_response.status_code == 200, after_response.text
after_body = after_response.json()
after_snapshot = AgentRun.from_json(json.dumps(after_body["run"]))
after_digest = after_body["capability_receipt"]["plan_sha256"]
assert after_digest == agent_run_plan_sha256(after_snapshot)
assert after_digest != before_digest
assert [item["tool"] for item in after_body["run"]["steps"]] == [
    "rig_status",
    "rig_status",
    "note_append",
]
assert after_body["run"]["steps"][1]["args"] == {"after": True}

# Capability decoration must never make generic exact GET unavailable. If the
# provider cannot evaluate, the run/review snapshot still returns and the
# capability field is simply absent; reviewed clients requiring it fail closed.
def unavailable_graph_provider():
    raise RuntimeError("fixture capability graph unavailable")

fallback_app = FastAPI()
fallback_app.include_router(
    build_router(
        orch,
        adapter,
        replan_service=service,
        worker_version="test-version",
        exact_run_capability_graph_provider=unavailable_graph_provider,
    )
)
fallback = TestClient(fallback_app).get(f"/experimental/agent3/runs/{run.id}")
assert fallback.status_code == 200, fallback.text
assert fallback.json()["run"]["id"] == run.id
assert "capability_receipt" not in fallback.json()

# Core-only / compatibility construction without a provider is unchanged.
plain_app = FastAPI()
plain_app.include_router(
    build_router(
        orch,
        adapter,
        replan_service=service,
        worker_version="test-version",
    )
)
plain = TestClient(plain_app).get(f"/experimental/agent3/runs/{run.id}")
assert plain.status_code == 200, plain.text
assert "capability_receipt" not in plain.json()

print("16 passed, 0 failed")
