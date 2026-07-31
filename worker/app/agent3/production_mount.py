"""Authoritative production mounting for the integrated dormant Agent 3 surface.

The approval-aware core router comes from the verified T-030/T-032 stack. This
module composes it with the planner/capability/task surfaces and owns the only
memory-surface selection used by process launchers. There is no implicit
migration and no protected-to-legacy fallback.
"""
from __future__ import annotations

import os
from typing import Any

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
from .memory_surface import ProviderFactory, mount_memory_surface
from .memory_protection import WindowsDpapiMemoryProtectionProvider
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


_RESOURCE_STATE_NAMES = (
    "agent3_task_execution_pool",
    "agent3_plan_store",
    "agent3_task_plan_store",
    "agent3_protected_memory_writer",
    "agent3_protected_memory_reader",
    "agent3_memory_store",
)
_CLEAR_STATE_NAMES = _RESOURCE_STATE_NAMES + (
    "agent3_orchestrator",
    "agent3_replanner",
    "agent3_read_review_store",
    "agent3_protected_memory_grant_db",
    "agent3_replan_preview_service",
)


def _task_workers() -> int:
    raw = os.getenv("KALIV_AGENT3_TASK_WORKERS", "2")
    try:
        value = int(raw)
    except ValueError as exc:
        raise RuntimeError("KALIV_AGENT3_TASK_WORKERS must be an integer") from exc
    if value < 1 or value > 8:
        raise RuntimeError("KALIV_AGENT3_TASK_WORKERS must be between 1 and 8")
    return value


def _close_owned_resource(resource: Any, seen: set[int]) -> None:
    if resource is None or id(resource) in seen:
        return
    seen.add(id(resource))

    shutdown = getattr(resource, "shutdown", None)
    if callable(shutdown):
        shutdown()
        return

    close = getattr(resource, "close", None)
    if callable(close):
        close()
        return

    # AgentRunStore, ReadReviewStore and ReplanJournal predate a public close
    # method but are owned by this composition root. Close their sole persistent
    # SQLite handle here until those stores gain an operation-scoped contract.
    connection = getattr(resource, "_conn", None)
    if connection is not None:
        connection.close()


def close_agent3(app: FastAPI) -> None:
    """Idempotently stop workers and release every resource owned by the mount."""
    if getattr(app.state, "agent3_closing", False):
        return
    app.state.agent3_closing = True
    try:
        seen: set[int] = set()
        for name in _RESOURCE_STATE_NAMES:
            _close_owned_resource(getattr(app.state, name, None), seen)

        replanner = getattr(app.state, "agent3_replanner", None)
        _close_owned_resource(getattr(replanner, "journal", None), seen)

        orchestrator = getattr(app.state, "agent3_orchestrator", None)
        _close_owned_resource(getattr(orchestrator, "review_store", None), seen)
        _close_owned_resource(getattr(orchestrator, "store", None), seen)

        for name in _CLEAR_STATE_NAMES:
            setattr(app.state, name, None)
        app.state.agent3_protected_memory_boundary_installed = False
        app.state.agent3_core_mounted = False
        app.state.agent3_mounted = False
        app.state.agent3_resources_closed = True
    finally:
        app.state.agent3_closing = False


def _rollback_surface(
    app: FastAPI,
    route_count: int,
    middleware_before: list[Any],
) -> None:
    if len(app.router.routes) > route_count:
        del app.router.routes[route_count:]
    app.user_middleware[:] = middleware_before
    app.middleware_stack = None
    app.openapi_schema = None


def mount_agent3(
    app: FastAPI,
    *,
    protected_provider_factory: ProviderFactory = WindowsDpapiMemoryProtectionProvider,
) -> bool:
    """Mount the entire dormant surface exactly once after explicit opt-in.

    Sole public owner of the Agent 3 route surface. All routes remain guarded by
    ``KALIV_AGENT3_ENABLED`` through the core mount. The memory selector accepts
    only empty/``legacy`` or exact ``protected``; a protected failure propagates
    instead of silently instantiating the plaintext store.

    The composition is transactional at the FastAPI boundary: if any store,
    provider, router, middleware or worker-pool step fails, every resource
    created by the attempt is closed and every route or middleware entry added
    by the attempt is removed. ``app.state.agent3_mounted`` is set only after the
    whole composition succeeds.
    """
    if getattr(app.state, "agent3_mounted", False):
        return True
    if getattr(app.state, "agent3_core_mounted", False):
        raise RuntimeError("Agent 3 core-only mount cannot be promoted in place")

    route_count = len(app.router.routes)
    middleware_before = list(app.user_middleware)
    app.state.agent3_resources_closed = False
    try:
        if not _mount_agent3_core(app):
            return False

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
        memory_grant_path = _paths.resolve(
            "./kaliv-agent3-memory-grants.db",
            env="KALIV_AGENT3_MEMORY_GRANT_DB",
        )
        plan_path = _paths.resolve(
            "./kaliv-agent3-plans.db", env="KALIV_AGENT3_PLAN_DB"
        )
        task_plan_path = _paths.resolve(
            "./kaliv-agent3-task-plans.db", env="KALIV_AGENT3_TASK_PLAN_DB"
        )

        memory_surface = mount_memory_surface(
            app,
            memory_path=memory_path,
            grant_db_path=memory_grant_path,
            protected_provider_factory=protected_provider_factory,
        )
        app.state.agent3_memory_store_mode = memory_surface.mode
        app.state.agent3_memory_store = memory_surface.legacy_store
        app.state.agent3_protected_memory_reader = memory_surface.protected_reader
        app.state.agent3_protected_memory_writer = memory_surface.protected_writer
        app.state.agent3_protected_memory_grant_db = memory_surface.grant_db_path
        app.state.agent3_planner_memory_enabled = (
            memory_surface.planner_memory_store is not None
        )

        plan_store = PlanStore(str(plan_path))
        app.state.agent3_plan_store = plan_store
        task_plan_store = PlanStore(str(task_plan_path))
        app.state.agent3_task_plan_store = task_plan_store
        task_execution_pool = TaskExecutionPool(_task_workers())
        app.state.agent3_task_execution_pool = task_execution_pool

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

        app.include_router(
            build_planner_router(
                adapter,
                orchestrator=orchestrator,
                plan_store=plan_store,
                memory_store=memory_surface.planner_memory_store,
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

        app.state.agent3_replan_preview_service = replan_preview_service
        app.state.agent3_outcome_answer_mounted = True
        app.state.agent3_capability_graph_mounted = True
        app.state.agent3_capability_receipt_mounted = True
        app.state.agent3_task_readiness_mounted = True
        app.state.agent3_task_surface_mounted = True
        if not getattr(app.state, "agent3_shutdown_registered", False):
            app.router.add_event_handler("shutdown", lambda: close_agent3(app))
            app.state.agent3_shutdown_registered = True
        # LAST, and only here: the full-surface composition above has succeeded.
        app.state.agent3_mounted = True
        return True
    except Exception:
        close_agent3(app)
        _rollback_surface(app, route_count, middleware_before)
        raise
