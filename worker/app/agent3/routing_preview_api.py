from __future__ import annotations

from collections.abc import Callable

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field

from .capability_graph import CapabilityGraph
from .capability_graph_api import build_runtime_capability_graph
from .core import CapabilitySnapshot, TurnRequest
from .integration import V2ToolAdapter
from .routing_preview import evaluate_routing_preview


class RoutingPreviewReq(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message: str = Field(min_length=1, max_length=20_000)
    mode: str = Field(default="rig", pattern="^(rig|cloud)$")
    tools: bool = False
    rag: bool = False
    has_image: bool = False
    voice: bool = False
    allow_rag_cloud: bool = False
    auto_cloud_fallback: bool = False


SnapshotProvider = Callable[[], CapabilitySnapshot]
GraphProvider = Callable[[CapabilitySnapshot], CapabilityGraph]


def build_runtime_routing_snapshot(adapter: V2ToolAdapter) -> CapabilitySnapshot:
    """Return the server-owned routing facts used by preview evaluation.

    Cloud and voice remain fail-closed until a future RigGate supplies trusted
    runtime facts. The existing V2 ToolGate is authoritative for tool readiness.
    """

    gate = adapter.tools.GATE
    tools_ready = bool(gate.enabled and not gate.state_error)
    return CapabilitySnapshot(
        rig_reachable=True,
        worker_ready=True,
        tools_ready=tools_ready,
        cloud_ready=False,
        rag_ready=True,
        voice_ready=False,
    )


def build_routing_preview_router(
    adapter: V2ToolAdapter,
    *,
    worker_version: str | None = None,
    snapshot_provider: SnapshotProvider | None = None,
    graph_provider: GraphProvider | None = None,
) -> APIRouter:
    """Expose a side-effect-free preview of future Agent 3.0 routing eligibility."""

    router = APIRouter(
        prefix="/experimental/agent3",
        tags=["experimental-agent3-routing-preview"],
    )
    snapshot_provider = snapshot_provider or (lambda: build_runtime_routing_snapshot(adapter))
    graph_provider = graph_provider or (
        lambda snapshot: build_runtime_capability_graph(
            adapter,
            worker_version=worker_version,
            capabilities=snapshot,
        )
    )

    @router.post("/routing-preview")
    def preview(req: RoutingPreviewReq) -> dict:
        snapshot = snapshot_provider()
        graph = graph_provider(snapshot)
        request = TurnRequest(
            message=req.message,
            mode=req.mode,
            tools=req.tools,
            rag=req.rag,
            has_image=req.has_image,
            voice=req.voice,
            allow_rag_cloud=req.allow_rag_cloud,
            auto_cloud_fallback=req.auto_cloud_fallback,
        )
        payload = evaluate_routing_preview(request, snapshot, graph).to_dict()
        payload["executed"] = False
        payload["planned"] = False
        return payload

    return router
