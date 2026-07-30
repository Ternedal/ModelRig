"""Authoritative production mounting for the integrated dormant Agent 3 surface.

The approval-aware core router comes from the verified T-030/T-032 stack. This
module composes it with current main's rich planner/memory/capability surface,
then adds termination, task-readiness and the separately readiness-bound normal
read-only task surface. Process launchers call only this function; no launcher
owns a parallel route list.
"""
from __future__ import annotations

import os

from fastapi import FastAPI

from .. import paths as _paths
from ..build_identity import code_fingerprint
from .api import _mount_agent3_core
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
from .task_surface import TaskExecutionPool, build_task_surface_router


def _task_workers() -> int:
    raw = os.getenv("KALIV_AGENT3_TASK_WORKERS", "2")
    try:
        value = int(raw)
    except ValueError as exc:
        raise RuntimeError("KALIV_AGENT3_TASK_WORKERS must be an integer") from exc
    if value < 1 or value > 8:
        raise RuntimeError("KALIV_AGENT3_TASK_WORKERS must be between 1 and 8")
    return value


def mount_agent3(app: FastAPI) -> bool:
    """Mount the entire dormant surface exactly once after explicit opt-in.

    Sole public owner of the Agent 3 route surface (kontraktpunkt 1, as
    restated by Sol 29/07). All routes here are guarded by
    ``KALIV_AGENT3_ENABLED`` through the core mount; none can alter normal chat
    or claim production activation. ``app.state.agent3_mounted`` is set only
    after the whole composition below has succeeded, so the flag can never mean
    "only the core router was mounted".
    """
    if not _mount_agent3_core(app):
        return False
    if getattr(app.state, "agent3_mounted", False):
        return True

    orchestrator = app.state.agent3_orchestrator
    replan_service = app.state.agent3_replanner
    adapter = V2ToolAdapter()
    runtime_adapter = getattr(orchestrator.executor, "__self__", None)
    if not isinstance(runtime_adapter, V2ToolAdapter):
        raise RuntimeError("Agent 3 runtime executor is not the V2 tool adapter")
    worker_version = getattr(app, "version", None)

    memory_path = _paths.resolve(
        "./kaliv-agent3-memory.db", env="KALIV_AGENT3_MEMORY_DB"
    )
    plan_path = _paths.resolve(
        "./kaliv-agent3-plans.db", env="KALIV_AGENT3_PLAN_DB"
    )
    task_plan_path = _paths.resolve(
        "./kaliv-agent3-task-plans.db", env="KALIV_AGENT3_TASK_PLAN_DB"
    )
    memory_store = MemoryStore(str(memory_path))
    task_plan_store = PlanStore(str(task_plan_path))
    task_execution_pool = TaskExecutionPool(_task_workers())

    def graph_provider():
        return build_runtime_capability_graph(
            adapter,
            worker_version=worker_version,
        )

    def task_graph_provider():
        return build_runtime_capability_graph(
            runtime_adapter,
            worker_version=worker_version,
        )

    def readiness_provider():
        return evaluate_configured_task_readiness(
            current_version=worker_version,
            current_code=code_fingerprint(),
        )

    # The core router owns runs/status/confirmation. These routers are the
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
    app.include_router(
        build_task_surface_router(
            runtime_adapter,
            orchestrator,
            task_plan_store,
            readiness_provider,
            task_execution_pool,
            capability_graph_provider=task_graph_provider,
        )
    )
    install_termination_contract(app)

    app.state.agent3_memory_store = memory_store
    app.state.agent3_replan_preview_service = replan_preview_service
    app.state.agent3_outcome_answer_mounted = True
    app.state.agent3_capability_graph_mounted = True
    app.state.agent3_capability_receipt_mounted = True
    app.state.agent3_task_readiness_mounted = True
    app.state.agent3_task_plan_store = task_plan_store
    app.state.agent3_task_execution_pool = task_execution_pool
    app.state.agent3_task_surface_mounted = True
    # LAST, and only here: the full-surface composition above has succeeded.
    # Per SOL-CLAUDE-SAMARBEJDE.md 29/07 this is the only authoritative key;
    # agent3_full_surface_mounted was retired in the same convergence.
    app.state.agent3_mounted = True
    return True
