from __future__ import annotations

from fastapi import APIRouter

from .capability_graph import (
    CapabilityGraph,
    build_capability_graph,
    runtime_tool_capabilities,
)
from .core import CapabilitySnapshot
from .integration import V2ToolAdapter
from .validation_gate import evaluate_configured_report


def build_runtime_capability_graph(
    adapter: V2ToolAdapter,
    *,
    worker_version: str | None = None,
    planner_mounted: bool = True,
    memory_mounted: bool = True,
    replanner_mounted: bool = True,
    review_mounted: bool = True,
    capabilities: CapabilitySnapshot | None = None,
) -> CapabilityGraph:
    """Build the server-authoritative local runtime graph used by read-only APIs.

    The default snapshot is deliberately fail-closed for cloud and voice. A future
    RigGate/provider may supply a fresher snapshot, but clients can never declare
    these capabilities ready through this function.
    """

    gate = adapter.tools.GATE
    tools_ready = bool(gate.enabled and not gate.state_error)
    snapshot = capabilities or CapabilitySnapshot(
        rig_reachable=True,
        worker_ready=True,
        tools_ready=tools_ready,
        cloud_ready=False,
        rag_ready=True,
        voice_ready=False,
    )
    # The V2 gate remains authoritative even if a custom infrastructure snapshot
    # accidentally claims tool readiness while the kill switch is off.
    if snapshot.tools_ready != tools_ready:
        snapshot = CapabilitySnapshot(
            rig_reachable=snapshot.rig_reachable,
            worker_ready=snapshot.worker_ready,
            tools_ready=tools_ready,
            cloud_ready=snapshot.cloud_ready,
            rag_ready=snapshot.rag_ready,
            voice_ready=snapshot.voice_ready,
        )
    return build_capability_graph(
        snapshot,
        runtime_tool_capabilities(adapter),
        planner_mounted=planner_mounted,
        memory_mounted=memory_mounted,
        replanner_mounted=replanner_mounted,
        review_mounted=review_mounted,
        validation_assessment=evaluate_configured_report(
            current_version=worker_version
        ),
    )


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
        return build_runtime_capability_graph(
            adapter,
            worker_version=worker_version,
            planner_mounted=planner_mounted,
            memory_mounted=memory_mounted,
            replanner_mounted=replanner_mounted,
            review_mounted=review_mounted,
        ).to_dict()

    return router
