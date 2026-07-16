from __future__ import annotations

import hashlib
import json

from app.agent3.capability_graph import (
    CapabilityGraph,
    ToolCapability,
    build_capability_graph,
)
from app.agent3.core import CapabilitySnapshot, TurnRequest
from app.agent3.routing_preview import evaluate_routing_preview


passed = failed = 0


def check(condition, name):
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS: {name}")
    else:
        failed += 1
        print(f"  FAIL: {name}")


def graph(caps, *, developer=True, write=False):
    return build_capability_graph(
        caps,
        [ToolCapability("rig_status", True, "read", "status")],
        planner_mounted=True,
        memory_mounted=True,
        replanner_mounted=True,
        review_mounted=True,
        validation_assessment={
            "eligible_for_developer_preview": developer,
            "eligible_for_write_pilot": write,
            "blockers": [] if developer else ["physical evidence missing"],
        },
    )


ready = CapabilitySnapshot(
    rig_reachable=True,
    worker_ready=True,
    tools_ready=True,
    cloud_ready=False,
    rag_ready=True,
    voice_ready=False,
)

plain = evaluate_routing_preview(TurnRequest("hej", mode="rig"), ready, graph(ready))
check(plain.selected_surface == "agent_v2", "plain chat keeps Agent v2 selected")
check(plain.candidate_surface is None, "plain chat is not an Agent 3.0 candidate")
check(not plain.eligible_for_agent3_preview, "plain chat is not preview eligible")
check("plain chat remains on Agent v2" in plain.blockers, "plain chat explains its blocker")

secret_message = "vis min rig status uden at lække denne tekst"
local_tools = evaluate_routing_preview(
    TurnRequest(secret_message, mode="rig", tools=True),
    ready,
    graph(ready, developer=True, write=True),
)
check(local_tools.candidate_surface == "agent3_developer_preview", "local tools are a preview candidate")
check(local_tools.eligible_for_agent3_preview, "ready local tools qualify for preview")
check(local_tools.route["kind"] == "rig_tools_local", "router kind is preserved")
check(local_tools.required_capabilities == ("validation", "planner.local", "rig", "worker", "tool_gate"), "required capabilities are explicit")
check(local_tools.message_sha256 == hashlib.sha256(secret_message.encode()).hexdigest(), "message is represented by SHA-256")
check(secret_message not in json.dumps(local_tools.to_dict(), ensure_ascii=False), "message text is not echoed")
check(local_tools.production_activation is False, "preview cannot activate production")
check(local_tools.selected_surface == "agent_v2", "eligible preview still does not switch routing")

no_evidence = evaluate_routing_preview(
    TurnRequest("status", mode="rig", tools=True),
    ready,
    graph(ready, developer=False),
)
check(not no_evidence.eligible_for_agent3_preview, "missing physical evidence blocks preview")
check(any("validation" in item or "evidence" in item for item in no_evidence.blockers), "evidence blocker is visible")

no_tools_caps = CapabilitySnapshot(
    rig_reachable=True,
    worker_ready=True,
    tools_ready=False,
    cloud_ready=False,
    rag_ready=True,
    voice_ready=False,
)
no_tools = evaluate_routing_preview(
    TurnRequest("status", mode="rig", tools=True),
    no_tools_caps,
    graph(no_tools_caps),
)
check(no_tools.route["kind"] == "unavailable", "disabled ToolGate makes route unavailable")
check(not no_tools.eligible_for_agent3_preview, "disabled ToolGate fails closed")

image = evaluate_routing_preview(
    TurnRequest("analyse", mode="rig", tools=True, has_image=True),
    ready,
    graph(ready),
)
check(not image.eligible_for_agent3_preview, "image turn is not Agent 3.0 eligible")
check(any("image" in item for item in image.blockers), "image blocker is explicit")

voice = evaluate_routing_preview(
    TurnRequest("status", mode="rig", tools=True, voice=True),
    ready,
    graph(ready),
)
check(not voice.eligible_for_agent3_preview, "unready voice capability blocks preview")
check("voice" in voice.required_capabilities, "voice is listed as required")

rag = evaluate_routing_preview(
    TurnRequest("find dokumenter", mode="rig", rag=True),
    ready,
    graph(ready),
)
check(rag.eligible_for_agent3_preview, "ready local RAG qualifies for preview")
check(rag.route["kind"] == "local_rag", "local RAG route is preserved")
check("rag" in rag.required_capabilities, "RAG requirement is explicit")

cloud_unready = evaluate_routing_preview(
    TurnRequest("status", mode="cloud", tools=True),
    ready,
    graph(ready),
)
check(cloud_unready.route["kind"] == "unavailable", "unready cloud route is unavailable")
check(not cloud_unready.eligible_for_agent3_preview, "unready cloud fails closed")

cloud_ready = CapabilitySnapshot(
    rig_reachable=True,
    worker_ready=True,
    tools_ready=True,
    cloud_ready=True,
    rag_ready=True,
    voice_ready=False,
)
cloud_tools = evaluate_routing_preview(
    TurnRequest("status", mode="cloud", tools=True),
    cloud_ready,
    graph(cloud_ready),
)
check(cloud_tools.eligible_for_agent3_preview, "ready cloud tool route can qualify")
check("cloud" in cloud_tools.required_capabilities, "cloud requirement is explicit")

cloud_rag_no_consent = evaluate_routing_preview(
    TurnRequest("find privat", mode="cloud", rag=True, allow_rag_cloud=False),
    cloud_ready,
    graph(cloud_ready),
)
check(not cloud_rag_no_consent.eligible_for_agent3_preview, "cloud RAG without consent is blocked")
check(any("consent" in item for item in cloud_rag_no_consent.blockers), "cloud RAG consent blocker is visible")

base = graph(ready)
tampered_graph = CapabilityGraph(base.schema, base.nodes, base.edges, production_activation=True)
tampered = evaluate_routing_preview(
    TurnRequest("status", mode="rig", tools=True),
    ready,
    tampered_graph,
)
check(not tampered.eligible_for_agent3_preview, "production activation claim fails closed")
check(tampered.selected_surface == "agent_v2", "tampered graph cannot switch actual surface")
check(tampered.production_activation is False, "response activation remains false")

empty = evaluate_routing_preview(TurnRequest("   ", mode="rig", tools=True), ready, graph(ready))
check(not empty.eligible_for_agent3_preview, "empty message fails closed")
check("message is empty" in empty.blockers, "empty message blocker is visible")

print(f"\n{passed} passed, {failed} failed")
raise SystemExit(1 if failed else 0)
