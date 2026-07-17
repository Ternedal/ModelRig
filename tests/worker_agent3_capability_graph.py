from __future__ import annotations

from types import SimpleNamespace

from app.agent3.capability_graph import (
    CapabilityNode,
    ToolCapability,
    build_capability_graph,
    runtime_tool_capabilities,
)
from app.agent3.core import CapabilitySnapshot
from app.agent3.integration import V2ToolAdapter


class Tool:
    # impact is what the tool DOES; risk is whether it needs a card (F-614).
    # This double used to declare delete_model as risk="read" and the graph
    # called it DESTRUCTIVE anyway, because a table keyed by tool NAME said so.
    # Right answer, wrong reason -- and the mirror image is the dangerous one: a
    # destructive tool called anything else stayed a read. The name confers
    # nothing now. The declaration does.
    def __init__(self, name, risk, description, impact=None):
        self.name = name
        self.risk = risk
        self.impact = impact or risk
        self.description = description
        self.params = {"type": "object", "properties": {}}


class Gate:
    enabled = True
    state_error = None

    @staticmethod
    def is_enabled(name):
        return name != "note_append"


adapter = V2ToolAdapter(
    SimpleNamespace(
        REGISTRY={
            "rig_status": Tool("rig_status", "read", "Rig status"),
            "note_append": Tool("note_append", "write", "Append note"),
            "delete_model": Tool("delete_model", "write", "Delete model",
                                 impact="destructive"),
            "pull_model": Tool("pull_model", "write", "Pull model", impact="admin"),
        },
        GATE=Gate(),
    )
)
tools = runtime_tool_capabilities(adapter)
assert [tool.name for tool in tools] == [
    "delete_model",
    "note_append",
    "pull_model",
    "rig_status",
]
assert {tool.name: tool.enabled for tool in tools}["note_append"] is False

graph = build_capability_graph(
    CapabilitySnapshot(
        rig_reachable=True,
        worker_ready=True,
        tools_ready=True,
        cloud_ready=False,
        rag_ready=True,
    ),
    tools,
    planner_mounted=True,
    memory_mounted=True,
    replanner_mounted=True,
    review_mounted=True,
    validation_assessment={
        "eligible_for_developer_preview": False,
        "eligible_for_write_pilot": False,
        "blockers": ["physical evidence missing"],
    },
)
payload = graph.to_dict()
assert payload["schema"] == "kaliv-agent3-capability-graph/v1"
assert payload["production_activation"] is False
nodes = {node["id"]: node for node in payload["nodes"]}
assert nodes["rig"]["state"] == "ready"
assert nodes["worker"]["state"] == "ready"
assert nodes["planner.local"]["state"] == "ready"
assert nodes["memory.local"]["state"] == "ready"
assert nodes["replanner.read"]["state"] == "ready"
assert nodes["review.read"]["state"] == "ready"
assert nodes["validation"]["state"] == "blocked"
assert nodes["validation"]["metadata"]["blocker_count"] == 1
assert nodes["production_activation"]["state"] == "blocked"
assert nodes["production_activation"]["metadata"]["value"] is False
assert nodes["tool:rig_status"]["metadata"]["risk"] == "read"
assert nodes["tool:note_append"]["metadata"]["risk"] == "write"
assert nodes["tool:note_append"]["state"] == "disabled"
assert nodes["tool:delete_model"]["metadata"]["risk"] == "destructive"
assert nodes["tool:pull_model"]["metadata"]["risk"] == "admin"

node_ids = set(nodes)
for edge in payload["edges"]:
    assert edge["source"] in node_ids
    assert edge["target"] in node_ids
assert {edge["target"] for edge in payload["edges"] if edge["source"] == "replanner.read"} == {
    "planner.local",
    "tool_gate",
}

eligible = build_capability_graph(
    CapabilitySnapshot(rig_reachable=True, worker_ready=True, tools_ready=True),
    [],
    planner_mounted=True,
    memory_mounted=False,
    replanner_mounted=False,
    review_mounted=False,
    validation_assessment={"eligible_for_developer_preview": True},
).to_dict()
eligible_nodes = {node["id"]: node for node in eligible["nodes"]}
assert eligible_nodes["validation"]["state"] == "ready"
assert eligible_nodes["production_activation"]["state"] == "blocked"
assert eligible["production_activation"] is False

try:
    CapabilityNode("bad", "test", "ready", "bad", {"device_token": "leak"})
except ValueError as exc:
    assert "sensitive" in str(exc)
else:
    raise AssertionError("sensitive metadata key was accepted")

try:
    build_capability_graph(
        CapabilitySnapshot(),
        [
            ToolCapability("duplicate", True, "read"),
            ToolCapability("duplicate", True, "read"),
        ],
        planner_mounted=False,
        memory_mounted=False,
        replanner_mounted=False,
        review_mounted=False,
    )
except ValueError as exc:
    assert "duplicate" in str(exc)
else:
    raise AssertionError("duplicate capability nodes were accepted")

print("31 passed, 0 failed")
