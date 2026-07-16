from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass
from typing import Any

from .capability_graph import CapabilityGraph
from .core import CapabilitySnapshot, RouteKind, TurnRequest, TurnRouter


_AGENT3_CANDIDATE_ROUTES = {
    RouteKind.RIG_TOOLS_LOCAL,
    RouteKind.RIG_TOOLS_CLOUD,
    RouteKind.LOCAL_RAG,
    RouteKind.CLOUD_RAG_VIA_RIG,
}


@dataclass(frozen=True)
class RoutingPreview:
    schema: str
    selected_surface: str
    candidate_surface: str | None
    eligible_for_agent3_preview: bool
    message_sha256: str
    message_characters: int
    route: dict[str, Any]
    required_capabilities: tuple[str, ...]
    blockers: tuple[str, ...]
    warnings: tuple[str, ...]
    proofs: dict[str, Any]
    production_activation: bool = False

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["required_capabilities"] = list(self.required_capabilities)
        payload["blockers"] = list(self.blockers)
        payload["warnings"] = list(self.warnings)
        return payload


def _node_map(graph: CapabilityGraph) -> dict[str, Any]:
    return {node.id: node for node in graph.nodes}


def evaluate_routing_preview(
    request: TurnRequest,
    capabilities: CapabilitySnapshot,
    graph: CapabilityGraph,
) -> RoutingPreview:
    """Evaluate whether a turn could enter the Agent 3.0 developer-preview path.

    This function is deliberately side-effect free. It does not call a model, build
    a plan, create a run, mutate routing or enable production. The actually selected
    surface remains Agent v2 until a separate, explicit integration is delivered.
    """

    route = TurnRouter().route(request, capabilities)
    nodes = _node_map(graph)
    blockers: list[str] = []
    warnings = [
        "normal chat routing is unchanged",
        "routing preview does not plan or execute tools",
    ]

    candidate = bool(request.tools or request.rag) and route.kind in _AGENT3_CANDIDATE_ROUTES
    required: list[str] = []

    if not request.message.strip():
        blockers.append("message is empty")
    if not request.tools and not request.rag:
        blockers.append("plain chat remains on Agent v2")
    if request.has_image:
        blockers.append("image turns are not enabled for Agent 3.0 routing")
    if route.kind == RouteKind.UNAVAILABLE:
        blockers.append(route.reason)
    if route.kind == RouteKind.ASK_BEFORE_DOWNGRADE or route.requires_user_choice:
        blockers.append("route requires an explicit user choice")

    if candidate:
        required.extend(("validation", "planner.local"))
        if route.uses_rig:
            required.extend(("rig", "worker"))
        if route.uses_tools:
            required.append("tool_gate")
        if route.uses_rag:
            required.append("rag")
        if route.uses_cloud:
            required.append("cloud")
        if request.voice:
            required.append("voice")

        for node_id in dict.fromkeys(required):
            node = nodes.get(node_id)
            if node is None:
                blockers.append(f"required capability is missing: {node_id}")
            elif node.state != "ready":
                blockers.append(f"required capability is not ready: {node_id}")

    if graph.production_activation:
        blockers.append("capability graph attempted to activate production")

    validation = nodes.get("validation")
    validation_metadata = dict(getattr(validation, "metadata", {}) or {})
    developer_evidence = bool(
        validation_metadata.get("eligible_for_developer_preview", False)
    )
    write_evidence = bool(validation_metadata.get("eligible_for_write_pilot", False))

    eligible = candidate and not blockers and developer_evidence
    if candidate and not developer_evidence and not any(
        item.endswith("validation") for item in blockers
    ):
        blockers.append("developer-preview evidence is not accepted")
        eligible = False

    message_bytes = request.message.encode("utf-8")
    return RoutingPreview(
        schema="kaliv-agent3-routing-preview/v1",
        selected_surface="agent_v2",
        candidate_surface="agent3_developer_preview" if candidate else None,
        eligible_for_agent3_preview=eligible,
        message_sha256=hashlib.sha256(message_bytes).hexdigest(),
        message_characters=len(request.message),
        route={
            "kind": route.kind.value,
            "reason": route.reason,
            "uses_cloud": route.uses_cloud,
            "uses_rig": route.uses_rig,
            "uses_tools": route.uses_tools,
            "uses_rag": route.uses_rag,
            "requires_user_choice": route.requires_user_choice,
        },
        required_capabilities=tuple(dict.fromkeys(required)),
        blockers=tuple(dict.fromkeys(blockers)),
        warnings=tuple(warnings),
        proofs={
            "developer_preview_evidence": developer_evidence,
            "write_pilot_evidence": write_evidence,
            "capability_graph_schema": graph.schema,
            "capability_graph_production_activation": graph.production_activation,
            "actual_surface_unchanged": True,
        },
        production_activation=False,
    )
