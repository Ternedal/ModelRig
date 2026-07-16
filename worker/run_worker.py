"""PyInstaller entrypoint for the RAG worker.

Exists so the worker can ship as a single prebuilt Windows exe (built + smoke-
tested in CI on a real Windows runner) for people who don't want a Python
toolchain on the rig. Imports the app OBJECT statically -- not the
"app.entrypoint:app" string form -- so PyInstaller's dependency graph actually
sees fastapi/uvicorn/httpx and bundles them.

Defaults mirror deploy/run-windows.ps1: loopback on 8099 (the worker is only
ever called by the backend on the same machine; it is deliberately NOT
LAN-exposed).
"""
import ipaddress
import os
import sys

import uvicorn

# Production must use the outer ASGI guard: it bounds chunked request bodies
# before FastAPI parses them and removes voice temp data after the final stream
# frame. Optional Agent 3.0 routes are mounted on the wrapped FastAPI instance,
# while uvicorn continues to serve this hardened outer app.
from app.entrypoint import app


def _is_loopback(host: str) -> bool:
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return host == "localhost"


def _routing_app():
    """Return the inner FastAPI routing surface behind the hardened ASGI guard."""
    candidate = app
    while not hasattr(candidate, "state") and hasattr(candidate, "app"):
        candidate = candidate.app
    if not hasattr(candidate, "state") or not hasattr(candidate, "include_router"):
        raise RuntimeError("worker app exposes no FastAPI routing surface")
    return candidate


def _mount_optional_agent3() -> bool:
    """Mount the dormant Agent 3.0 draft only after explicit operator opt-in."""
    if os.getenv("KALIV_AGENT3_ENABLED", "0") != "1":
        return False

    routing_app = _routing_app()
    if getattr(routing_app.state, "agent3_planner_mounted", False):
        return True

    from app import paths as app_paths
    from app.agent3.api import mount_agent3
    from app.agent3.capability_graph_api import (
        build_capability_graph_router,
        build_runtime_capability_graph,
    )
    from app.agent3.capability_receipt_api import build_capability_receipt_router
    from app.agent3.integration import V2ToolAdapter
    from app.agent3.memory import MemoryStore
    from app.agent3.memory_api import build_memory_router
    from app.agent3.outcome_answer_api import build_outcome_answer_router
    from app.agent3.plan_store import PlanStore
    from app.agent3.planner import build_planner_router
    from app.agent3.replan_preview_api import (
        build_default_replan_preview_service,
        build_replan_preview_router,
    )

    if not mount_agent3(routing_app):
        return False
    adapter = V2ToolAdapter()
    worker_version = getattr(routing_app, "version", None)
    plan_db = app_paths.resolve("./kaliv-agent3-plans.db", env="KALIV_AGENT3_PLAN_DB")
    memory_db = app_paths.resolve("./kaliv-agent3-memory.db", env="KALIV_AGENT3_MEMORY_DB")
    memory_store = MemoryStore(memory_db)
    replan_preview_service = build_default_replan_preview_service(
        adapter,
        routing_app.state.agent3_replanner,
    )

    def graph_provider():
        return build_runtime_capability_graph(
            adapter,
            worker_version=worker_version,
        )

    routing_app.include_router(
        build_planner_router(
            adapter,
            orchestrator=routing_app.state.agent3_orchestrator,
            plan_store=PlanStore(plan_db),
            memory_store=memory_store,
            capability_graph_provider=graph_provider,
        )
    )
    routing_app.include_router(build_memory_router(memory_store))
    routing_app.include_router(
        build_replan_preview_router(
            replan_preview_service,
            review_store=routing_app.state.agent3_read_review_store,
        )
    )
    routing_app.include_router(
        build_outcome_answer_router(routing_app.state.agent3_orchestrator.store)
    )
    routing_app.include_router(
        build_capability_graph_router(
            adapter,
            worker_version=worker_version,
        )
    )
    routing_app.include_router(
        build_capability_receipt_router(
            routing_app.state.agent3_orchestrator.store,
            graph_provider,
        )
    )
    routing_app.state.agent3_memory_store = memory_store
    routing_app.state.agent3_replan_preview_service = replan_preview_service
    routing_app.state.agent3_outcome_answer_mounted = True
    routing_app.state.agent3_capability_graph_mounted = True
    routing_app.state.agent3_capability_receipt_mounted = True
    routing_app.state.agent3_planner_mounted = True
    return True


if __name__ == "__main__":
    # Isolated tool execution re-invokes this exe with --tool-child (a frozen
    # build has no python -m). This must run before server or Agent 3.0 setup.
    if "--tool-child" in sys.argv:
        from app.tool_child import main as _child_main

        raise SystemExit(_child_main())

    host = os.getenv("MODELRIG_WORKER_HOST", "127.0.0.1")
    if not _is_loopback(host) and os.getenv("KALIV_WORKER_ALLOW_LAN", "0") != "1":
        sys.stderr.write(
            f"refusing to bind worker to non-loopback host {host!r}: the worker has "
            "no auth of its own and should only be reached by the backend on the "
            "same machine. Set KALIV_WORKER_ALLOW_LAN=1 to override.\n"
        )
        sys.exit(1)
    _mount_optional_agent3()
    uvicorn.run(
        app,
        host=host,
        port=int(os.getenv("MODELRIG_WORKER_PORT", "8099")),
    )
