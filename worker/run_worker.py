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
import os
import sys

import uvicorn

# Production must use the outer ASGI guard: it bounds chunked request bodies
# before FastAPI parses them and removes voice temp data after the final stream
# frame. Optional Agent 3 routes are mounted on the wrapped FastAPI instance,
# while uvicorn continues to serve this hardened outer app.
from app.netguard import enforce_loopback
from app.entrypoint import app


def _routing_app():
    """Return the inner FastAPI routing surface behind the hardened ASGI guard."""
    candidate = app
    while not hasattr(candidate, "state") and hasattr(candidate, "app"):
        candidate = candidate.app
    if not hasattr(candidate, "state") or not hasattr(candidate, "include_router"):
        raise RuntimeError("worker app exposes no FastAPI routing surface")
    return candidate


def _mount_optional_agent3() -> bool:
    """Mount the complete dormant Agent 3 surface after explicit operator opt-in."""
    if os.getenv("KALIV_AGENT3_ENABLED", "0") != "1":
        return False

    routing_app = _routing_app()
    if getattr(routing_app.state, "agent3_full_surface_mounted", False):
        return True

    from app.agent3.production_mount import mount_agent3

    return bool(mount_agent3(routing_app))


if __name__ == "__main__":
    # Isolated tool execution re-invokes this exe with --tool-child (a frozen
    # build has no python -m). This must run before server or Agent 3 setup.
    if "--tool-child" in sys.argv:
        from app.tool_child import main as _child_main

        raise SystemExit(_child_main())

    host = os.getenv("MODELRIG_WORKER_HOST", "127.0.0.1")
    enforce_loopback(host)
    _mount_optional_agent3()
    uvicorn.run(
        app,
        host=host,
        port=int(os.getenv("MODELRIG_WORKER_PORT", "8099")),
    )
