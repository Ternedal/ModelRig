from __future__ import annotations

from types import SimpleNamespace

from app.agent3 import capability_graph as capability_graph_module
from app.agent3.capability_graph import (
    CapabilityNode,
    RuntimeToolCapability,
    build_capability_graph,
    runtime_tool_capabilities,
)
from app.agent3.core import CapabilitySnapshot, RiskClass
from app.agent3.integration import V2ToolAdapter, _V2_RISK
from app.capability_schema import CapabilityDescriptorV2


class Tool:
    # The test double declares the same canonical axes as the real registry. The
    # graph may no longer reconstruct or guess any of them in a parallel model.
    def __init__(
        self,
        name,
        risk,
        description,
        impact=None,
        *,
        network="none",
        network_destinations=(),
    ):
        self.name = name
        self.risk = risk
        self.impact = impact or risk
        self.description = description
        self.params = {"type": "object", "properties": {}}
        self.isolate = False
        self.env_allow = ()
        self.schedulable = self.impact not in {"destructive", "admin"}
        self.unschedulable_because = (
            "requires an attended operator" if not self.schedulable else ""
        )
        self.sensitivity = "operational"
        self.cancellation = "none"
        self.idempotent = self.impact == "read"
        self.network = network
        self.network_destinations = network_destinations


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
            "delete_model": Tool(
                "delete_model",
                "write",
                "Delete model",
                impact="destructive",
                network="configured_service",
                network_destinations=("ollama",),
            ),
            "pull_model": Tool(
                "pull_model",
                "write",
                "Pull model",
                impact="admin",
                network="configured_service",
                network_destinations=("ollama",),
            ),
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
assert all(isinstance(tool, RuntimeToolCapability) for tool in tools)
assert all(isinstance(tool.descriptor, CapabilityDescriptorV2) for tool in tools)
legacy_constructor = capability_graph_module.ToolCapability(
    "legacy_read", True, "read", "legacy compatibility"
)
assert isinstance(legacy_constructor, RuntimeToolCapability)
assert isinstance(legacy_constructor.descriptor, CapabilityDescriptorV2)
assert legacy_constructor.risk == RiskClass.READ
assert not hasattr(legacy_constructor, "declared_risk")
assert {
    tool.name: (tool.descriptor.network.mode, tuple(tool.descriptor.network.destinations))
    for tool in tools
}["delete_model"] == ("configured_service", ("ollama",))

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

# Byte/state parity with the pre-migration graph projection. The descriptor may
# know more (network, scheduling, replay, data class), but graph/v1 must keep the
# exact public metadata/state shape in this slice.
legacy_tool_nodes = {}
for name, tool in sorted(adapter.tools.REGISTRY.items()):
    enabled = adapter.is_enabled(name)
    legacy_tool_nodes[f"tool:{name}"] = {
        "id": f"tool:{name}",
        "kind": "tool",
        "state": "ready" if enabled else "disabled",
        "reason": (
            "enabled by existing V2 ToolGate"
            if enabled
            else "disabled by existing V2 ToolGate"
        ),
        "metadata": {
            "risk": _V2_RISK[tool.impact].value,
            "cancellation": tool.cancellation,
            "description": tool.description[:300],
        },
    }
actual_tool_nodes = {
    node_id: node for node_id, node in nodes.items() if node_id.startswith("tool:")
}
assert actual_tool_nodes == legacy_tool_nodes
assert all(set(node["metadata"]) == {"risk", "cancellation", "description"}
           for node in actual_tool_nodes.values())

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
        [tools[0], tools[0]],
        planner_mounted=False,
        memory_mounted=False,
        replanner_mounted=False,
        review_mounted=False,
    )
except ValueError as exc:
    assert "duplicate" in str(exc)
else:
    raise AssertionError("duplicate capability nodes were accepted")

try:
    RuntimeToolCapability(descriptor=tools[0].descriptor, enabled=1)
except TypeError as exc:
    assert "boolean" in str(exc)
else:
    raise AssertionError("non-boolean runtime enabled state was accepted")

print("42 passed, 0 failed")
