from __future__ import annotations

import json
import os
import tempfile
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.agent3 import capability_probe as _probe
from app.agent3.api import build_router
from app.agent3.cancellation_status import install_termination_contract
from app.agent3.capability_graph_api import build_runtime_capability_graph
from app.agent3.capability_receipt import agent_run_plan_sha256
from app.agent3.capability_receipt_api import build_capability_receipt_router
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
    TurnRequest,
)
from app.agent3.integration import V2ToolAdapter
from app.agent3.replan_runtime import PersistentReadReplanner, ReplanJournal
from app.agent3.replanner import ReadSuffixReplanner

# The capability receipt now describes the rig it MEASURES (F-302): before
# 1.58.67 rig_reachable/rag_ready were hardcoded True, so this test passed by
# inheriting an assumption. There is no Ollama in CI, so a real probe correctly
# reports the rig as unreachable and the receipt correctly refuses. State the
# assumption instead of depending on the environment.
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

# #1255: exact generic GET capability evidence is calculated from the exact
# serialized run in that response. It is not a later independent store read.
snapshot_root = tempfile.mkdtemp(prefix="agent3-run-snapshot-capability-")
snapshot_store = AgentRunStore(os.path.join(snapshot_root, "runs.db"))
snapshot_orchestrator = Agent3Orchestrator(
    store=snapshot_store,
    executor=adapter.execute,
)
snapshot_replanner = PersistentReadReplanner(
    snapshot_store,
    ReplanJournal(os.path.join(snapshot_root, "replans.db")),
    ReadSuffixReplanner(max_steps=12, max_replans=3),
)
snapshot_app = FastAPI(version="test-version")
snapshot_app.include_router(
    build_router(
        snapshot_orchestrator,
        adapter,
        worker_version="test-version",
        replan_service=snapshot_replanner,
    )
)
snapshot_app.state.agent3_orchestrator = snapshot_orchestrator
snapshot_app.state.agent3_replanner = snapshot_replanner
snapshot_app.state.agent3_mounted = True
install_termination_contract(snapshot_app)
snapshot_client = TestClient(snapshot_app)

snapshot_run = AgentRun(
    request=TurnRequest(
        "snapshot receipt",
        mode="rig",
        tools=True,
        conversation_id="conv-snapshot",
    ),
    route=RoutePlan(
        RouteKind.RIG_TOOLS_LOCAL,
        "snapshot route",
        uses_cloud=False,
        uses_rig=True,
        uses_tools=True,
        uses_rag=False,
    ),
    steps=[
        AgentStep(
            tool="rig_status",
            args={"revision": 1},
            risk=RiskClass.READ,
            sensitivity=Sensitivity.OPERATIONAL,
            egress=EgressClass.LOCAL,
            origin="local",
            conversation_id="conv-snapshot",
        )
    ],
)
snapshot_store.save(snapshot_run)

first_get = snapshot_client.get(f"/experimental/agent3/runs/{snapshot_run.id}")
assert first_get.status_code == 200, first_get.text
first_payload = first_get.json()
assert "capability_receipt" in first_payload
first_returned_run = AgentRun.from_json(
    json.dumps(first_payload["run"], ensure_ascii=False, sort_keys=True)
)
first_snapshot_digest = first_payload["capability_receipt"]["plan_sha256"]
assert first_snapshot_digest == agent_run_plan_sha256(first_returned_run)
assert first_payload["capability_receipt"]["production_activation"] is False

replacement = AgentStep(
    tool="rig_status",
    args={"revision": 2},
    risk=RiskClass.READ,
    sensitivity=Sensitivity.OPERATIONAL,
    egress=EgressClass.LOCAL,
    origin="local",
    conversation_id="conv-snapshot",
)
revised, replan_receipt = snapshot_replanner.apply(
    snapshot_run.id,
    [replacement],
    reason="change pending read args",
)
assert replan_receipt.to_revision == 1
assert revised.steps[0].args == {"revision": 2}

