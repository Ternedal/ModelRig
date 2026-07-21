#!/usr/bin/env python3
"""T-017 worker HTTP timezone fields and fingerprint binding.

Backend token claim expansion is a later stage. This test proves the worker
accepts, validates and persists explicit time terms, while the already-signed
approval fingerprint prevents a token from being reused with another zone.
This stage changes worker request forwarding only, not the signed claim schema.
Run: PYTHONPATH=worker python3 tests/worker_schedule_api_time.py
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import sys
import tempfile
import time

from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "worker"))

from app.schedule_admin import ScheduleAdmin, ScheduleAdminStore  # noqa: E402
from app.schedule_api import build_schedule_router  # noqa: E402

passed = failed = 0


def check(condition, message):
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS: {message}")
    else:
        failed += 1
        print(f"  FAIL: {message}")


class FakeTool:
    def __init__(self, risk):
        self.risk = risk
        self.sensitivity = "private" if risk == "write" else "public"
        self.schedulable = True
        self.unschedulable_because = ""
        self.params = {
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"] if risk == "write" else [],
        }

    def human_summary(self, args):
        return f"{self.risk}: {json.dumps(args, sort_keys=True)}"


root = tempfile.mkdtemp(prefix="kaliv-t017-api-time-")
db_path = os.path.join(root, "schedules.db")
secret = "0123456789abcdef0123456789abcdef-t017-api"
os.environ["KALIV_SCHEDULES_DB"] = db_path
os.environ["KALIV_SCHEDULER_APPROVAL_SECRET"] = secret
registry = {
    "read_clock": FakeTool("read"),
    "append_note": FakeTool("write"),
}
admin = ScheduleAdmin(
    store_factory=lambda: ScheduleAdminStore(db_path),
    registry_factory=lambda: registry,
)
app = FastAPI()
app.include_router(build_schedule_router(admin))
client = TestClient(app)


def token_for(preview):
    issued_at = int(time.time())
    claims = {
        "v": 1,
        "nonce": base64.urlsafe_b64encode(secrets.token_bytes(32)).decode().rstrip("="),
        "device_id": "pixel-6a-t017-api",
        "operation": preview["operation"],
        "schedule_id": preview["schedule_id"],
        "tool": preview["tool"],
        "args": preview["args"],
        "cadence": preview["cadence"],
        "ttl_days": preview["ttl_days"],
        "max_runs": preview["max_runs"],
        "enable": preview["enable"],
        "action_fingerprint": preview["action_fingerprint"],
        # The v1 envelope has no separate timezone claims, but this signed value
        # is version 2 and already hashes timezone + misfire policy.
        "approval_fingerprint": preview["approval_fingerprint"],
        "issued_at": issued_at,
        "expires_at": issued_at + 120,
    }
    raw = json.dumps(claims, sort_keys=True, separators=(",", ":")).encode()
    payload = base64.urlsafe_b64encode(raw).decode().rstrip("=")
    signature = hmac.new(secret.encode(), payload.encode(), hashlib.sha256).digest()
    return payload + "." + base64.urlsafe_b64encode(signature).decode().rstrip("=")


write_terms = {
    "tool": "append_note",
    "args": {"text": "New York HTTP"},
    "cadence": "daily:02:30",
    "timezone": "America/New_York",
    "misfire_policy": "run_once",
    "ttl_days": 30,
    "max_runs": 3,
}
preview_resp = client.post("/schedules/preview", json=write_terms)
preview = preview_resp.json()["preview"]
check(preview_resp.status_code == 200, "worker previews explicit timezone terms")
check(preview["timezone"] == "America/New_York", "preview returns canonical timezone")
check(preview["misfire_policy"] == "run_once", "preview returns explicit misfire policy")
check("-04:00" in preview["due_at_local"] or "-05:00" in preview["due_at_local"], "preview returns local due time with offset")

token = token_for(preview)
tampered = client.post(
    "/schedules",
    json={
        **write_terms,
        "timezone": "Europe/Copenhagen",
        "approval_token": token,
    },
)
check(tampered.status_code == 409, "signed preview cannot authorize another timezone")
check(not os.path.exists(db_path), "timezone tamper persists no schedule")

created_resp = client.post(
    "/schedules",
    json={**write_terms, "approval_token": token},
)
created = created_resp.json()["schedule"]
check(created_resp.status_code == 200, "matching timezone-bound write persists")
check(created["timezone"] == "America/New_York", "write create persists HTTP timezone")
check(created["due_at_local"] == preview["due_at_local"], "write create preserves previewed local due time")

read_resp = client.post(
    "/schedules",
    json={
        "tool": "read_clock",
        "args": {},
        "cadence": "daily:08:00",
        "timezone": "Asia/Tokyo",
        "misfire_policy": "run_once",
        "ttl_days": 10,
        "max_runs": 0,
    },
)
read_schedule = read_resp.json()["schedule"]
check(read_resp.status_code == 200, "read schedule accepts explicit timezone without write token")
check(read_schedule["timezone"] == "Asia/Tokyo", "read schedule persists HTTP timezone")
check("+09:00" in read_schedule["due_at_local"], "read schedule returns server-authoritative Tokyo time")

listed = client.get("/schedules").json()["schedules"]
check({item["timezone"] for item in listed} == {"America/New_York", "Asia/Tokyo"}, "list preserves each schedule timezone")

bad_zone = client.post(
    "/schedules/preview",
    json={**write_terms, "timezone": "Mars/Olympus_Mons"},
)
bad_policy = client.post(
    "/schedules/preview",
    json={**write_terms, "misfire_policy": "replay_all"},
)
check(bad_zone.status_code == 422, "HTTP preview rejects unknown IANA timezone")
check(bad_policy.status_code == 422, "HTTP preview rejects unsupported misfire policy")

legacy_default = client.post(
    "/schedules/preview",
    json={
        "tool": "read_clock",
        "args": {},
        "cadence": "every:60",
    },
).json()["preview"]
check(legacy_default["timezone"] == "Europe/Copenhagen", "omitted timezone gets explicit compatibility default")
check(legacy_default["misfire_policy"] == "run_once", "omitted policy gets explicit compatibility default")

print(f"\n===== SCHEDULE API TIME: {passed} passed, {failed} failed =====")
raise SystemExit(1 if failed else 0)
