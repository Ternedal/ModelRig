"""Production ASGI entrypoint.

Import the FastAPI application, attach process-owned optional services and the
local operator-only schedule/control-center APIs, then put the body-limit and
temp-cleanup guard outside it. Run with ``uvicorn app.entrypoint:app``. Tests that
need direct route access may still import ``app.main:app``; process launchers must
use this module so parsing, streaming and scheduler lifecycle are guarded at the
ASGI boundary.
"""
import os

from .agent3.cancellation_status import install_termination_contract
from .agent3.production_mount import mount_agent3
from .control_center_api import build_control_center_router
from .file_capabilities_mount import mount_file_capabilities
from .hardening import harden
from .main import app as fastapi_app
from .schedule_api import build_schedule_router
from .web_research_mount import mount_web_research
from .schedule_runtime import scheduler_lifespan

# Route construction is side-effect free: no schedule/job/audit DB is opened and
# ToolGate is not imported until an operator explicitly calls an admin route.
# There is no model-visible tool for creating schedules.
fastapi_app.include_router(build_schedule_router())

# The Control Center status route is read-only and independently loopback-only,
# even when the wider worker has deliberately been made LAN-reachable. It does no
# collection until called and exposes no permission or activation write surface.
fastapi_app.include_router(build_control_center_router())

# Person Profile registry (#752). Route construction opens nothing; the
# store is read on the first call. The route set is the contract: the only
# activation route takes an approved Person Revision -- body, voice and
# personality cannot be switched one at a time through any path here.
from .person_api import build_person_router  # noqa: E402
fastapi_app.include_router(build_person_router())

# Body assets (Unity renderer roadmap, slice A): the active body's validated
# avatar/thumbnail/motions over HTTP for phone and headset clients. Reads
# only through BodyRig's store and current-selection paths; the store is
# opened per request, so mounting touches nothing.
from .body_assets import build_body_router  # noqa: E402
fastapi_app.include_router(build_body_router())

# Live render frames (slice B): /body/state, /body/frames (SSE 20 fps),
# /body/interrupt, /body/state/{name}. The session is created on first
# use for the active body; without one every route answers 404.
from .body_session import build_body_session_router  # noqa: E402
fastapi_app.include_router(build_body_session_router())

# Middleware must be registered before the first ASGI request. It is inert when
# no Agent 3 response exists: it only decorates JSON payloads under the dormant
# /experimental/agent3 prefix and cannot mount or activate a route.
install_termination_contract(fastapi_app)

# Agent 3 wires through the same documented entrypoint the campaign probes. The
# mount self-guards on KALIV_AGENT3_ENABLED (default off) and owns the complete
# production surface; launchers do not add parallel routers.
mount_agent3(fastapi_app)

# Agent 4 remains absent from a standard worker boot, including Python's imported
# module inventory. Exact opt-in imports the production read bootstrap, composes
# only canonical campaign/timeline/evidence read facades from
# KALIV_AGENT4_DATA_ROOT and injects them into the existing GET-only mount. The
# read context constructs no lifecycle scheduler, resource admission, handoff,
# recovery or background-work authority.
if os.getenv("KALIV_AGENT4_OPERATOR_API", "0") == "1":
    from .agent4.production_bootstrap import (
        compose_agent4_operator_context_from_environment,
    )
    from .agent4.production_mount import mount_agent4_operator

    mount_agent4_operator(
        fastapi_app,
        compose_agent4_operator_context_from_environment(),
    )

# Web research and scoped file access are separate opt-in capabilities. Each
# mount owns its own default-off guard. T-035 additionally refuses registration
# unless the trusted workspace is explicit and ToolHost process isolation is on;
# no file route is added here and no absolute path becomes model-controlled.
mount_web_research(fastapi_app)
mount_file_capabilities(fastapi_app)

# The raw route app stays inert for unit tests. Only the documented production
# entrypoint owns process lifecycle, and the hook itself creates no scheduler
# resources unless KALIV_SCHEDULER is explicitly enabled.
fastapi_app.router.lifespan_context = scheduler_lifespan
app = harden(fastapi_app)
