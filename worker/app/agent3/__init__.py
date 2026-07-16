"""Experimental Agent 3.0 execution substrate.

Dormant unless KALIV_AGENT3_ENABLED=1. The normal Agent v2 chat path remains the
production default. Package initialization installs the load-bearing Agent 3.0
policy before any orchestrator instance can be constructed.
"""

from . import core as _core
from .policy import Agent3PolicyEngine, install as _install_policy

_install_policy()

from .core import *  # noqa: F401,F403,E402

# Make the explicit class discoverable without exposing the installer helper.
__all__ = [name for name in dir(_core) if not name.startswith("_")] + ["Agent3PolicyEngine"]
