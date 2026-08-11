#!/usr/bin/env python3
"""T-044 privacy projection contracts for Control Center.

Run: PYTHONPATH=worker python3 tests/worker_control_center_privacy.py
"""
from __future__ import annotations

import os
import sys

from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "worker"))

from app.control_center_api import build_control_center_router  # noqa: E402
from app.control_center_privacy import build_control_center_privacy  # noqa: E402

passed = failed = 0
NOW = 2_100_000_000.0


def check(condition, message):
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS: {message}")
    else:
        failed += 1
        print(f"  FAIL: {message}")


def env(values):
    return lambda key, default="": values.get(key, default)


# The status must match ToolGate's documented active switch semantics without
# importing ToolGate (which would open the audit DB just to render a read view).
off = build_control_center_privacy(env_get=env({}))
check(off["schema"] == "kaliv-control-center-privacy/v1", "privacy projection is versioned")
check(off["evidence_state"] == "ready", "environment-backed privacy evidence is ready")
check(not off["tool_result_egress"]["private_gate_enabled"], "private egress gate is off by default")
check(
    off["tool_result_egress"]["rules"]["private"] == "allowed_legacy_mode",
    "gate-off mode truthfully exposes legacy private-cloud behaviour",
)
check(
    off["tool_result_egress"]["rules"]["secret"] == "forbidden",
    "secret results remain forbidden regardless of the optional private gate",
)

for value in ("1", "true", "TRUE", "on", " On "):
    enabled = build_control_center_privacy(env_get=env({"KALIV_EGRESS_GATE": value}))
    check(enabled["tool_result_egress"]["private_gate_enabled"], f"{value!r} enables private gate")
    check(
        enabled["tool_result_egress"]["rules"]["private"]
        == "blocked_requires_explicit_consent",
        f"{value!r} reports private cloud data as blocked pending consent",
    )

check(
    off["common_data_sharing"]["state"] == "dormant"
    and off["common_data_sharing"]["runtime_integrated"] is False,
    "dormant common data-sharing is never presented as active authority",
)
check(
    off["scoped_permissions"]["state"] == "unavailable"
    and off["scoped_permissions"]["revocation_supported"] is False,
    "Control Center does not invent revocable scoped permissions before runtime integration",
)
check(off["production_activation"] is False, "privacy projection cannot activate production")


async def healthy_health():
    return {
        "checks": {
            "worker": {"ok": True, "version": "1.58.151"},
            "ollama": {"ok": True, "detail": "HTTP 200"},
        }
    }


def disabled_agent3():
    return {
        "enabled": False,
        "ok": False,
        "observed_at": NOW,
        "detail": "developer surface disabled",
    }


def v2_route():
    return {
        "configured_surface": "agent_v2",
        "active_surface": "agent_v2",
        "observed_at": NOW,
    }


def client_for(privacy_provider):
    app = FastAPI()
    app.include_router(
        build_control_center_router(
            health_provider=healthy_health,
            agent3_provider=disabled_agent3,
            routing_provider=v2_route,
            privacy_provider=privacy_provider,
            loopback_allowed=lambda _request: True,
            clock=lambda: NOW,
        )
    )
    return TestClient(app)


headers = {
    "X-Kaliv-Backend-Observed-At": str(NOW),
    "X-Kaliv-Backend-Version": "1.58.151",
    "X-Kaliv-Backend-Status": "ok",
}

ready = client_for(lambda: off).get("/control-center/status", headers=headers)
check(ready.status_code == 200, "status route remains successful with privacy projection")
ready_body = ready.json()
check(ready_body["schema"] == "kaliv-control-center-status/v1", "parent status schema stays v1")
check(ready_body["privacy"] == off, "status embeds the privacy object without reinterpretation")


def broken_privacy():
    raise RuntimeError("secret privacy path and token")


broken = client_for(broken_privacy).get("/control-center/status", headers=headers)
check(broken.status_code == 200, "privacy provider failure does not erase operational status")
broken_privacy_body = broken.json()["privacy"]
check(broken_privacy_body["evidence_state"] == "unknown", "privacy provider failure fails closed")
check(
    broken_privacy_body["scoped_permissions"]["revocation_supported"] is False,
    "unknown privacy evidence cannot manufacture a revoke control",
)
serialized = str(broken_privacy_body)
check("provider_error:RuntimeError" in serialized, "privacy failure keeps exception type")
check("secret privacy" not in serialized and "token" not in serialized, "privacy failure message is redacted")

bad_type = client_for(lambda: ["not", "an", "object"]).get(
    "/control-center/status",
    headers=headers,
).json()["privacy"]
check(bad_type["evidence_state"] == "unknown", "non-object privacy provider fails closed")
check("provider_error:TypeError" in str(bad_type), "non-object provider is typed as TypeError")

print(f"\n===== CONTROL CENTER PRIVACY: {passed} passed, {failed} failed =====")
raise SystemExit(1 if failed else 0)
