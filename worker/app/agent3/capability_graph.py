from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Iterable

from .core import CapabilitySnapshot, RiskClass


_ALLOWED_STATES = {"ready", "degraded", "disabled", "unavailable", "blocked"}
_RISK_OVERRIDES = {
    "delete_model": RiskClass.DESTRUCTIVE,
    "pull_model": RiskClass.ADMIN,
}


@dataclass(frozen=True)
class CapabilityNode:
    id: str
    kind: str
    state: str
    reason: str
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.id or len(self.id) > 160:
            raise ValueError("capability node id is invalid")
        if self.state not in _ALLOWED_STATES:
            raise ValueError(f"unsupported capability state: {self.state}")
        for key in self.metadata:
            lowered = key.lower()
            if any(token in lowered for token in ("token", "secret", "password", "credential")):
                raise ValueError(f"sensitive capability metadata key is forbidden: {key}")


@dataclass(frozen=True)
class CapabilityEdge:
    source: str
    target: str
    relation: str = "depends_on"


@dataclass(frozen=True)
class CapabilityGraph:
    schema: str
    nodes: tuple[CapabilityNode, ...]
    edges: tuple[CapabilityEdge, ...]
    production_activation: bool = False

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["nodes"] = [asdict(node) for node in self.nodes]
        payload["edges"] = [asdict(edge) for edge in self.edges]
        return payload


@dataclass(frozen=True)
class ToolCapability:
    name: str
    enabled: bool
    declared_risk: str
    description: str = ""

    @property
    def risk(self) -> RiskClass:
        if self.name in _RISK_OVERRIDES:
            return _RISK_OVERRIDES[self.name]
        # The same downgrade I removed from integration.py in 1.58.66 lived here
        # untouched, because I fixed the file I was looking at and called the
        # finding closed. "WRITE if it says write, else READ" turns a desktop
        # tool into a READ -- in the CAPABILITY GRAPH, which is the thing that
        # tells a planner and a human what an action is. One mapping table, and
        # a class we do not understand stops the graph rather than being guessed
        # into the safest box we have.
        from .integration import _V2_RISK

        risk = _V2_RISK.get(self.declared_risk)
        if risk is None:
            raise ValueError(
                f"ukendt risikoklasse {self.declared_risk!r} for {self.name}: "
                "kapabilitetsgrafen gætter ikke på risiko"
            )
        return risk


def runtime_tool_capabilities(adapter) -> list[ToolCapability]:
    """Read the existing V2 registry/gate without exposing params or credentials."""
    capabilities: list[ToolCapability] = []
    for name, tool in sorted(adapter.tools.REGISTRY.items()):
        capabilities.append(
            ToolCapability(
                name=name,
                enabled=adapter.is_enabled(name),
                declared_risk=str(getattr(tool, "risk", "read")),
                description=str(getattr(tool, "description", ""))[:300],
            )
        )
    return capabilities


