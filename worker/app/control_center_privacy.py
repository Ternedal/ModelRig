"""Read-only privacy/data-sharing truth for T-044 Control Center.

This projection is deliberately narrower than the dormant common data-sharing
ledger. It reports what the active ToolGate does *today* and labels the common
v1 data-sharing layer as dormant instead of pretending that its permissions are
runtime authority.

No database is opened, no permission is created and no environment value is
changed by this module.
"""
from __future__ import annotations

import os
from collections.abc import Callable
from typing import Any

SCHEMA = "kaliv-control-center-privacy/v1"
COMMON_POLICY_SCHEMA = "kaliv-data-sharing-policy/v1"


def _egress_gate_enabled(env_get: Callable[[str, str], str]) -> bool:
    """Mirror the active ToolGate switch without importing ToolGate/AuditLog."""
    return env_get("KALIV_EGRESS_GATE", "").strip().lower() in {"1", "true", "on"}


def build_control_center_privacy(
    *,
    env_get: Callable[[str, str], str] = os.getenv,
) -> dict[str, Any]:
    """Return side-effect-free privacy state from active configuration.

    The private-result rule matches ToolGate's current enforcement boundary:
    when KALIV_EGRESS_GATE is off, private cloud reads remain in the documented
    legacy-open mode; when it is on, private results are blocked pending an
    explicit consent path. Secret results are always forbidden.

    The common data-sharing ledger already models scoped permissions/revocation,
    but it is not imported by an active route/tool/connector. Reporting those
    rows as current permissions would therefore be a lie, so the projection
    exposes that gap explicitly.
    """
    private_gate = _egress_gate_enabled(env_get)
    return {
        "schema": SCHEMA,
        "evidence_state": "ready",
        "tool_result_egress": {
            "source": "toolgate",
            "private_gate_enabled": private_gate,
            "rules": {
                "public": "allowed",
                "operational": "allowed",
                "private": (
                    "blocked_requires_explicit_consent"
                    if private_gate
                    else "allowed_legacy_mode"
                ),
                "secret": "forbidden",
            },
        },
        "common_data_sharing": {
            "schema": COMMON_POLICY_SCHEMA,
            "state": "dormant",
            "runtime_integrated": False,
            "reason": "common_data_sharing_not_runtime_integrated",
        },
        "scoped_permissions": {
            "state": "unavailable",
            "count": None,
            "revocation_supported": False,
            "reason": "no_active_scoped_permission_authority",
        },
        "production_activation": False,
    }
