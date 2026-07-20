"""Compatibility facade for the integrated scheduler runner.

The implementation is retained byte-for-byte from current main in
``schedule_runner_impl``.  Before exposing it, install the one read-only
AuditLog query that implementation requires.  This keeps the large common
T-030/T-032 tool registry untouched while preserving main's crash-recovery
contract.
"""
from __future__ import annotations

from .audit_attempt_contract import install_audit_attempt_contract

install_audit_attempt_contract()

from .schedule_runner_impl import (  # noqa: E402,F401
    SchedulerRunner,
    TickResult,
    _occurrence_conversation,
)

__all__ = ["SchedulerRunner", "TickResult"]
