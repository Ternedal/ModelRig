from __future__ import annotations

import json
import os
import tempfile
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.agent3.capability_graph_api import build_runtime_capability_graph
from app.agent3.capability_receipt import agent_run_plan_sha256
from app.agent3.capability_receipt_api import build_capability_receipt_router
from app.agent3.core import (
    AgentRun,
    AgentRunStore,
    AgentStep,
    EgressClass,
    RiskClass,
    RouteKind,
    RoutePlan,
    Sensitivity,
    TurnRequest,
)
from app.agent3.integration import V2ToolAdapter

# The capability receipt now describes the rig it MEASURES (F-302): before
# 1.58.67 rig_reachable/rag_ready were hardcoded True, so this test passed by
# inheriting an assumption. There is no Ollama in CI, so a real probe correctly
# reports the rig as unreachable and the receipt correctly refuses. State the
# assumption instead of depending on the environment.
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


class Gate:
    enabled = True
    state_error = None
    disabled: set[str] = set()

    @classmethod
    def is_enabled(cls, name):
        return name not in cls.disabled


adapter = V2ToolAdapter(
    SimpleNamespace(
        REGISTRY={
            "rig_status": Tool("rig_status", "read"),
            "note_append": Tool("note_append", "write"),
        },
        GATE=Gate(),
    )
)
root = tempfile.mkdtemp(prefix="agent3-capability-receipt-api-")
store = AgentRunStore(os.path.join(root, "runs.db"))


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
app.include_router(build_capability_receipt_router(store, graph_provider))
client = TestClient(app)

run = AgentRun(
    request=TurnRequest(
        "capability receipt",
        mode="rig",
        tools=True,
        conversation_id="conv-receipt",
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
        AgentStep(
            tool="rig_status",
            args={"private_value": "never-return-this"},
            risk=RiskClass.READ,
            sensitivity=Sensitivity.OPERATIONAL,
            egress=EgressClass.LOCAL,
            origin="local",
            conversation_id="conv-receipt",
        )
    ],
)
store.save(run)
before_digest = agent_run_plan_sha256(run)
before_events = store.events(run.id)

response = client.get(f"/experimental/agent3/runs/{run.id}/capability-receipt")
assert response.status_code == 200, response.text
payload = response.json()
assert payload["run_id"] == run.id
assert payload["run_state"] == "running"
assert payload["current_step"] == 0
assert payload["evaluated"] is True
assert payload["executed"] is False
receipt = payload["receipt"]
assert receipt["schema"] == "kaliv-agent3-capability-receipt/v1"
assert receipt["allowed"] is True
assert receipt["production_activation"] is False
assert receipt["plan_sha256"] == before_digest
assert len(receipt["graph_sha256"]) == 64
assert receipt["blockers"] == []
assert "never-return-this" not in response.text
assert "private_value" not in response.text
assert agent_run_plan_sha256(store.load(run.id)) == before_digest
assert store.events(run.id) == before_events

Gate.disabled.add("rig_status")
blocked = client.get(f"/experimental/agent3/runs/{run.id}/capability-receipt")
assert blocked.status_code == 200, blocked.text
blocked_receipt = blocked.json()["receipt"]
assert blocked_receipt["allowed"] is False
assert any(
    item["capability_id"] == "tool:rig_status" and item["state"] == "disabled"
    for item in blocked_receipt["blockers"]
)
assert blocked_receipt["plan_sha256"] == before_digest
assert agent_run_plan_sha256(store.load(run.id)) == before_digest
Gate.disabled.clear()

cloud = AgentRun(
    request=TurnRequest(
        "cloud receipt",
        mode="cloud",
        tools=True,
        conversation_id="conv-cloud",
    ),
    route=RoutePlan(
        RouteKind.RIG_TOOLS_CLOUD,
        "cloud route",
        uses_cloud=True,
        uses_rig=True,
        uses_tools=True,
        uses_rag=False,
    ),
    steps=[
        AgentStep(
            tool="rig_status",
            args={},
            risk=RiskClass.READ,
            sensitivity=Sensitivity.OPERATIONAL,
            egress=EgressClass.CLOUD,
            origin="cloud",
            conversation_id="conv-cloud",
        )
    ],
)
store.save(cloud)
cloud_response = client.get(
    f"/experimental/agent3/runs/{cloud.id}/capability-receipt"
)
assert cloud_response.status_code == 200, cloud_response.text
assert cloud_response.json()["receipt"]["allowed"] is False
assert any(
    item["capability_id"] == "cloud"
    for item in cloud_response.json()["receipt"]["blockers"]
)

assert client.get(
    "/experimental/agent3/runs/does-not-exist/capability-receipt"
).status_code == 404
assert client.post(
    f"/experimental/agent3/runs/{run.id}/capability-receipt",
    json={},
).status_code == 405

parsed = json.loads(response.text)
assert set(parsed) == {
    "run_id",
    "run_state",
    "current_step",
    "receipt",
    "evaluated",
    "executed",
}

print("31 passed, 0 failed")
