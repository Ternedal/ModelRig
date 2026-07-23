"""Authoritative production mounting for the integrated dormant Agent 3 surface.

The approval-aware core router comes from the verified T-030/T-032 stack.  This
module composes it with current main's rich planner/memory/capability surface,
then adds the termination and task-readiness receipts.  Process launchers call
only this function; no launcher owns a parallel route list.
"""
from __future__ import annotations

from fastapi import FastAPI

from .. import paths as _paths
from ..build_identity import code_fingerprint
from .api import mount_agent3 as _mount_core
from .cancellation_status import install_termination_contract
from .capability_graph_api import (
    build_capability_graph_router,
    build_runtime_capability_graph,
)
from .capability_receipt_api import build_capability_receipt_router
from .integration import V2ToolAdapter
from .memory import MemoryStore
from .memory_api import build_memory_router
from .outcome_answer_api import build_outcome_answer_router
from .plan_store import PlanStore
from .planner import build_planner_router
from .replan_preview_api import (
    build_default_replan_preview_service,
    build_replan_preview_router,
)
from .task_readiness import (
    build_task_readiness_router,
    evaluate_configured_task_readiness,
)


def mount_agent3(app: FastAPI) -> bool:
    """Mount the entire dormant surface exactly once after explicit opt-in."""
    if not _mount_core(app):
        return False
    if getattr(app.state, "agent3_full_surface_mounted", False):
        return True

    orchestrator = app.state.agent3_orchestrator
    replan_service = app.state.agent3_replanner
    adapter = V2ToolAdapter()
    worker_version = getattr(app, "version", None)

    memory_path = _paths.resolve(
        "./kaliv-agent3-memory.db", env="KALIV_AGENT3_MEMORY_DB"
    )
    plan_path = _paths.resolve(
        "./kaliv-agent3-plans.db", env="KALIV_AGENT3_PLAN_DB"
    )
    memory_store = MemoryStore(str(memory_path))

    def graph_provider():
        return build_runtime_capability_graph(
            adapter,
            worker_version=worker_version,
        )

    def readiness_provider():
        return evaluate_configured_task_readiness(
            current_version=worker_version,
            current_code=code_fingerprint(),
        )

    # The core router owns runs/status/confirmation.  These routers are the
    # non-overlapping production surface that was previously richer only in the
    # development launchers.
    app.include_router(build_memory_router(memory_store))
    app.include_router(
        build_planner_router(
            adapter,
            orchestrator=orchestrator,
            plan_store=PlanStore(str(plan_path)),
            memory_store=memory_store,
            capability_graph_provider=graph_provider,
        )
    )
    replan_preview_service = build_default_replan_preview_service(
        adapter,
        replan_service,
    )
    app.include_router(
        build_replan_preview_router(
            replan_preview_service,
            review_store=orchestrator.review_store,
        )
    )
    app.include_router(build_outcome_answer_router(orchestrator.store))
    app.include_router(
        build_capability_graph_router(
            adapter,
            worker_version=worker_version,
        )
    )
    app.include_router(
        build_capability_receipt_router(
            orchestrator.store,
            graph_provider,
        )
    )
    app.include_router(build_task_readiness_router(readiness_provider))
    install_termination_contract(app)

    app.state.agent3_memory_store = memory_store
    app.state.agent3_replan_preview_service = replan_preview_service
    app.state.agent3_outcome_answer_mounted = True
    app.state.agent3_capability_graph_mounted = True
    app.state.agent3_capability_receipt_mounted = True
    app.state.agent3_task_readiness_mounted = True
    app.state.agent3_full_surface_mounted = True
    return True
