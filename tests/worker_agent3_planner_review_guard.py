from __future__ import annotations

import os
import tempfile
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.agent3.core import Agent3Orchestrator, AgentRunStore
from app.agent3.integration import V2ToolAdapter
from app.agent3.plan_store import PlanStore
from app.agent3.planner import TypedPlanner, build_planner_router


class Tool:
    name = "rig_status"
    risk = "read"
    description = "read rig status"
    params = {"type": "object", "properties": {}}

    @staticmethod
    def human_summary(args):
        return f"rig_status: {args}"


class Gate:
    enabled = True
    state_error = None

    @staticmethod
    def is_enabled(name):
        return name == "rig_status"


calls = {"count": 0}


async def chat(_messages, _model):
    calls["count"] += 1
    return '{"steps":[{"tool":"rig_status","args":{}}]}'


root = tempfile.mkdtemp(prefix="agent3-planner-review-guard-")
adapter = V2ToolAdapter(
    SimpleNamespace(REGISTRY={"rig_status": Tool()}, GATE=Gate())
)
base = Agent3Orchestrator(
    AgentRunStore(os.path.join(root, "runs.db")),
    lambda step: {"tool": step.tool},
)
app = FastAPI()
app.include_router(
    build_planner_router(
        adapter,
        TypedPlanner(adapter, chat_fn=chat),
        orchestrator=base,
        plan_store=PlanStore(os.path.join(root, "plans.db")),
    )
)
client = TestClient(app)

response = client.post(
    "/experimental/agent3/plan",
    json={
        "message": "review this read",
        "mode": "rig",
        "review_reads": True,
    },
)
assert response.status_code == 409, response.text
assert response.json()["detail"] == "read review is not mounted"
assert calls["count"] == 0

print("3 passed, 0 failed")
