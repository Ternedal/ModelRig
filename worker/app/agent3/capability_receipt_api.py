from __future__ import annotations

from collections.abc import Callable

from fastapi import APIRouter, HTTPException

from .capability_graph import CapabilityGraph
from .capability_receipt import evaluate_run_capabilities
from .core import AgentRunStore


CapabilityGraphProvider = Callable[[], CapabilityGraph]


def build_capability_receipt_router(
    run_store: AgentRunStore,
    graph_provider: CapabilityGraphProvider,
) -> APIRouter:
    """Expose a side-effect-free readiness receipt for an already stored run."""

    router = APIRouter(
        prefix="/experimental/agent3",
        tags=["experimental-agent3-capabilities"],
    )

    @router.get("/runs/{run_id}/capability-receipt")
    def capability_receipt(run_id: str) -> dict:
        run = run_store.load(run_id)
        if run is None:
            raise HTTPException(status_code=404, detail="run not found")
        receipt = evaluate_run_capabilities(graph_provider(), run)
        return {
            "run_id": run.id,
            "run_state": run.state.value,
            "current_step": run.current_step,
            "receipt": receipt.to_dict(),
            "evaluated": True,
            "executed": False,
        }

    return router
