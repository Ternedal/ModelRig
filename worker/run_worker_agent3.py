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

from app.main import app
from app import paths as app_paths
from app.agent3.api import mount_agent3
from app.agent3.integration import V2ToolAdapter
from app.agent3.memory import MemoryStore
from app.agent3.memory_api import build_memory_router
from app.agent3.plan_store import PlanStore
from app.agent3.planner import build_planner_router


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
        plan_db = app_paths.resolve("./kaliv-agent3-plans.db", env="KALIV_AGENT3_PLAN_DB")
        memory_db = app_paths.resolve("./kaliv-agent3-memory.db", env="KALIV_AGENT3_MEMORY_DB")
        memory_store = MemoryStore(memory_db)
        app.include_router(
            build_planner_router(
                adapter,
                orchestrator=app.state.agent3_orchestrator,
                plan_store=PlanStore(plan_db),
            )
        )
        app.include_router(build_memory_router(memory_store))
        app.state.agent3_memory_store = memory_store
    else:
        sys.stderr.write(
            "Agent 3.0 was not mounted because KALIV_AGENT3_ENABLED is not 1. "
            "The ordinary worker API will still start.\n"
        )
    uvicorn.run(app, host=host, port=int(os.getenv("MODELRIG_WORKER_PORT", "8099")))
