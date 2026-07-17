"""Experimental worker entrypoint for the isolated Agent 3.0 draft.

Production `/tools/chat` remains unchanged. Run with:

    set KALIV_AGENT3_ENABLED=1
    python worker/run_worker_agent3.py

The worker remains loopback-only by default, exactly like the production entrypoint.
"""

import ipaddress
import os
import sys

import uvicorn
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
# Routers must attach to the FastAPI object; the process must SERVE the
# hardened wrapper around it. entrypoint.py says so in its own docstring --
# "process launchers must use this module" -- and this launcher was born after
# that rule was written and never heard about it, because nothing enforced it.
from app.entrypoint import app as guarded_app
from app.main import app


def _is_loopback(host: str) -> bool:
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return host == "localhost"


if __name__ == "__main__":
    host = os.getenv("MODELRIG_WORKER_HOST", "127.0.0.1")
    if not _is_loopback(host) and os.getenv("KALIV_WORKER_ALLOW_LAN", "0") != "1":
        sys.stderr.write(
            f"refusing to bind worker to non-loopback host {host!r}: the worker has "
            "no auth of its own. Set KALIV_WORKER_ALLOW_LAN=1 to override.\n"
        )
        sys.exit(1)
    if mount_agent3(app):
        adapter = V2ToolAdapter()
        worker_version = getattr(app, "version", None)
        plan_db = app_paths.resolve("./kaliv-agent3-plans.db", env="KALIV_AGENT3_PLAN_DB")
        memory_db = app_paths.resolve("./kaliv-agent3-memory.db", env="KALIV_AGENT3_MEMORY_DB")
        memory_store = MemoryStore(memory_db)
        replan_preview_service = build_default_replan_preview_service(
            adapter,
            app.state.agent3_replanner,
        )

        def graph_provider():
            return build_runtime_capability_graph(
                adapter,
                worker_version=worker_version,
            )

        app.include_router(
            build_planner_router(
                adapter,
                orchestrator=app.state.agent3_orchestrator,
                plan_store=PlanStore(plan_db),
                memory_store=memory_store,
                capability_graph_provider=graph_provider,
            )
        )
        app.include_router(build_memory_router(memory_store))
        app.include_router(
            build_replan_preview_router(
                replan_preview_service,
                review_store=app.state.agent3_read_review_store,
            )
        )
        app.include_router(build_outcome_answer_router(app.state.agent3_orchestrator.store))
        app.include_router(
            build_capability_graph_router(
                adapter,
                worker_version=worker_version,
            )
        )
        app.include_router(
            build_capability_receipt_router(
                app.state.agent3_orchestrator.store,
                graph_provider,
            )
        )
        app.state.agent3_memory_store = memory_store
        app.state.agent3_replan_preview_service = replan_preview_service
        app.state.agent3_outcome_answer_mounted = True
        app.state.agent3_capability_graph_mounted = True
        app.state.agent3_capability_receipt_mounted = True
    else:
        sys.stderr.write(
            "Agent 3.0 was not mounted because KALIV_AGENT3_ENABLED is not 1. "
            "The ordinary worker API will still start.\n"
        )
    # Serve the GUARDED app: same FastAPI routes, with the ASGI body-limit and
    # temp-cleanup guard outside them. Without this, an experimental worker
    # accepts a chunked upload that never declares a Content-Length -- exactly
    # the hole 1.58.46 closed for the production entrypoint.
    uvicorn.run(guarded_app, host=host, port=int(os.getenv("MODELRIG_WORKER_PORT", "8099")))
