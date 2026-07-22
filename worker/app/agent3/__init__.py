"""Experimental Agent 3.0 execution substrate.

Dormant unless KALIV_AGENT3_ENABLED=1. The normal Agent v2 chat path remains the
production default. Package initialization installs the load-bearing Agent 3.0
policy before any orchestrator instance can be constructed.
"""

from . import core as _core
from .policy import Agent3PolicyEngine, install as _install_policy

_install_policy()

# Sensitive-memory migration and rotation are installed at package bootstrap so
# every import path observes the same fail-closed MemoryStore. Both installers
# are idempotent and perform no I/O until a store instance is explicitly opened.
from . import memory as _memory  # noqa: E402
from .memory_migration import install as _install_memory_migration  # noqa: E402
from .memory_rotation import install as _install_memory_rotation  # noqa: E402

_install_memory_migration(_memory.MemoryStore, _memory.MemoryStoreError)
_install_memory_rotation(_memory.MemoryStore)

from .core import *  # noqa: F401,F403,E402

# Make the explicit class discoverable without exposing installer helpers.
__all__ = [name for name in dir(_core) if not name.startswith("_")] + ["Agent3PolicyEngine"]
