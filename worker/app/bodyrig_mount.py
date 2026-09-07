"""Default-off production mount for the complete BodyRig HTTP surface.

The mount owns its guard, like the other opt-in production surfaces. Entry
points call it unconditionally; a launcher cannot accidentally expose BodyRig
by forgetting a surrounding ``if``. Imports of the body asset/session routers
are lazy so a standard worker boot does not even compose the runtime surface.
"""
from __future__ import annotations

from fastapi import FastAPI

from .bodyrig_activation import bodyrig_enabled

_STATE_ATTR = "bodyrig_mounted"


def mount_bodyrig(app: FastAPI) -> bool:
    """Mount BodyRig assets + live-session routes exactly once after opt-in."""
    if not bodyrig_enabled():
        return False
    if getattr(app.state, _STATE_ATTR, False):
        return True

    from .body_assets import build_body_router
    from .body_session import build_body_session_router

    app.include_router(build_body_router())
    app.include_router(build_body_session_router())
    setattr(app.state, _STATE_ATTR, True)
    return True
