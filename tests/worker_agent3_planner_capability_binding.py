from __future__ import annotations

import json
import os
import tempfile
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.agent3.capability_graph_api import build_runtime_capability_graph
from app.agent3.capability_receipt import agent_run_plan_sha256
from app.agent3.core import Agent3Orchestrator, AgentRun, AgentRunStore, CapabilitySnapshot
from app.agent3.integration import V2ToolAdapter
from app.agent3.plan_store import PlanStore
from app.agent3.planner import TypedPlanner, build_planner_router
# The planner now plans against a rig it MEASURES (F-302, completed in 1.58.73:
# the 1.58.67 fix reached api.py and capability_graph_api.py and missed this
# one). There is no Ollama in CI, so an honest probe reports the rig
# unreachable and the planner correctly refuses to plan rig work against it.
# This test is about planning, not about whether Ollama is up -- so state the
# assumption instead of inheriting it.
from app.agent3 import capability_probe as _probe  # noqa: E402

_probe.measure = lambda **kw: {  # type: ignore[assignment]
    "worker_ready": True,
    "rig_reachable": True,
    "rag_ready": True,
    "measured_at": 0.0,
}



class Tool:
    def __init__(self, name: str, risk: str):
        self.name = name
        self.risk = risk
        self.description = f"description:{name}"
        self.params = {"type": "object", "properties": {}}

    def human_summary(self, args):
        return f"{self.name}: {args}"


class Gate:
    enabled = True
    state_error = None
    disabled: set[str] = set()

    @classmethod
    def is_enabled(cls, name):
        return cls.enabled and name not in cls.disabled


adapter = V2ToolAdapter(
    SimpleNamespace(
        REGISTRY={"rig_status": Tool("rig_status", "read")},
        GATE=Gate(),
    )
)


async def scripted_chat(_messages, _model):
    return (
        '{"steps":[{"tool":"rig_status",'
        '"args":{"private_value":"bound-but-not-in-receipt"}}],'
        '"rationale":"Read current rig status"}'
    )


class RecordingPlanStore(PlanStore):
    def __init__(self, path: str):
        super().__init__(path, ttl_seconds=300)
        self.last_payload: str | None = None

    def save(self, payload: str):
        self.last_payload = payload
        return super().save(payload)


root = tempfile.mkdtemp(prefix="agent3-planner-capability-binding-")
run_store = AgentRunStore(os.path.join(root, "runs.db"))
plan_store = RecordingPlanStore(os.path.join(root, "plans.db"))
executed: list[str] = []
orchestrator = Agent3Orchestrator(
    run_store,
    lambda step: executed.append(step.tool) or {"ok": True},
)
runtime = {"voice": False, "cloud": False}


def graph_provider():
    return build_runtime_capability_graph(
        adapter,
        worker_version="test-version",
        capabilities=CapabilitySnapshot(
            rig_reachable=True,
            worker_ready=True,
            tools_ready=True,
            cloud_ready=runtime["cloud"],
            rag_ready=True,
            voice_ready=runtime["voice"],
        ),
    )


app = FastAPI()
app.include_router(
    build_planner_router(
        adapter,
        TypedPlanner(adapter, chat_fn=scripted_chat),
        orchestrator=orchestrator,
        plan_store=plan_store,
        capability_graph_provider=graph_provider,
    )
)
client = TestClient(app)


def preview(**overrides):
    payload = {
        "message": "Check rig",
        "mode": "rig",
        "conversation_id": "conv-capability",
    }
    payload.update(overrides)
    response = client.post("/experimental/agent3/plan", json=payload)
    assert response.status_code == 200, response.text
    return response.json()


# Unchanged local graph: preview receipt is stored and returned unchanged at start.
first = preview()
receipt = first["capability_receipt"]
assert receipt["schema"] == "kaliv-agent3-capability-receipt/v1"
assert receipt["allowed"] is True
assert receipt["production_activation"] is False
assert len(receipt["graph_sha256"]) == 64
assert len(receipt["plan_sha256"]) == 64
assert "bound-but-not-in-receipt" not in json.dumps(receipt, sort_keys=True)
assert plan_store.last_payload is not None
stored = json.loads(plan_store.last_payload)
template = AgentRun.from_json(stored["run"])
assert stored["capability_receipt"] == receipt
assert receipt["plan_sha256"] == agent_run_plan_sha256(template)

started = client.post(f"/experimental/agent3/plans/{first['plan_id']}/start")
assert started.status_code == 200, started.text
started_payload = started.json()
assert started_payload["capability_receipt"] == receipt
assert started_payload["run"]["state"] == "completed"
assert executed == ["rig_status"]

# Any graph change invalidates the reviewed token, even when unrelated to this route.
stale_graph = preview()
runtime["voice"] = True
stale_response = client.post(
    f"/experimental/agent3/plans/{stale_graph['plan_id']}/start"
)
assert stale_response.status_code == 409, stale_response.text
assert "stale" in stale_response.json()["detail"]
assert client.post(
    f"/experimental/agent3/plans/{stale_graph['plan_id']}/start"
).status_code == 409
runtime["voice"] = False
assert executed == ["rig_status"]

# The existing V2 kill switch wins after preview and consumes the stale token.
stale_gate = preview()
Gate.enabled = False
gate_response = client.post(
    f"/experimental/agent3/plans/{stale_gate['plan_id']}/start"
)
assert gate_response.status_code == 409, gate_response.text
assert "stale" in gate_response.json()["detail"]
Gate.enabled = True
assert executed == ["rig_status"]

# Client-declared cloud readiness cannot override the server graph.
cloud = preview(mode="cloud", cloud_ready=True)
assert cloud["route"]["uses_cloud"] is True
assert cloud["capability_receipt"]["allowed"] is False
assert any(
    blocker["capability_id"] == "cloud"
    for blocker in cloud["capability_receipt"]["blockers"]
)
cloud_start = client.post(f"/experimental/agent3/plans/{cloud['plan_id']}/start")
assert cloud_start.status_code == 409, cloud_start.text
assert "blocked" in cloud_start.json()["detail"]
assert executed == ["rig_status"]

# Legacy router construction remains compatible when no graph provider is mounted.
legacy_store = RecordingPlanStore(os.path.join(root, "legacy-plans.db"))
legacy_app = FastAPI()
legacy_app.include_router(
    build_planner_router(
        adapter,
        TypedPlanner(adapter, chat_fn=scripted_chat),
        orchestrator=orchestrator,
        plan_store=legacy_store,
    )
)
legacy = TestClient(legacy_app).post(
    "/experimental/agent3/plan",
    json={"message": "legacy", "mode": "rig"},
)
assert legacy.status_code == 200, legacy.text
assert "capability_receipt" not in legacy.json()

print("35 passed, 0 failed")
