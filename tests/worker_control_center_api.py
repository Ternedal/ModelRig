#!/usr/bin/env python3
"""T-044 loopback worker route contracts.

Run: PYTHONPATH=worker python3 tests/worker_control_center_api.py
"""
from __future__ import annotations

import os
import sys

from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "worker"))

from app.control_center_api import build_control_center_router  # noqa: E402

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


async def healthy_health():
    return {
        "checks": {
            "worker": {"ok": True, "version": "1.58.141"},
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


def schedule_history():
    return {
        "schema": "kaliv-control-center-schedule-history/v1",
        "generated_at": NOW,
        "sources": {
            "occurrence_ledger": {"state": "ready", "reason": None},
            "jobs": {"state": "ready", "reason": None},
        },
        "items": [
            {
                "occurrence_id": "0123456789abcdef0123456789abcdef",
                "schedule_id": "0a1b2c3d4e5f",
                "tool": "note_append",
                "due_at": NOW - 20,
                "occurrence_status": "executed",
                "in_flight": False,
                "terminal_outcome": "executed",
                "created_at": NOW - 19,
                "resolved_at": NOW - 18,
                "job_id": "job000000001",
                "job": {
                    "status": "completed",
                    "kind": "schedule",
                    "progress_completed": 1,
                    "progress_total": 1,
                    "created_at": NOW - 19,
                    "updated_at": NOW - 18,
                },
            }
        ],
        "production_activation": False,
    }


def app_for(**kwargs):
    app = FastAPI()
    app.include_router(
        build_control_center_router(
            health_provider=kwargs.get("health_provider", healthy_health),
            agent3_provider=kwargs.get("agent3_provider", disabled_agent3),
            routing_provider=kwargs.get("routing_provider", v2_route),
            schedule_history_provider=kwargs.get("schedule_history_provider", schedule_history),
            loopback_allowed=kwargs.get("loopback_allowed", lambda _request: True),
            clock=lambda: NOW,
        )
    )
    return TestClient(app)


client = app_for()
headers = {
    "X-Kaliv-Backend-Observed-At": str(NOW),
    "X-Kaliv-Backend-Version": "1.58.141",
    "X-Kaliv-Backend-Status": "ok",
}
response = client.get("/control-center/status", headers=headers)
check(response.status_code == 200, "loopback status route succeeds")
payload = response.json()
check(payload["schema"] == "kaliv-control-center-status/v1", "status route returns v1 contract")
check(payload["overall"] == "healthy" and payload["green"], "fresh local stack is green")
check(payload["components"]["backend"]["detail"] == "modelrig-server 1.58.141", "backend stamp is visible")
check(payload["components"]["worker"]["state"] == "healthy", "worker health is mapped")
check(payload["components"]["models"]["state"] == "healthy", "model health is mapped")
check(payload["components"]["agent3"]["state"] == "disabled", "Agent 3 disablement stays explicit")
check(payload["routing"]["active_surface"] == "agent_v2", "normal route remains Agent v2")

# A direct local caller has no authority to claim backend health.
direct = client.get("/control-center/status")
check(direct.status_code == 200, "direct loopback read remains available")
direct_payload = direct.json()
check(direct_payload["components"]["backend"]["state"] == "unknown", "missing backend stamp fails closed")
check(direct_payload["overall"] == "unknown" and not direct_payload["green"], "direct call cannot render green")

# The schedule-history route is independent of backend health stamping: it is
# durable worker-owned truth, but still loopback-only.
history = client.get("/control-center/schedules")
check(history.status_code == 200, "loopback schedule-history route succeeds")
history_payload = history.json()
check(history_payload["schema"] == "kaliv-control-center-schedule-history/v1", "history route returns its versioned contract")
check(history_payload["items"][0]["terminal_outcome"] == "executed", "history returns durable outcome")
check(history_payload["production_activation"] is False, "history route cannot authorize production")

# Both routes remain loopback-only even if the wider worker is intentionally LAN-enabled.
denied_client = app_for(loopback_allowed=lambda _request: False)
denied = denied_client.get("/control-center/status", headers=headers)
check(denied.status_code == 403, "non-loopback status caller is rejected")
denied_history = denied_client.get("/control-center/schedules")
check(denied_history.status_code == 403, "non-loopback history caller is rejected")

# Provider failures reveal type only and keep both affected components unknown.
async def broken_health():
    raise RuntimeError("secret upstream URL and token")

broken = app_for(health_provider=broken_health).get(
    "/control-center/status",
    headers=headers,
)
broken_payload = broken.json()
check(broken.status_code == 200, "provider failure returns structured status")
check(broken_payload["components"]["worker"]["state"] == "unknown", "worker provider failure is unknown")
check(broken_payload["components"]["models"]["state"] == "unknown", "model provider failure is unknown")
serialized = str(broken_payload)
check("provider_error:RuntimeError" in serialized, "provider failure type is retained")
check("secret upstream" not in serialized and "token" not in serialized, "provider message is not leaked")

# Schedule-history provider exceptions are a transport failure; only type escapes.
def broken_history():
    raise RuntimeError("secret schedule args and token")

broken_history = app_for(schedule_history_provider=broken_history).get(
    "/control-center/schedules"
)
check(broken_history.status_code == 503, "history provider exception fails closed")
history_detail = broken_history.json().get("detail", "")
check("RuntimeError" in history_detail, "history exception type is retained")
check("secret schedule" not in history_detail and "token" not in history_detail, "history exception message is redacted")

# Non-object providers cannot smuggle arbitrary response shapes.
bad_history_type = app_for(schedule_history_provider=lambda: ["wrong"]).get(
    "/control-center/schedules"
)
check(bad_history_type.status_code == 503, "non-object history provider fails closed")

# Enabled but unready Agent 3 remains attention without corrupting normal routing.
def unready_agent3():
    return {
        "enabled": True,
        "ok": False,
        "observed_at": NOW,
        "detail": "pilot evidence missing",
    }

unready = app_for(agent3_provider=unready_agent3).get(
    "/control-center/status",
    headers=headers,
).json()
check(unready["components"]["agent3"]["state"] == "unavailable", "unready Agent 3 is unavailable")
check(unready["overall"] == "attention", "optional unready Agent 3 yields attention")
check(unready["routing"]["state"] == "healthy", "normal Agent v2 route stays healthy")

# Bad backend timestamp never becomes a healthy backend observation.
bad_stamp = dict(headers)
bad_stamp["X-Kaliv-Backend-Observed-At"] = "not-a-time"
bad = client.get("/control-center/status", headers=bad_stamp).json()
check(bad["components"]["backend"]["state"] == "unknown", "invalid backend timestamp fails closed")
check(not bad["green"], "invalid backend timestamp blocks green")

print(f"\n===== CONTROL CENTER API: {passed} passed, {failed} failed =====")
raise SystemExit(1 if failed else 0)
