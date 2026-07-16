from __future__ import annotations

import json

from app.agent3.capability_graph import (
    CapabilityGraph,
    ToolCapability,
    build_capability_graph,
)
from app.agent3.capability_receipt import (
    agent_run_plan_sha256,
    capability_graph_sha256,
    evaluate_run_capabilities,
)
from app.agent3.core import (
    AgentRun,
    AgentStep,
    CapabilitySnapshot,
    EgressClass,
    RiskClass,
    RouteKind,
    RoutePlan,
    Sensitivity,
    TurnRequest,
)


def make_run(*, cloud=False, rag=False, voice=False, tool="rig_status", risk=RiskClass.READ):
    route = RoutePlan(
        RouteKind.RIG_TOOLS_CLOUD if cloud else RouteKind.RIG_TOOLS_LOCAL,
        "test",
        uses_cloud=cloud,
        uses_rig=True,
        uses_tools=True,
        uses_rag=rag,
    )
    return AgentRun(
        request=TurnRequest(
            "capability receipt",
            mode="cloud" if cloud else "rig",
            tools=True,
            rag=rag,
            voice=voice,
            conversation_id="conv-1",
        ),
        route=route,
        steps=[
            AgentStep(
                tool=tool,
                args={"private_value": "must-not-appear-in-receipt"},
                risk=risk,
                sensitivity=Sensitivity.OPERATIONAL,
                egress=EgressClass.CLOUD if cloud else EgressClass.LOCAL,
                origin="cloud" if cloud else "local",
                conversation_id="conv-1",
            )
        ],
    )


def graph(*, cloud=True, rag=True, voice=True, status_enabled=True):
    return build_capability_graph(
        CapabilitySnapshot(
            rig_reachable=True,
            worker_ready=True,
            tools_ready=True,
            cloud_ready=cloud,
            rag_ready=rag,
            voice_ready=voice,
        ),
        [
            ToolCapability("rig_status", status_enabled, "read", "status"),
            ToolCapability("note_append", True, "write", "note"),
        ],
        planner_mounted=True,
        memory_mounted=True,
        replanner_mounted=True,
        review_mounted=True,
    )


local_run = make_run()
local_graph = graph()
receipt = evaluate_run_capabilities(local_graph, local_run)
assert receipt.allowed is True
assert receipt.route == "rig_tools_local"
assert receipt.production_activation is False
assert len(receipt.graph_sha256) == 64
assert len(receipt.plan_sha256) == 64
assert receipt.required_capability_ids == (
    "rig",
    "tool:rig_status",
    "tool_gate",
    "worker",
)
assert receipt.blockers == ()
serialized = json.dumps(receipt.to_dict(), sort_keys=True)
assert "must-not-appear-in-receipt" not in serialized
assert "private_value" not in serialized

reordered = CapabilityGraph(
    schema=local_graph.schema,
    nodes=tuple(reversed(local_graph.nodes)),
    edges=tuple(reversed(local_graph.edges)),
    production_activation=False,
)
assert capability_graph_sha256(reordered) == capability_graph_sha256(local_graph)

same = AgentRun.from_json(local_run.to_json())
assert agent_run_plan_sha256(same) == agent_run_plan_sha256(local_run)
same.steps[0].args["changed"] = True
assert agent_run_plan_sha256(same) != agent_run_plan_sha256(local_run)

cloud_run = make_run(cloud=True, rag=True, voice=True)
cloud_receipt = evaluate_run_capabilities(graph(), cloud_run)
assert cloud_receipt.allowed is True
assert {"cloud", "rag", "voice"}.issubset(cloud_receipt.required_capability_ids)

cloud_blocked = evaluate_run_capabilities(graph(cloud=False), cloud_run)
assert cloud_blocked.allowed is False
assert any(item.capability_id == "cloud" for item in cloud_blocked.blockers)

rag_blocked = evaluate_run_capabilities(graph(rag=False), make_run(rag=True))
assert rag_blocked.allowed is False
assert any(item.capability_id == "rag" for item in rag_blocked.blockers)

voice_blocked = evaluate_run_capabilities(graph(voice=False), make_run(voice=True))
assert voice_blocked.allowed is False
assert any(item.capability_id == "voice" for item in voice_blocked.blockers)

disabled = evaluate_run_capabilities(graph(status_enabled=False), local_run)
assert disabled.allowed is False
assert any(
    item.capability_id == "tool:rig_status" and item.state == "disabled"
    for item in disabled.blockers
)

missing = evaluate_run_capabilities(graph(), make_run(tool="unknown_tool"))
assert missing.allowed is False
assert any(
    item.capability_id == "tool:unknown_tool" and item.state == "missing"
    for item in missing.blockers
)

risk_mismatch = evaluate_run_capabilities(
    graph(),
    make_run(tool="rig_status", risk=RiskClass.WRITE),
)
assert risk_mismatch.allowed is False
assert any("risk" in item.reason for item in risk_mismatch.blockers)

secret_cloud = make_run(cloud=True)
secret_cloud.steps[0].sensitivity = Sensitivity.SECRET
secret_receipt = evaluate_run_capabilities(graph(), secret_cloud)
assert secret_receipt.allowed is False
assert any("secret" in item.reason for item in secret_receipt.blockers)

unavailable = make_run()
unavailable.route = RoutePlan(
    RouteKind.UNAVAILABLE,
    "no route",
    uses_cloud=False,
    uses_rig=False,
    uses_tools=False,
    uses_rag=False,
)
unavailable_receipt = evaluate_run_capabilities(graph(), unavailable)
assert unavailable_receipt.allowed is False
assert any(item.capability_id == "route" for item in unavailable_receipt.blockers)

try:
    evaluate_run_capabilities(
        CapabilityGraph(
            schema="kaliv-agent3-capability-graph/v1",
            nodes=local_graph.nodes,
            edges=local_graph.edges,
            production_activation=True,
        ),
        local_run,
    )
except ValueError as exc:
    assert "activate production" in str(exc)
else:
    raise AssertionError("production-activating graph was accepted")

try:
    evaluate_run_capabilities(
        CapabilityGraph("unsupported", local_graph.nodes, local_graph.edges),
        local_run,
    )
except ValueError as exc:
    assert "schema" in str(exc)
else:
    raise AssertionError("unsupported graph schema was accepted")

print("32 passed, 0 failed")
