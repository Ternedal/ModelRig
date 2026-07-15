from __future__ import annotations

import os
import tempfile

from app.agent3.core import (
    Agent3Orchestrator,
    AgentRunStore,
    AgentStep,
    CapabilitySnapshot,
    EgressClass,
    RiskClass,
    RouteKind,
    RunState,
    Sensitivity,
    TurnRequest,
)

passed = failed = 0
executed: list[str] = []


def check(cond, name):
    global passed, failed
    if cond:
        passed += 1
        print(f"  PASS: {name}")
    else:
        failed += 1
        print(f"  FAIL: {name}")


def execute(step: AgentStep):
    executed.append(step.id)
    return {"ok": True}


store = AgentRunStore(os.path.join(tempfile.mkdtemp(prefix="agent3-cloud-policy-"), "runs.db"))
orch = Agent3Orchestrator(store, execute, confirmation_ttl_seconds=30)
caps = CapabilitySnapshot(True, True, True, True, True, False)
local_req = TurnRequest("status", mode="rig", tools=True)
cloud_req = TurnRequest("status", mode="cloud", tools=True)

local = orch.start_with_steps(
    local_req,
    caps,
    [AgentStep("rig_status", {}, RiskClass.READ, egress=EgressClass.LOCAL, origin="local")],
)
check(local.state == RunState.COMPLETED, "local read executes without confirmation")
check(len(executed) == 1, "local read reached executor")

cloud = orch.start_with_steps(
    cloud_req,
    caps,
    [
        AgentStep(
            "rig_status",
            {},
            RiskClass.READ,
            sensitivity=Sensitivity.OPERATIONAL,
            egress=EgressClass.CLOUD,
            origin="cloud",
        )
    ],
)
check(cloud.route.kind == RouteKind.RIG_TOOLS_CLOUD, "cloud tools route is selected")
check(cloud.state == RunState.WAITING_CONFIRMATION, "operational cloud read waits for confirmation")
check(len(executed) == 1, "cloud read did not reach executor before confirmation")
cloud_step = cloud.steps[0]
cloud = orch.confirm(cloud.id, cloud_step.id, "approve", cloud_step.confirmation_digest)
check(cloud.state == RunState.COMPLETED, "approved cloud read completes")
check(len(executed) == 2, "approved cloud read reaches executor exactly once")

private_blocked = orch.start_with_steps(
    cloud_req,
    caps,
    [
        AgentStep(
            "list_documents",
            {},
            RiskClass.READ,
            sensitivity=Sensitivity.PRIVATE,
            egress=EgressClass.CLOUD,
            origin="cloud",
        )
    ],
)
check(private_blocked.state == RunState.BLOCKED, "private cloud read is blocked without consent")

private_allowed = orch.start_with_steps(
    cloud_req,
    caps,
    [
        AgentStep(
            "list_documents",
            {},
            RiskClass.READ,
            sensitivity=Sensitivity.PRIVATE,
            egress=EgressClass.CLOUD,
            origin="cloud",
        )
    ],
    allow_private_cloud=True,
)
check(private_allowed.state == RunState.WAITING_CONFIRMATION, "private consent does not replace per-call confirmation")

secret = orch.start_with_steps(
    cloud_req,
    caps,
    [
        AgentStep(
            "read_secret",
            {},
            RiskClass.READ,
            sensitivity=Sensitivity.SECRET,
            egress=EgressClass.CLOUD,
            origin="cloud",
        )
    ],
    allow_private_cloud=True,
)
check(secret.state == RunState.BLOCKED, "secret data is never allowed to cloud")

cloud_write = orch.start_with_steps(
    cloud_req,
    caps,
    [
        AgentStep(
            "note_append",
            {"text": "x"},
            RiskClass.WRITE,
            sensitivity=Sensitivity.PRIVATE,
            egress=EgressClass.CLOUD,
            origin="cloud",
        )
    ],
    allow_private_cloud=True,
)
check(cloud_write.state == RunState.WAITING_CONFIRMATION, "cloud write also waits for confirmation")

print(f"\n{passed} passed, {failed} failed")
raise SystemExit(1 if failed else 0)
