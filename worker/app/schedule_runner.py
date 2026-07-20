"""Compatibility alias for the integrated scheduler runner.

Install the common audit attempt contract, then expose current main's preserved
implementation as the actual ``app.schedule_runner`` module.  Module-level
safety probes that deliberately patch ``refusal`` therefore observe the same
global object used by ``SchedulerRunner`` methods.
"""
from __future__ import annotations

import sys

from .audit_attempt_contract import install_audit_attempt_contract
from . import schedule_runner_impl as _implementation

install_audit_attempt_contract()
sys.modules[__name__] = _implementation
