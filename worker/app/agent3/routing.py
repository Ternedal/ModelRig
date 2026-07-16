from __future__ import annotations

from .core import CapabilitySnapshot, RouteKind, RoutePlan, TurnRequest, TurnRouter


class StrictTurnRouter(TurnRouter):
    """Retry router that preserves the complete original turn semantics.

    RouteKind alone is not enough to describe combinations such as RAG + tools,
    so retries use the original request flags together with the persisted route
    kind. The API supplies these fields from the stored run, not from the client.
    """

    def route(self, req: TurnRequest, caps: CapabilitySnapshot) -> RoutePlan:
        if not (req.retry_of_run_id and req.original_route):
            return super().route(req, caps)

        if req.original_route in {RouteKind.UNAVAILABLE, RouteKind.ASK_BEFORE_DOWNGRADE}:
            return self._unavailable("A blocked/user-choice route cannot be retried automatically")

        cloud = req.mode == "cloud"
        tools = req.tools
        rag = req.rag
        rig = (not cloud) or tools or rag

        if cloud and not caps.cloud_ready:
            return self._unavailable("Original cloud route is no longer available")
        if rig and (not caps.rig_reachable or not caps.worker_ready):
            return self._unavailable("Original rig route is no longer available")
        if tools and not caps.tools_ready:
            return self._unavailable("Original tools route is no longer available")
        if rag and not caps.rag_ready:
            return self._unavailable("Original RAG route is no longer available")

        return RoutePlan(
            req.original_route,
            "Retry reuses the stored route, flags and validated plan",
            uses_cloud=cloud,
            uses_rig=rig,
            uses_tools=tools,
            uses_rag=rag,
        )
