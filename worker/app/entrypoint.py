"""Production ASGI entrypoint.

Import the FastAPI application, then put the body-limit/temp-cleanup guard
outside it. Run with ``uvicorn app.entrypoint:app``. Tests that need direct
route access may still import ``app.main:app``; process launchers must use this
module so parsing and streaming are guarded at the ASGI boundary.
"""
from .hardening import harden
from .main import app as fastapi_app

app = harden(fastapi_app)
