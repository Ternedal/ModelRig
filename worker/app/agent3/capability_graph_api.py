from __future__ import annotations

from fastapi import APIRouter

from .capability_graph import build_capability_graph, runtime_tool_capabilities
from .core import CapabilitySnapshot
from .integration import V2ToolAdapter
from .validation_gate import evaluate_configured_report


def build_capability_graph_router(
    adapter: V2ToolAdapter,
    *,
    worker_version: str | None = None,
    planner_mounted: bool = True,
    memory_mounted: bool = True,
    replanner_mounted: bool = True,
    review_mounted: bool = True,
) -> APIRouter:
    """Expose a read-only runtime graph; it never routes or activates anything."""

    router = APIRouter(prefix="/experimental/agent3", tags=["experimental-agent3-capabilities"])

    @router.get("/capabilities")
    def capabilities() -> dict:
        gate = adapter.tools.GATE
        tools_ready = bool(gate.enabled and not gate.state_error)
        graph = build_capability_graph(
            CapabilitySnapshot(
                rig_reachable=True,
                worker_ready=True,
                tools_ready=tools_ready,
                cloud_ready=False,
                rag_ready=True,
            ),
            runtime_tool_capabilities(adapter),
            planner_mounted=planner_mounted,
            memory_mounted=memory_mounted,
            replanner_mounted=replanner_mounted,
            review_mounted=review_mounted,
            validation_assessment=evaluate_configured_report(
                current_version=worker_version
            ),
        )
        return graph.to_dict()

    return router
