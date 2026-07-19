"""Production ASGI entrypoint.

Import the FastAPI application, attach process-owned optional services and the
local operator-only schedule API, then put the body-limit/temp-cleanup guard
outside it. Run with ``uvicorn app.entrypoint:app``. Tests that need direct route
access may still import ``app.main:app``; process launchers must use this module
so parsing, streaming and scheduler lifecycle are guarded at the ASGI boundary.
"""
from .agent3.api import mount_agent3
from .hardening import harden
from .main import app as fastapi_app
from .schedule_api import build_schedule_router
from .schedule_runtime import scheduler_lifespan

# Route construction is side-effect free: no schedule/job/audit DB is opened and
# ToolGate is not imported until an operator explicitly calls an admin route.
# There is no model-visible tool for creating schedules.
fastapi_app.include_router(build_schedule_router())

# Agent3 wires through the SAME documented entrypoint the campaign probes.
# Found by the sandbox rehearsal: mount_agent3 existed and was suite-tested by
# direct calls, while nothing this module runs ever called it -- the live
# probe answered 404 with the flag set. The mount self-guards on
# KALIV_AGENT3_ENABLED (default off = untouched app) and is idempotent, so
# the explicit-opt-in contract above still holds.
mount_agent3(fastapi_app)

# The raw route app stays inert for unit tests. Only the documented production
# entrypoint owns process lifecycle, and the hook itself creates no scheduler
# resources unless KALIV_SCHEDULER is explicitly enabled.
fastapi_app.router.lifespan_context = scheduler_lifespan
app = harden(fastapi_app)
