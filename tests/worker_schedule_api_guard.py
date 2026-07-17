"""Schedule administration remains loopback-only under every worker setting.

Run: PYTHONPATH=worker python3 tests/worker_schedule_api_guard.py
"""
from __future__ import annotations

import os
import sys
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "worker"))

from app.schedule_admin import ScheduleAdmin  # noqa: E402
from app.schedule_api import (  # noqa: E402
    _loopback_operator_allowed,
    build_schedule_router,
)

passed = failed = 0


def check(cond, msg):
    global passed, failed
    if cond:
        passed += 1
        print(f"  PASS: {msg}")
    else:
        failed += 1
        print(f"  FAIL: {msg}")


def request_from(host):
    client = None if host is None else SimpleNamespace(host=host)
    return SimpleNamespace(client=client)


check(_loopback_operator_allowed(request_from("127.0.0.1")), "IPv4 loopback is admitted")
check(_loopback_operator_allowed(request_from("::1")), "IPv6 loopback is admitted")
check(_loopback_operator_allowed(request_from("testclient")), "in-process TestClient alias is admitted")
check(not _loopback_operator_allowed(request_from("192.168.1.20")), "LAN peer is refused")
check(not _loopback_operator_allowed(request_from("10.0.0.8")), "private network peer is refused")
check(not _loopback_operator_allowed(request_from(None)), "missing peer identity fails closed")

calls = []


def bomb():
    calls.append("resource")
    raise AssertionError("guarded request must not reach a store or registry")


admin = ScheduleAdmin(
    store_factory=bomb,
    registry_factory=bomb,
)
app = FastAPI()
app.include_router(build_schedule_router(admin, operator_allowed=lambda _request: False))
client = TestClient(app)

old_allow_lan = os.environ.get("KALIV_WORKER_ALLOW_LAN")
os.environ["KALIV_WORKER_ALLOW_LAN"] = "1"
try:
    status = client.get("/schedules/status")
    check(status.status_code == 403, "status is refused to a non-local operator")
    preview = client.post(
        "/schedules/preview",
        json={"tool": "anything", "args": {}, "cadence": "every:60"},
    )
    check(preview.status_code == 403, "schedule writes remain refused even when worker LAN access is enabled")
    check("loopback-only" in preview.json()["detail"], "refusal explains the stronger local-only boundary")
    check(not calls, "admission happens before any registry or SQLite resource is opened")
finally:
    if old_allow_lan is None:
        os.environ.pop("KALIV_WORKER_ALLOW_LAN", None)
    else:
        os.environ["KALIV_WORKER_ALLOW_LAN"] = old_allow_lan

print(f"\n===== SCHEDULE API GUARD: {passed} passed, {failed} failed =====")
raise SystemExit(1 if failed else 0)
