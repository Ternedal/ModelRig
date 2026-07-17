"""Production ASGI entrypoint.

Import the FastAPI application, attach process-owned optional services, then put
the body-limit/temp-cleanup guard outside it. Run with
``uvicorn app.entrypoint:app``. Tests that need direct route access may still
import ``app.main:app``; process launchers must use this module so parsing,
streaming and scheduler lifecycle are guarded at the ASGI boundary.
"""
from .hardening import harden
from .main import app as fastapi_app
from .schedule_runtime import scheduler_lifespan

# The raw route app stays inert for unit tests.  Only the documented production
# entrypoint owns process lifecycle, and the hook itself creates no scheduler
# resources unless KALIV_SCHEDULER is explicitly enabled.
fastapi_app.router.lifespan_context = scheduler_lifespan
app = harden(fastapi_app)
