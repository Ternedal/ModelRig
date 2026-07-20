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
from app.agent3.replan_preview_api import (
    build_default_replan_preview_service,
    build_replan_preview_router,
)
# Routers must attach to the FastAPI object; the process must SERVE the
# hardened wrapper around it. entrypoint.py says so in its own docstring --
# "process launchers must use this module" -- and this launcher was born after
# that rule was written and never heard about it, because nothing enforced it.
from app.netguard import enforce_loopback
from app.entrypoint import app as guarded_app
from app.main import app




if __name__ == "__main__":
    host = os.getenv("MODELRIG_WORKER_HOST", "127.0.0.1")
    enforce_loopback(host)
    # mount_agent3 owns the FULL production surface (rich planner,
    # replan-preview, outcome-answer, capability graph + receipt, memory).
    # The runner adds nothing -- dev serves exactly what production serves.
    if not mount_agent3(app):
        sys.stderr.write(
            "Agent 3.0 was not mounted because KALIV_AGENT3_ENABLED is not 1. "
            "The ordinary worker API will still start.\n"
        )
    # Serve the GUARDED app: same FastAPI routes, with the ASGI body-limit and
    # temp-cleanup guard outside them. Without this, an experimental worker
    # accepts a chunked upload that never declares a Content-Length -- exactly
    # the hole 1.58.46 closed for the production entrypoint.
    uvicorn.run(guarded_app, host=host, port=int(os.getenv("MODELRIG_WORKER_PORT", "8099")))
