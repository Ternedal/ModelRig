from __future__ import annotations

from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.agent3.capability_graph_api import build_capability_graph_router
from app.agent3.integration import V2ToolAdapter


class Tool:
    def __init__(self, name, risk):
        self.name = name
        self.risk = risk
        self.impact = risk
        self.description = f"description:{name}"
        self.params = {"type": "object", "properties": {"password": {"type": "string"}}}
        self.isolate = False
        self.env_allow = ()
        self.schedulable = True
        self.unschedulable_because = ""
        self.sensitivity = "operational"
        self.cancellation = "none"
        self.idempotent = risk == "read"
        self.network = "none"
        self.network_destinations = ()


class Gate:
    enabled = True
    state_error = None

    @staticmethod
    def is_enabled(name):
        return name == "rig_status"


adapter = V2ToolAdapter(
    SimpleNamespace(
        REGISTRY={
            "rig_status": Tool("rig_status", "read"),
            "note_append": Tool("note_append", "write"),
        },
        GATE=Gate(),
    )
)
app = FastAPI()
app.include_router(
    build_capability_graph_router(
        adapter,
        worker_version="test-version",
        planner_mounted=True,
        memory_mounted=True,
        replanner_mounted=True,
        review_mounted=True,
    )
)
client = TestClient(app)

response = client.get("/experimental/agent3/capabilities")
assert response.status_code == 200, response.text
payload = response.json()
assert payload["schema"] == "kaliv-agent3-capability-graph/v1"
assert payload["production_activation"] is False
nodes = {node["id"]: node for node in payload["nodes"]}
assert nodes["tool:rig_status"]["state"] == "ready"
assert nodes["tool:note_append"]["state"] == "disabled"
assert nodes["tool:note_append"]["metadata"] == {
    "risk": "write",
    "cancellation": "none",
    "description": "description:note_append",
}
assert "params" not in nodes["tool:rig_status"]["metadata"]
assert "network" not in nodes["tool:rig_status"]["metadata"]
assert "password" not in response.text.lower()
assert nodes["production_activation"]["state"] == "blocked"
assert nodes["production_activation"]["metadata"]["value"] is False
assert nodes["validation"]["state"] == "blocked"

before = response.json()
second = client.get("/experimental/agent3/capabilities")
assert second.status_code == 200
assert second.json() == before

print("18 passed, 0 failed")
