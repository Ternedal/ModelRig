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
    uvicorn.run(
        app,
        host=host,
        port=int(os.getenv("MODELRIG_WORKER_PORT", "8099")),
    )