second_get = snapshot_client.get(f"/experimental/agent3/runs/{snapshot_run.id}")
assert second_get.status_code == 200, second_get.text
second_payload = second_get.json()
second_returned_run = AgentRun.from_json(
    json.dumps(second_payload["run"], ensure_ascii=False, sort_keys=True)
)
second_snapshot_digest = second_payload["capability_receipt"]["plan_sha256"]
assert second_snapshot_digest == agent_run_plan_sha256(second_returned_run)
assert second_snapshot_digest != first_snapshot_digest
assert second_payload["run"]["current_step"] == first_payload["run"]["current_step"] == 0
assert second_payload["run"]["state"] == first_payload["run"]["state"] == "running"

# Scope is exact generic GET only. The run list has no synthetic per-run receipt.
list_payload = snapshot_client.get("/experimental/agent3/runs").json()
assert "capability_receipt" not in list_payload

# #1258: pin the documented production composition order. The middleware is
# installed while Agent 3 is still dormant, then the full mount supplies runtime
# authority later. Request-time lookup must still produce exact-run evidence.
from app.agent3.production_mount import close_agent3, mount_agent3

with tempfile.TemporaryDirectory(prefix="agent3-production-composition-") as composition_root:
    composition_env = {
        "KALIV_AGENT3_ENABLED": "1",
        "KALIV_AGENT3_DB": os.path.join(composition_root, "runs.db"),
        "KALIV_AGENT3_REVIEW_DB": os.path.join(composition_root, "reviews.db"),
        "KALIV_AGENT3_REPLAN_DB": os.path.join(composition_root, "replans.db"),
        "KALIV_AGENT3_MEMORY_DB": os.path.join(composition_root, "memory.db"),
        "KALIV_AGENT3_PLAN_DB": os.path.join(composition_root, "plans.db"),
        "KALIV_AGENT3_TASK_PLAN_DB": os.path.join(composition_root, "task-plans.db"),
        "KALIV_AGENT3_APPROVAL_DB": os.path.join(composition_root, "approvals.db"),
        "KALIV_AGENT3_MEMORY_STORE": "legacy",
        "KALIV_AGENT3_TASK_WORKERS": "1",
    }
    old_env = {name: os.environ.get(name) for name in composition_env}
    try:
        os.environ.update(composition_env)
        composition_app = FastAPI(version="test-version")
        assert not getattr(composition_app.state, "agent3_mounted", False)

        install_termination_contract(composition_app)
        early_middleware_count = len(composition_app.user_middleware)
        assert early_middleware_count == 1
        assert getattr(composition_app.state, "agent3_termination_contract_mounted", False)
        assert not getattr(composition_app.state, "agent3_mounted", False)

        assert mount_agent3(composition_app) is True
        assert getattr(composition_app.state, "agent3_mounted", False)
        assert len(composition_app.user_middleware) == early_middleware_count

        composition_run = AgentRun(
            request=TurnRequest(
                "production composition receipt",
                mode="rig",
                tools=False,
                conversation_id="conv-production-composition",
            ),
            route=RoutePlan(
                RouteKind.DIRECT_RIG,
                "production composition route",
                uses_cloud=False,
                uses_rig=True,
                uses_tools=False,
                uses_rag=False,
            ),
            steps=[],
        )
        composition_app.state.agent3_orchestrator.store.save(composition_run)
        composition_client = TestClient(composition_app)
        try:
            exact_get = composition_client.get(
                f"/experimental/agent3/runs/{composition_run.id}"
            )
            assert exact_get.status_code == 200, exact_get.text
            exact_payload = exact_get.json()
            assert "capability_receipt" in exact_payload
            exact_returned_run = AgentRun.from_json(
                json.dumps(exact_payload["run"], ensure_ascii=False, sort_keys=True)
            )
            assert (
                exact_payload["capability_receipt"]["plan_sha256"]
                == agent_run_plan_sha256(exact_returned_run)
            )
            assert exact_payload["capability_receipt"]["production_activation"] is False

            events_get = composition_client.get(
                f"/experimental/agent3/runs/{composition_run.id}/events"
            )
            assert events_get.status_code == 200, events_get.text
            assert "capability_receipt" not in events_get.json()
        finally:
            composition_client.close()
            close_agent3(composition_app)

        assert composition_app.state.agent3_resources_closed is True
        assert composition_app.state.agent3_mounted is False
    finally:
        for name, previous in old_env.items():
            if previous is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = previous

print("53 passed, 0 failed")
