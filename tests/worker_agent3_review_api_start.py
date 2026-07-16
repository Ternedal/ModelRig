from __future__ import annotations

import os
import tempfile
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.agent3.api import build_router
from app.agent3.core import AgentRunStore, CapabilitySnapshot, RiskClass
from app.agent3.integration import V2ToolAdapter
from app.agent3.review_orchestrator import ReadReviewStore, ReviewingAgent3Orchestrator


class Tool:
    def __init__(self, name: str, risk: str):
        self.name = name
        self.risk = risk
        self.description = name
        self.params = {"type": "object", "properties": {}}

    def human_summary(self, args):
        return f"{self.name}: {args}"


class Gate:
    enabled = True
    state_error = None

    @staticmethod
    def is_enabled(name: str) -> bool:
        return name in {"rig_status", "list_models", "note_append"}


class Executor:
    def __init__(self):
        self.calls: list[str] = []

    def __call__(self, step):
        self.calls.append(step.tool)
        return {"tool": step.tool, "ok": True}


root = tempfile.mkdtemp(prefix="agent3-review-api-start-")
run_store = AgentRunStore(os.path.join(root, "runs.db"))
review_store = ReadReviewStore(os.path.join(root, "reviews.db"))
executor = Executor()
orchestrator = ReviewingAgent3Orchestrator(run_store, executor, review_store)
tools = SimpleNamespace(
    REGISTRY={
        "rig_status": Tool("rig_status", "read"),
        "list_models": Tool("list_models", "read"),
        "note_append": Tool("note_append", "write"),
    },
    GATE=Gate(),
)
adapter = V2ToolAdapter(tools)


def caps(_req, _adapter):
    return CapabilitySnapshot(
        rig_reachable=True,
        worker_ready=True,
        tools_ready=True,
        cloud_ready=False,
        rag_ready=True,
    )


app = FastAPI()
app.include_router(build_router(orchestrator, adapter, capability_provider=caps))
client = TestClient(app)

response = client.post(
    "/experimental/agent3/runs",
    json={
        "message": "review reads before write",
        "mode": "rig",
        "tools": True,
        "review_reads": True,
        "conversation_id": "conv-review-api",
        "plan": [
            {"tool": "rig_status", "args": {}},
            {"tool": "list_models", "args": {}},
            {"tool": "note_append", "args": {"text": "fixed"}},
        ],
    },
)
assert response.status_code == 200, response.text
payload = response.json()
run = payload["run"]
review = payload["read_review"]

assert executor.calls == ["rig_status"]
assert run["current_step"] == 1
assert run["state"] == "running"
assert run["steps"][0]["state"] == "succeeded"
assert run["steps"][1]["state"] == "pending"
assert run["steps"][2]["risk"] == RiskClass.WRITE.value
assert run["steps"][2]["state"] == "pending"
assert review["enabled"] is True
assert review["waiting"] is True
assert review["window_start"] == 1
assert review["window_end"] == 2
assert review["removable_step_ids"] == [run["steps"][1]["id"]]
assert review["completed_step_id"] == run["steps"][0]["id"]
assert review["completed_tool"] == "rig_status"

loaded = client.get(f"/experimental/agent3/runs/{run['id']}")
assert loaded.status_code == 200, loaded.text
loaded_payload = loaded.json()
assert loaded_payload["run"]["current_step"] == 1
assert loaded_payload["read_review"]["waiting"] is True
assert loaded_payload["read_review"]["removable_step_ids"] == [run["steps"][1]["id"]]
assert executor.calls == ["rig_status"]

plain = client.post(
    "/experimental/agent3/runs",
    json={
        "message": "default flow stays unchanged",
        "mode": "rig",
        "tools": True,
        "plan": [
            {"tool": "rig_status", "args": {}},
            {"tool": "list_models", "args": {}},
            {"tool": "note_append", "args": {"text": "fixed"}},
        ],
    },
)
assert plain.status_code == 200, plain.text
plain_payload = plain.json()
assert executor.calls[-2:] == ["rig_status", "list_models"]
assert plain_payload["run"]["state"] == "waiting_confirmation"
assert plain_payload["run"]["current_step"] == 2
assert plain_payload["read_review"]["enabled"] is False
assert plain_payload["read_review"]["waiting"] is False

print("24 passed, 0 failed")
