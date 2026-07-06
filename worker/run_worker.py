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
import os

import uvicorn

from app.main import app

if __name__ == "__main__":
    uvicorn.run(
        app,
        host=os.getenv("MODELRIG_WORKER_HOST", "127.0.0.1"),
        port=int(os.getenv("MODELRIG_WORKER_PORT", "8099")),
    )
