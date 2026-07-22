#!/usr/bin/env python3
"""T-044 first-layer status/freshness contract.

Run: PYTHONPATH=worker python3 tests/worker_control_center_status.py
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "worker"))

from app.control_center_status import (  # noqa: E402
    SCHEMA,
    build_control_center_status,
    collect_control_center_status,
)

passed = failed = 0


def check(condition, message):
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS: {message}")
    else:
        failed += 1
        print(f"  FAIL: {message}")


NOW = 2_000_000_000.0


def component(ok=True, *, age=1.0, enabled=True, detail=None):
    return {
        "ok": ok,
        "enabled": enabled,
        "observed_at": NOW - age,
        "detail": detail,
    }


def healthy_components(agent3=None):
    return {
        "backend": component(detail="backend reachable"),
        "worker": component(detail="worker reachable"),
        "models": component(detail="models loaded"),
        "agent3": agent3 if agent3 is not None else component(enabled=False),
    }


# A deliberately disabled optional surface is truthful and does not make the
# required local stack unhealthy.
status = build_control_center_status(
    healthy_components(),
    {
        "configured_surface": "disabled",
        "active_surface": "agent_v2",
        "observed_at": NOW - 1,
    },
    now=NOW,
)
check(status["schema"] == SCHEMA, "status uses the versioned v1 schema")
check(status["overall"] == "healthy" and status["green"], "fresh required stack is green")
check(status["components"]["agent3"]["state"] == "disabled", "disabled Agent 3 is explicit")
check(not status["components"]["agent3"]["green"], "disabled is never painted green")
check(status["routing"]["state"] == "disabled", "routing reports intentional disablement")

# ok=true without time evidence is not health evidence.
missing_time = healthy_components()
missing_time["worker"] = {"ok": True, "detail": "looks fine"}
status = build_control_center_status(
    missing_time,
    {"configured_surface": "agent_v2", "active_surface": "agent_v2", "observed_at": NOW},
    now=NOW,
)
check(status["components"]["worker"]["state"] == "unknown", "missing timestamp fails closed")
check(status["overall"] == "unknown" and not status["green"], "missing required freshness blocks green")

# A once-green but old source is stale, not green.
stale = healthy_components()
stale["backend"] = component(age=31)
status = build_control_center_status(
    stale,
    {"configured_surface": "agent_v2", "active_surface": "agent_v2", "observed_at": NOW},
    now=NOW,
    freshness_s=30,
)
check(status["components"]["backend"]["state"] == "stale", "old green becomes stale")
check(status["components"]["backend"]["green"] is False, "stale source is never green")
check(status["summary"]["required_failures"] == ["backend"], "required stale source is named")

# Future observations beyond bounded clock skew are unknown.
future = healthy_components()
future["models"] = {"ok": True, "observed_at": NOW + 6}
status = build_control_center_status(
    future,
    {"configured_surface": "agent_v2", "active_surface": "agent_v2", "observed_at": NOW},
    now=NOW,
)
check(status["components"]["models"]["reason"] == "observation_from_future", "future timestamp is rejected")
check(status["overall"] == "unknown", "future required source blocks green")

# Enabled but unready Agent 3 is attention, not a full local-stack outage.
status = build_control_center_status(
    healthy_components(agent3=component(ok=False, enabled=True, detail="pilot not ready")),
    {"configured_surface": "agent_v2", "active_surface": "agent_v2", "observed_at": NOW},
    now=NOW,
)
check(status["components"]["agent3"]["state"] == "unavailable", "enabled unready Agent 3 is unavailable")
check(status["overall"] == "attention", "optional unready surface yields attention")

# Server-selected fallback must say why. Clients may not invent the reason.
status = build_control_center_status(
    healthy_components(agent3=component(ok=False, enabled=True)),
    {
        "configured_surface": "agent3_developer",
        "active_surface": "agent_v2",
        "fallback_reason": "readiness report expired",
        "observed_at": NOW,
    },
    now=NOW,
)
check(status["routing"]["state"] == "fallback", "fresh explained fallback is explicit")
check(status["routing"]["fallback_reason"] == "readiness report expired", "server reason is preserved")
check(status["overall"] == "attention", "fallback is visible as attention")

status = build_control_center_status(
    healthy_components(),
    {
        "configured_surface": "agent3_developer",
        "active_surface": "agent_v2",
        "observed_at": NOW,
    },
    now=NOW,
)
check(status["routing"]["state"] == "unknown", "fallback without reason fails closed")
check(status["routing"]["reason"] == "fallback_reason_missing", "missing reason is machine-readable")
check(not status["green"], "unexplained fallback is never green")

# Provider exceptions expose only their type, not potentially sensitive text.
def broken_provider():
    raise RuntimeError("secret URL and token must not escape")

collected = collect_control_center_status(
    {
        "backend": lambda: component(),
        "worker": broken_provider,
        "models": lambda: component(),
        "agent3": lambda: component(enabled=False),
    },
    lambda: {
        "configured_surface": "disabled",
        "active_surface": "agent_v2",
        "observed_at": NOW,
    },
    now=NOW,
)
worker_detail = collected["components"]["worker"]["detail"] or ""
check("provider_error:RuntimeError" in worker_detail, "provider failure type is visible")
check("secret URL" not in worker_detail and "token" not in worker_detail, "exception message is not leaked")
check(collected["components"]["worker"]["state"] == "unknown", "provider exception is unknown")

# Contract bounds and validation are explicit.
long_detail = "x" * 500
status = build_control_center_status(
    healthy_components(agent3=component(enabled=False, detail=long_detail)),
    {"configured_surface": "disabled", "active_surface": "agent_v2", "observed_at": NOW},
    now=NOW,
)
check(len(status["components"]["agent3"]["detail"]) == 240, "operator detail is bounded")

for bad in (0, -1, 3601, float("inf")):
    error = None
    try:
        build_control_center_status(healthy_components(), None, now=NOW, freshness_s=bad)
    except ValueError as exc:
        error = exc
    check(error is not None, f"invalid freshness {bad!r} is rejected")

print(f"\n===== CONTROL CENTER STATUS: {passed} passed, {failed} failed =====")
raise SystemExit(1 if failed else 0)
