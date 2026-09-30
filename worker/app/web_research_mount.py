"""Flag guard for the canonical web-research ToolGate surface.

T-034/D7 deliberately chose one production caller: the ``web_research`` tool in
ToolGate. There is no parallel research HTTP endpoint. The surface remains
default-off and is registered only when ``KALIV_WEB_RESEARCH_ENABLED=1``.

Keeping this guard separate from the tool implementation preserves the original
safety property: the outbound caller cannot become reachable merely because its
module is imported.
"""
from __future__ import annotations

import os

from fastapi import FastAPI

WEB_RESEARCH_FLAG = "KALIV_WEB_RESEARCH_ENABLED"
_STATE_ATTR = "web_research_mounted"


def web_research_enabled() -> bool:
    """Return True only for the exact explicit opt-in value ``1``."""
    return os.getenv(WEB_RESEARCH_FLAG, "").strip() == "1"


def mount_web_research(app: FastAPI) -> bool:
    """Register the canonical ToolGate caller exactly once after explicit opt-in.

    The historical ``/research/fetch`` placeholder route is intentionally not
    mounted: D7 selected ToolGate as the single production surface.
    """
    if not web_research_enabled():
        return False
    if getattr(app.state, _STATE_ATTR, False):
        return True

    from .web_research_tool import register_web_research_tool

    register_web_research_tool()
    setattr(app.state, _STATE_ATTR, True)
    return True
