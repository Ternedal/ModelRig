from __future__ import annotations

from fastapi import FastAPI

from .. import paths as _paths
from ..build_identity import code_fingerprint
from .api import mount_agent3 as mount_agent3_runtime
from .capability_graph_api import build_runtime_capability_graph
from .integration import V2ToolAdapter
from .plan_store import PlanStore
from .task_readiness import (
    build_task_readiness_router,
    evaluate_configured_task_readiness,
)
from .task_surface import build_task_surface_router


def mount_agent3(app: FastAPI) -> bool:
    """Mount the complete production Agent 3 surface exactly once.

    The runtime router remains owned by ``api.mount_agent3``. This wrapper adds
    the evidence-only readiness route and the separate readiness-bound, read-only
    task surface used by normal clients. All are guarded by
    ``KALIV_AGENT3_ENABLED`` through the runtime mount; none can alter normal chat
    or claim production activation.
    """
    if not mount_agent3_runtime(app):
        return False
    if getattr(app.state, "agent3_task_surface_mounted", False):
        return True

    worker_version = getattr(app, "version", None)

    def readiness_provider() -> dict:
        return evaluate_configured_task_readiness(
            current_version=worker_version,
            current_code=code_fingerprint(),
        )

    if not getattr(app.state, "agent3_task_readiness_mounted", False):
        app.include_router(build_task_readiness_router(readiness_provider))
        app.state.agent3_task_readiness_mounted = True

    orchestrator = getattr(app.state, "agent3_orchestrator", None)
    if orchestrator is None:
        raise RuntimeError("Agent 3 runtime mounted without an orchestrator")
    # build_default_runtime installs adapter.execute as the orchestrator's bound
    # executor. Resolve that exact adapter rather than construct a second registry
    # boundary whose kill-switch state could diverge from execution.
    adapter = getattr(orchestrator.executor, "__self__", None)
    if not isinstance(adapter, V2ToolAdapter):
        raise RuntimeError("Agent 3 runtime executor is not the V2 tool adapter")

    task_plan_path = _paths.resolve(
        "./kaliv-agent3-task-plans.db",
        env="KALIV_AGENT3_TASK_PLAN_DB",
    )
    task_plan_store = PlanStore(str(task_plan_path))

    def graph_provider():
        return build_runtime_capability_graph(
            adapter,
            worker_version=worker_version,
        )

    app.include_router(
        build_task_surface_router(
            adapter,
            orchestrator,
            task_plan_store,
            readiness_provider,
            capability_graph_provider=graph_provider,
        )
    )
    app.state.agent3_task_plan_store = task_plan_store
    app.state.agent3_task_surface_mounted = True
    return True