def build_capability_graph(
    caps: CapabilitySnapshot,
    tools: Iterable[ToolCapability],
    *,
    planner_mounted: bool,
    memory_mounted: bool,
    replanner_mounted: bool,
    review_mounted: bool,
    validation_assessment: dict[str, Any] | None = None,
) -> CapabilityGraph:
    """Build a read-only graph. It never selects routes or enables capabilities."""

    validation = validation_assessment or {}
    developer_eligible = bool(validation.get("eligible_for_developer_preview", False))
    write_eligible = bool(validation.get("eligible_for_write_pilot", False))
    blockers = validation.get("blockers", validation.get("reasons", []))
    blocker_count = len(blockers) if isinstance(blockers, list) else 0

    nodes: list[CapabilityNode] = [
        CapabilityNode(
            "rig",
            "infrastructure",
            "ready" if caps.rig_reachable else "unavailable",
            "rig reachable" if caps.rig_reachable else "rig is unreachable",
        ),
        CapabilityNode(
            "worker",
            "infrastructure",
            "ready" if caps.worker_ready else "unavailable",
            "worker ready" if caps.worker_ready else "worker is not ready",
        ),
        CapabilityNode(
            "cloud",
            "model_runtime",
            "ready" if caps.cloud_ready else "unavailable",
            "cloud model route ready" if caps.cloud_ready else "cloud model route is unavailable",
        ),
        CapabilityNode(
            "rag",
            "retrieval",
            "ready" if caps.rag_ready and caps.worker_ready else "unavailable",
            "local retrieval ready" if caps.rag_ready else "local retrieval is unavailable",
        ),
        CapabilityNode(
            "voice",
            "input_output",
            "ready" if caps.voice_ready and caps.worker_ready else "unavailable",
            "voice pipeline ready" if caps.voice_ready else "voice pipeline is unavailable",
        ),
        CapabilityNode(
            "tool_gate",
            "security_gate",
            "ready" if caps.tools_ready else "disabled",
            "existing V2 ToolGate is ready" if caps.tools_ready else "tool execution is disabled",
        ),
        CapabilityNode(
            "planner.local",
            "planner",
            "ready" if planner_mounted and caps.worker_ready else "disabled",
            "local plan-only planner mounted" if planner_mounted else "planner is not mounted",
        ),
        CapabilityNode(
            "memory.local",
            "memory",
            "ready" if memory_mounted and caps.worker_ready else "disabled",
            "local Memory 3.0 mounted" if memory_mounted else "memory is not mounted",
        ),
        CapabilityNode(
            "replanner.read",
            "replanner",
            "ready" if replanner_mounted and caps.tools_ready else "disabled",
            "reviewed read replanner mounted" if replanner_mounted else "replanner is not mounted",
        ),
        CapabilityNode(
            "review.read",
            "human_checkpoint",
            "ready" if review_mounted and replanner_mounted else "disabled",
            "persistent read-review checkpoints mounted" if review_mounted else "read review is not mounted",
        ),
        CapabilityNode(
            "validation",
            "promotion_gate",
            "ready" if developer_eligible else "blocked",
            "developer preview evidence accepted" if developer_eligible else "physical evidence gate is not satisfied",
            {
                "eligible_for_developer_preview": developer_eligible,
                "eligible_for_write_pilot": write_eligible,
                "blocker_count": blocker_count,
            },
        ),
        CapabilityNode(
            "production_activation",
            "promotion_gate",
            "blocked",
            "Agent 3.0 draft never activates production automatically",
            {"value": False},
        ),
    ]

    edges: list[CapabilityEdge] = [
        CapabilityEdge("worker", "rig"),
        CapabilityEdge("cloud", "rig"),
        CapabilityEdge("rag", "worker"),
        CapabilityEdge("voice", "worker"),
        CapabilityEdge("tool_gate", "worker"),
        CapabilityEdge("planner.local", "tool_gate"),
        CapabilityEdge("memory.local", "worker"),
        CapabilityEdge("replanner.read", "planner.local"),
        CapabilityEdge("replanner.read", "tool_gate"),
        CapabilityEdge("review.read", "replanner.read"),
        CapabilityEdge("validation", "worker"),
        CapabilityEdge("production_activation", "validation"),
    ]

    for tool in sorted(tools, key=lambda item: item.name):
        node_id = f"tool:{tool.name}"
        nodes.append(
            CapabilityNode(
                node_id,
                "tool",
                "ready" if tool.enabled and caps.tools_ready else "disabled",
                "enabled by existing V2 ToolGate" if tool.enabled else "disabled by existing V2 ToolGate",
                {
                    "risk": tool.risk.value,
                    "description": tool.description,
                },
            )
        )
        edges.append(CapabilityEdge(node_id, "tool_gate"))

    node_ids = [node.id for node in nodes]
    if len(node_ids) != len(set(node_ids)):
        raise ValueError("capability graph contains duplicate node ids")
    known = set(node_ids)
    for edge in edges:
        if edge.source not in known or edge.target not in known:
            raise ValueError("capability graph edge references an unknown node")

    return CapabilityGraph(
        schema="kaliv-agent3-capability-graph/v1",
        nodes=tuple(nodes),
        edges=tuple(edges),
        production_activation=False,
    )
