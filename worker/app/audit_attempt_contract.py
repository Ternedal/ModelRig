"""Install the scheduler's durable attempt-evidence query on the common audit log.

The T-019 scheduler must distinguish "never reached ToolGate" from "ToolGate was
about to run and the process died before the executed receipt".  The common
T-030/T-032 tool registry remains the authority for AuditLog; this narrow
compatibility contract adds only the exact read-only query introduced on main.
"""
from __future__ import annotations

from typing import Any

from . import tools


def _has_attempt(self: tools.AuditLog, conversation_id: str) -> bool:
    """Return whether an attempt marker exists for one exact conversation id."""
    if not isinstance(conversation_id, str) or not conversation_id:
        return False
    with self._lock:
        row = self._conn.execute(
            "SELECT 1 FROM audit WHERE conversation_id=? "
            "AND outcome='attempt' LIMIT 1",
            (conversation_id,),
        ).fetchone()
    return row is not None


def install_audit_attempt_contract() -> None:
    """Attach the exact query once, refusing an incompatible pre-existing API."""
    existing: Any = getattr(tools.AuditLog, "has_attempt", None)
    if existing is not None:
        if not callable(existing):
            raise RuntimeError("AuditLog.has_attempt exists but is not callable")
        return
    setattr(tools.AuditLog, "has_attempt", _has_attempt)
