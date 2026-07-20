"""Experimental worker entrypoint for the isolated Agent 3 draft.

Production ``/tools/chat`` remains unchanged. Run with::

    set KALIV_AGENT3_ENABLED=1
    python worker/run_worker_agent3.py

The process remains loopback-only and serves the same hardened, authoritatively
mounted application as the ordinary worker entrypoint.
"""
import os
import sys

import uvicorn

from app.agent3.production_mount import mount_agent3
from app.entrypoint import app as guarded_app
from app.main import app as routing_app
from app.netguard import enforce_loopback


if __name__ == "__main__":
    host = os.getenv("MODELRIG_WORKER_HOST", "127.0.0.1")
    enforce_loopback(host)
    if not mount_agent3(routing_app):
        sys.stderr.write(
            "Agent 3 was not mounted because KALIV_AGENT3_ENABLED is not 1. "
            "The ordinary worker API will still start.\n"
        )
    uvicorn.run(
        guarded_app,
        host=host,
        port=int(os.getenv("MODELRIG_WORKER_PORT", "8099")),
    )
