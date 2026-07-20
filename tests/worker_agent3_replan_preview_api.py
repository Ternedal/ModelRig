from __future__ import annotations

import os
import tempfile
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.agent3.core import (
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
from app.agent3.plan_store import PlanStore
from app.agent3.replan_planner import TypedReadReplanPlanner
from app.agent3.replan_preview import ReplanPreviewService
from app.agent3.replan_preview_api import build_replan_preview_router
from app.agent3.replan_runtime import PersistentReadReplanner, ReplanJournal, plan_digest
from app.agent3.replanner import ReadSuffixReplanner


class Tool:
    def __init__(self, name, risk):
        self.name = name
        self.risk = risk
        self.impact = risk
        self.description = name
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

    @staticmethod
    def is_enabled(name):
        return name in {"rig_status", "list_models", "current_datetime", "note_append"}

    @staticmethod
    def propose(*_args, **_kwargs):
        raise AssertionError("preview and apply are planning operations")


tools = SimpleNamespace(
    REGISTRY={
        "rig_status": Tool("rig_status", "read"),
        "list_models": Tool("list_models", "read"),
        "current_datetime": Tool("current_datetime", "read"),
        "note_append": Tool("note_append", "write"),
    },
    GATE=Gate(),
)
adapter = V2ToolAdapter(tools)


def make_step(tool, risk=RiskClass.READ, *, state=StepState.PENDING, cloud=False, args=None):
    return AgentStep(
        tool=tool,
        args={} if args is None else dict(args),
        risk=risk,
        sensitivity=Sensitivity.OPERATIONAL,
        egress=EgressClass.CLOUD if cloud else EgressClass.LOCAL,
        origin="cloud" if cloud else "local",
        conversation_id="conv-1",
        summary=f"summary:{tool}",
        state=state,
    )


def make_run(label, *, cloud=False):
    completed = make_step("rig_status", state=StepState.SUCCEEDED, cloud=cloud)
    completed.result = {"status": "online", "source": label}
    return AgentRun(
        request=TurnRequest(
            label,
            mode="cloud" if cloud else "rig",
            tools=True,
            conversation_id="conv-1",
        ),
        route=RoutePlan(
            RouteKind.RIG_TOOLS_CLOUD if cloud else RouteKind.RIG_TOOLS_LOCAL,
            "test",
            uses_cloud=cloud,
            uses_rig=True,
            uses_tools=True,
            uses_rag=False,
        ),
        steps=[
            completed,
            make_step("list_models", cloud=cloud),
            make_step("current_datetime", cloud=cloud),
            make_step(
                "note_append",
                RiskClass.WRITE,
                cloud=cloud,
                args={"text": f"fixed-tail-{label}"},
            ),
        ],
        current_step=1,
    )


calls = {"count": 0}


async def scripted_chat(messages, model):
    calls["count"] += 1
    assert model == "local-replanner"
    assert "fixed-tail-" not in messages[0]["content"]
    return '{"steps":[{"tool":"rig_status","args":{"detail":true}}],"rationale":"One fresh status read is sufficient"}'


root = tempfile.mkdtemp(prefix="agent3-replan-preview-api-")
store = AgentRunStore(os.path.join(root, "runs.db"))
journal = ReplanJournal(os.path.join(root, "journal.db"))
policy = ReadSuffixReplanner(max_steps=8, max_replans=3)
persistent = PersistentReadReplanner(store, journal, policy)
service = ReplanPreviewService(
    store,
    persistent,
    TypedReadReplanPlanner(adapter, policy, chat_fn=scripted_chat),
    PlanStore(os.path.join(root, "previews.db"), ttl_seconds=300),
)
app = FastAPI()
app.include_router(build_replan_preview_router(service))
client = TestClient(app)

run = make_run("normal")
write_id = run.steps[-1].id
store.save(run)
before = plan_digest(run)
preview_response = client.post(
    f"/experimental/agent3/runs/{run.id}/replan-preview",
    json={"planner_model": "local-replanner"},
)
assert preview_response.status_code == 200, preview_response.text
preview = preview_response.json()
assert preview["executed"] is False
assert preview["revision"] == 0
assert preview["replan_count"] == 0
assert preview["planner_model"] == "local-replanner"
assert len(preview["prompt_sha256"]) == 64
assert preview["window"]["removable_step_ids"] == [run.steps[1].id, run.steps[2].id]
assert preview["window"]["immutable_tail_ids"] == [write_id]
assert preview["plan"][0]["tool"] == "rig_status"
assert preview["plan"][0]["risk"] == "read"
assert plan_digest(store.load(run.id)) == before
assert journal.history(run.id) == []
assert calls["count"] == 1

preview_id = preview["preview_id"]
apply_response = client.post(
    f"/experimental/agent3/replan-previews/{preview_id}/apply"
)
assert apply_response.status_code == 200, apply_response.text
applied = apply_response.json()
assert [item["tool"] for item in applied["run"]["steps"]] == [
    "rig_status",
    "rig_status",
    "note_append",
]
assert applied["run"]["steps"][-1]["id"] == write_id
assert applied["run"]["steps"][-1]["args"] == {"text": "fixed-tail-normal"}
assert applied["replan"]["to_revision"] == 1
assert applied["replan"]["added_tools"] == ["rig_status"]
assert applied["preview"]["prompt_sha256"] == preview["prompt_sha256"]
assert journal.revision_state(run.id) == (1, 1)
assert calls["count"] == 1
assert client.post(
    f"/experimental/agent3/replan-previews/{preview_id}/apply"
).status_code == 409

stale_run = make_run("stale")
store.save(stale_run)
stale_preview = client.post(
    f"/experimental/agent3/runs/{stale_run.id}/replan-preview",
    json={"planner_model": "local-replanner"},
)
assert stale_preview.status_code == 200, stale_preview.text
stale_id = stale_preview.json()["preview_id"]
changed = store.load(stale_run.id)
changed.steps[1].args["changed"] = True
store.save(changed)
stale_apply = client.post(f"/experimental/agent3/replan-previews/{stale_id}/apply")
assert stale_apply.status_code == 409, stale_apply.text
assert "stale" in stale_apply.json()["detail"]

cloud_run = make_run("cloud", cloud=True)
store.save(cloud_run)
before_cloud = calls["count"]
cloud_preview = client.post(
    f"/experimental/agent3/runs/{cloud_run.id}/replan-preview",
    json={"planner_model": "local-replanner"},
)
assert cloud_preview.status_code == 409, cloud_preview.text
assert calls["count"] == before_cloud

missing = client.post(
    "/experimental/agent3/runs/does-not-exist/replan-preview",
    json={"planner_model": "local-replanner"},
)
assert missing.status_code == 404, missing.text
assert client.post(
    "/experimental/agent3/replan-previews/does-not-exist/apply"
).status_code == 409

print("25 passed, 0 failed")
