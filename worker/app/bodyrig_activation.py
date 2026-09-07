"""Single production authority for BodyRig activation.

BodyRig contracts and implementation may be imported and unit-tested while the
production integration remains dormant. Only the exact string ``1`` opts in;
missing, empty, malformed and truthy-looking values all remain off.
"""
from __future__ import annotations

import os

BODYRIG_FLAG = "KALIV_BODYRIG_ENABLED"


def bodyrig_enabled() -> bool:
    """Return True only for explicit production opt-in."""
    # Keep the production authority literal here: scripts/current_state.py
    # derives the rig's switch table from literal environment reads so this
    # default-off boundary cannot silently disappear from generated authority.
    return os.getenv("KALIV_BODYRIG_ENABLED", "0").strip() == "1"
