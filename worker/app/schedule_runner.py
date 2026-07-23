"""Compatibility alias for the integrated scheduler runner.

Install the common audit attempt contract and the explicit T-018 single-flight
contract, then expose current main's preserved implementation as the actual
``app.schedule_runner`` module. Module-level safety probes that deliberately
patch ``refusal`` therefore observe the same global object used by
``SchedulerRunner`` methods.
"""
from __future__ import annotations

import sys

from .audit_attempt_contract import install_audit_attempt_contract
from . import schedule_runner_impl as _implementation
from .scheduler_single_flight import install_single_flight

install_audit_attempt_contract()
install_single_flight(_implementation.SchedulerRunner, _implementation.TickResult)
sys.modules[__name__] = _implementation
