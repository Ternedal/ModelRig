"""Production ASGI entrypoint.

Import the FastAPI application, attach process-owned optional services and the
local operator-only schedule/control-center APIs, then put the body-limit and
temp-cleanup guard outside it. Run with ``uvicorn app.entrypoint:app``. Tests that
need direct route access may still import ``app.main:app``; process launchers must
use this module so parsing, streaming and scheduler lifecycle are guarded at the
ASGI boundary.
"""
from .agent3.cancellation_status import install_termination_contract
from .agent3.production_mount import mount_agent3
from .control_center_api import build_control_center_router
from .hardening import harden
from .main import app as fastapi_app
from .schedule_api import build_schedule_router
from .schedule_runtime import scheduler_lifespan

# Route construction is side-effect free: no schedule/job/audit DB is opened and
# ToolGate is not imported until an operator explicitly calls an admin route.
# There is no model-visible tool for creating schedules.
fastapi_app.include_router(build_schedule_router())

# The Control Center status route is read-only and independently loopback-only,
# even when the wider worker has deliberately been made LAN-reachable. It does no
# collection until called and exposes no permission or activation write surface.
fastapi_app.include_router(build_control_center_router())

# Middleware must be registered before the first ASGI request. It is inert when
# no Agent 3 response exists: it only decorates JSON payloads under the dormant
# /experimental/agent3 prefix and cannot mount or activate a route.
install_termination_contract(fastapi_app)

# Agent 3 wires through the same documented entrypoint the campaign probes. The
# mount self-guards on KALIV_AGENT3_ENABLED (default off) and owns the complete
# production surface; launchers do not add parallel routers.
mount_agent3(fastapi_app)

# The raw route app stays inert for unit tests. Only the documented production
# entrypoint owns process lifecycle, and the hook itself creates no scheduler
# resources unless KALIV_SCHEDULER is explicitly enabled.
fastapi_app.router.lifespan_context = scheduler_lifespan
app = harden(fastapi_app)
