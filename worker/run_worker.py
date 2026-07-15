"""PyInstaller entrypoint for the RAG worker.

Exists so the worker can ship as a single prebuilt Windows exe (built + smoke-
tested in CI on a real Windows runner) for people who don't want a Python
toolchain on the rig. Imports the app OBJECT statically -- not the
"app.main:app" string form -- so PyInstaller's dependency graph actually sees
fastapi/uvicorn/httpx and bundles them.

Defaults mirror deploy/run-windows.ps1: loopback on 8099 (the worker is only
ever called by the backend on the same machine; it is deliberately NOT
LAN-exposed).
"""
import ipaddress
import os
import sys

import uvicorn

from app.main import app


def _is_loopback(host: str) -> bool:
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return host == "localhost"


def _mount_optional_agent3() -> bool:
    """Mount the dormant Agent 3.0 draft only after explicit operator opt-in.

    Imports stay inside the feature branch so the ordinary worker creates no
    Agent 3.0 databases or routes when KALIV_AGENT3_ENABLED is unset. The import
    statements remain statically visible to PyInstaller, so the release worker
    can be tested on the rig without a separate Python environment.
    """
    if os.getenv("KALIV_AGENT3_ENABLED", "0") != "1":
        return False
    if getattr(app.state, "agent3_planner_mounted", False):
        return True

    from app import paths as app_paths
    from app.agent3.api import mount_agent3
    from app.agent3.integration import V2ToolAdapter
    from app.agent3.memory import MemoryStore
    from app.agent3.memory_api import build_memory_router
    from app.agent3.plan_store import PlanStore
    from app.agent3.planner import build_planner_router

    if not mount_agent3(app):
        return False
    adapter = V2ToolAdapter()
    plan_db = app_paths.resolve("./kaliv-agent3-plans.db", env="KALIV_AGENT3_PLAN_DB")
    memory_db = app_paths.resolve("./kaliv-agent3-memory.db", env="KALIV_AGENT3_MEMORY_DB")
    memory_store = MemoryStore(memory_db)
    app.include_router(
        build_planner_router(
            adapter,
            orchestrator=app.state.agent3_orchestrator,
            plan_store=PlanStore(plan_db),
            memory_store=memory_store,
        )
    )
    app.include_router(build_memory_router(memory_store))
    app.state.agent3_memory_store = memory_store
    app.state.agent3_planner_mounted = True
    return True


if __name__ == "__main__":
    host = os.getenv("MODELRIG_WORKER_HOST", "127.0.0.1")
    # The worker has no auth and is meant to be reached only by the backend on the
    # same machine. Fail fast instead of silently exposing RAG/voice/tools on the
    # LAN. Override with KALIV_WORKER_ALLOW_LAN=1 if that is genuinely intended.
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
