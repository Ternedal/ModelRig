"""Production registration boundary for T-035 scoped file capabilities.

No route is added: the capabilities live in the existing ToolGate registry and
therefore reuse the existing authenticated backend/client capability surface.
This mount owns the explicit default-off activation boundary and the audit
redaction required before arbitrary private file text may pass ToolGate.
"""
from __future__ import annotations

import hashlib
import json

from fastapi import FastAPI

from .file_capabilities import (
    RESULT_SCHEMA,
    file_capabilities_enabled,
    register_file_capability_tools,
)

_STATE_ATTR = "file_capabilities_mounted"
_FILE_TOOLS = frozenset({"file_read", "file_list", "file_search"})


def _redact_file_args(args: object) -> dict:
    """Preserve bounded authority metadata, never plaintext search content."""
    if not isinstance(args, dict):
        return {"args": "invalid"}
    redacted = dict(args)
    query = redacted.pop("query", None)
    if isinstance(query, str):
        redacted["query_sha256"] = hashlib.sha256(query.encode("utf-8")).hexdigest()
        redacted["query_length"] = len(query)
    elif query is not None:
        redacted["query"] = "invalid-redacted"
    return redacted


def _redact_file_result(result: object, outcome: str) -> str:
    """Return audit-safe metadata only; malformed output is never copied raw."""
    if outcome != "executed" or not isinstance(result, str):
        return f"file capability {outcome}"
    try:
        payload = json.loads(result)
    except (TypeError, ValueError):
        return "file capability executed; result redacted because it was unparseable"
    if not isinstance(payload, dict) or payload.get("schema") != RESULT_SCHEMA:
        return "file capability executed; result redacted because schema was invalid"
    receipt = payload.get("receipt")
    if not isinstance(receipt, dict):
        return "file capability executed; result redacted because receipt was missing"
    workspace_id = payload.get("workspace_id")
    operation = payload.get("operation")
    summary = receipt.get("result_summary")
    if not all(isinstance(value, str) for value in (workspace_id, operation, summary)):
        return "file capability executed; result redacted because receipt metadata was invalid"
    return f"workspace={workspace_id} operation={operation} {summary}"


class _FileAuditProxy:
    """Delegate the existing append-only audit while redacting T-035 content."""

    def __init__(self, delegate) -> None:
        self._delegate = delegate

    def __getattr__(self, name):
        return getattr(self._delegate, name)

    def record(self, **kwargs) -> None:
        if kwargs.get("tool") in _FILE_TOOLS:
            kwargs = dict(kwargs)
            kwargs["args"] = _redact_file_args(kwargs.get("args"))
            kwargs["result_summary"] = _redact_file_result(
                kwargs.get("result_summary"), str(kwargs.get("outcome") or "unknown")
            )
        self._delegate.record(**kwargs)


def _install_file_audit_redaction() -> None:
    from . import tools

    if isinstance(tools.GATE.audit, _FileAuditProxy):
        return
    tools.GATE.audit = _FileAuditProxy(tools.GATE.audit)


def mount_file_capabilities(app: FastAPI) -> bool:
    if not file_capabilities_enabled():
        return False
    if getattr(app.state, _STATE_ATTR, False):
        return True
    register_file_capability_tools()
    _install_file_audit_redaction()
    setattr(app.state, _STATE_ATTR, True)
    return True
