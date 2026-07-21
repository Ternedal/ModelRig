"""Human schedule API: server-issued write approvals and dormant runtime status.

Run: PYTHONPATH=worker python3 tests/worker_schedule_api.py
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
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "worker"))

from app.schedule_admin import ScheduleAdmin, ScheduleAdminStore  # noqa: E402
from app.schedule_api import build_schedule_router  # noqa: E402

passed = failed = 0


def check(cond, msg):
    global passed, failed
    if cond:
        passed += 1
        print(f"  PASS: {msg}")
    else:
        failed += 1
        print(f"  FAIL: {msg}")


class FakeTool:
    def __init__(
        self,
        name,
        risk,
        sensitivity="operational",
        params=None,
        schedulable=False,
        unschedulable_because="",
    ):
        self.name = name
        self.risk = risk
        self.sensitivity = sensitivity
        self.params = params or {"type": "object", "properties": {}}
        self.schedulable = schedulable
        self.unschedulable_because = unschedulable_because or (
            "" if schedulable else "denne fake erklærer sig ikke planlægbar"
        )

    def human_summary(self, args):
        return f"{self.name}: {json.dumps(args, sort_keys=True, ensure_ascii=False)}"


root = tempfile.mkdtemp(prefix="kaliv-schedule-api-")
db_path = os.path.join(root, "schedules.db")
secret = "0123456789abcdef0123456789abcdef-worker-test"
os.environ["KALIV_SCHEDULES_DB"] = db_path
os.environ["KALIV_SCHEDULER_APPROVAL_SECRET"] = secret
now = [1_800_000_000.0]
registry = {
    "read_clock": FakeTool("read_clock", "read", "public", schedulable=True),
    "append_note": FakeTool(
        "append_note",
        "write",
        "private",
        schedulable=True,
        params={
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
        },
    ),
    "click_screen": FakeTool(
        "click_screen",
        "desktop",
        params={
            "type": "object",
            "properties": {"x": {"type": "integer"}},
            "required": ["x"],
        },
    ),
}
admin = ScheduleAdmin(
    store_factory=lambda: ScheduleAdminStore(db_path),
    registry_factory=lambda: registry,
    clock=lambda: now[0],
)
app = FastAPI()
app.include_router(build_schedule_router(admin))
client = TestClient(app)


def token_for(preview, *, issued_at=None, expires_at=None, device_id="phone", nonce=None):
    issued_at = int(time.time()) if issued_at is None else int(issued_at)
    expires_at = issued_at + 120 if expires_at is None else int(expires_at)
    claims = {
        "v": 2,
        "nonce": nonce or base64.urlsafe_b64encode(secrets.token_bytes(32)).decode().rstrip("="),
        "device_id": device_id,
        "operation": preview["operation"],
        "schedule_id": preview["schedule_id"],
        "tool": preview["tool"],
        "args": preview["args"],
        "cadence": preview["cadence"],
        "timezone": preview["timezone"],
        "misfire_policy": preview["misfire_policy"],
        "ttl_days": preview["ttl_days"],
        "max_runs": preview["max_runs"],
        "enable": preview["enable"],
        "action_fingerprint": preview["action_fingerprint"],
        "approval_fingerprint": preview["approval_fingerprint"],
        "issued_at": issued_at,
        "expires_at": expires_at,
    }
    payload = json.dumps(claims, sort_keys=True, separators=(",", ":")).encode()
    payload_part = base64.urlsafe_b64encode(payload).decode().rstrip("=")
    signature = hmac.new(secret.encode(), payload_part.encode(), hashlib.sha256).digest()
    signature_part = base64.urlsafe_b64encode(signature).decode().rstrip("=")
    return f"{payload_part}.{signature_part}"


def create_body(preview, token=None, **changes):
    body = {
        "tool": preview["tool"],
        "args": preview["args"],
        "cadence": preview["cadence"],
        "timezone": preview["timezone"],
        "misfire_policy": preview["misfire_policy"],
        "ttl_days": preview["ttl_days"],
        "max_runs": preview["max_runs"],
    }
    body.update(changes)
    if token is not None:
        body["approval_token"] = token
    return body


old_scheduler = os.environ.pop("KALIV_SCHEDULER", None)
try:
    status = client.get("/schedules/status")
    check(status.status_code == 200, "scheduler status endpoint is available")
    check(
        status.json()
        == {
            "configured": False,
            "running": False,
            "resources_open": False,
            "last_error": None,
        },
        "status tells the truth while the dormant flag is off",
    )
    check(not os.path.exists(db_path), "status does not create the schedule DB")

    preview_resp = client.post(
        "/schedules/preview",
        json={
            "tool": "append_note",
            "args": {"text": "Husk brygdag"},
            "cadence": "every:60",
            "ttl_days": 30,
            "max_runs": 1,
        },
    )
    preview = preview_resp.json()["preview"]
    check(preview_resp.status_code == 200, "write schedule can be previewed")
    check(
        preview["requires_approval"]
        and len(preview["approval_fingerprint"]) == 32
        and len(preview["action_fingerprint"]) == 32,
        "preview still binds exact standing-grant and execution terms",
    )
    check(
        preview_resp.json()["executed"] is False
        and preview_resp.json()["schedule_persisted"] is False
        and not os.path.exists(db_path),
        "preview executes and persists nothing",
    )
    check(
        "Husk brygdag" in preview["human_summary"],
        "preview exposes the exact human-readable action",
    )

    # Validation remains fail-closed independently of the approval ceremony.
    too_fast = client.post(
        "/schedules/preview",
        json={"tool": "read_clock", "args": {}, "cadence": "every:5"},
    )
    too_large = client.post(
        "/schedules/preview",
        json={
            "tool": "append_note",
            "args": {"text": "x" * 21_000},
            "cadence": "every:60",
        },
    )
    wrong_type = client.post(
        "/schedules/preview",
        json={"tool": "append_note", "args": {"text": 42}, "cadence": "every:60"},
    )
    unknown_arg = client.post(
        "/schedules/preview",
        json={
            "tool": "append_note",
            "args": {"text": "ok", "path": "/tmp/escape"},
            "cadence": "every:60",
        },
    )
    check(too_fast.status_code == 422, "busy-loop cadences remain rejected")
    check(too_large.status_code == 422, "oversized arguments remain bounded")
    check(wrong_type.status_code == 422, "tool argument types remain validated")
    check(unknown_arg.status_code == 422, "unknown tool arguments remain rejected")

    missing = client.post("/schedules", json=create_body(preview))
    check(missing.status_code == 409, "write cannot persist without an issued token")
    old_bypass = client.post(
        "/schedules",
        json={**create_body(preview), "approved_fingerprint": preview["approval_fingerprint"]},
    )
    check(
        old_bypass.status_code == 422,
        "the old caller-computable fingerprint field is not part of the API",
    )
    check(not os.path.exists(db_path), "rejected writes create no schedule DB")

    tamper_token = token_for(preview)
    changed_args = client.post(
        "/schedules",
        json=create_body(preview, tamper_token, args={"text": "En anden handling"}),
    )
    changed_cadence = client.post(
        "/schedules",
        json=create_body(preview, tamper_token, cadence="every:3600"),
    )
    changed_horizon = client.post(
        "/schedules",
        json=create_body(preview, tamper_token, ttl_days=31),
    )
    changed_budget = client.post(
        "/schedules",
        json=create_body(preview, tamper_token, max_runs=2),
    )
    check(changed_args.status_code == 409, "changed arguments invalidate the token")
    check(changed_cadence.status_code == 409, "changed cadence invalidates the token")
    check(changed_horizon.status_code == 409, "changed expiry horizon invalidates the token")
    check(changed_budget.status_code == 409, "changed run budget invalidates the token")
    exact_after_tamper = client.post(
        "/schedules", json=create_body(preview, tamper_token)
    )
    check(
        exact_after_tamper.status_code == 200,
        "a mismatch does not consume a token before canonical terms match",
    )
    write_schedule = exact_after_tamper.json()["schedule"]
    write_id = write_schedule["schedule_id"]
    check(
        write_schedule["approved_fingerprint"] == preview["action_fingerprint"]
        and write_schedule["approval_valid"],
        "persisted execution grant remains bound only to immutable action args",
    )
    check(
        exact_after_tamper.json()["executed"] is False
        and write_schedule["structurally_eligible"]
        and write_schedule["runtime_gate_checked"] is False,
        "create persists no execution and reports structural validity honestly",
    )
    check(os.path.exists(db_path), "explicit create persists the schedule DB")

    replay = client.post("/schedules", json=create_body(preview, tamper_token))
    check(replay.status_code == 409, "approval token is durably single-use")

    fresh_preview = client.post(
        "/schedules/preview",
        json={
            "tool": "append_note",
            "args": {"text": "Udløbet"},
            "cadence": "every:60",
            "ttl_days": 30,
            "max_runs": 1,
        },
    ).json()["preview"]
    expired = token_for(
        fresh_preview,
        issued_at=int(time.time()) - 300,
        expires_at=int(time.time()) - 1,
    )
    expired_resp = client.post(
        "/schedules", json=create_body(fresh_preview, expired)
    )
    check(expired_resp.status_code == 409, "expired approval token is refused")

    signed = token_for(fresh_preview)
    payload_part, signature_part = signed.split(".")
    invalid_signature = payload_part + "." + (
        ("A" if signature_part[0] != "A" else "B") + signature_part[1:]
    )
    bad_sig_resp = client.post(
        "/schedules", json=create_body(fresh_preview, invalid_signature)
    )
    check(bad_sig_resp.status_code == 409, "forged token signature is refused")

    read_resp = client.post(
        "/schedules",
        json={
            "tool": "read_clock",
            "args": {},
            "cadence": "every:60",
            "ttl_days": 10,
            "max_runs": 0,
        },
    )
    check(read_resp.status_code == 200, "read schedules still need no write approval")
    read_schedule = read_resp.json()["schedule"]
    check(
        read_schedule["approved_fingerprint"] is None
        and read_schedule["approval_valid"],
        "read schedule stores no fake write approval",
    )

    listed = client.get("/schedules").json()["schedules"]
    check(
        {item["schedule_id"] for item in listed}
        == {write_id, read_schedule["schedule_id"]},
        "list exposes every persisted schedule",
    )
    check(
        client.get(f"/schedules/{write_id}").json()["schedule"]["args"]
        == {"text": "Husk brygdag"},
        "get returns immutable approved arguments",
    )
    check(client.get("/schedules/missing").status_code == 404, "missing schedule is 404")

    desktop = client.post(
        "/schedules/preview",
        json={"tool": "click_screen", "args": {"x": 10}, "cadence": "every:60"},
    )
    unknown = client.post(
        "/schedules/preview",
        json={"tool": "not_registered", "args": {}, "cadence": "every:60"},
    )
    malformed = client.post(
        "/schedules/preview",
        json={"tool": "append_note", "args": {}, "cadence": "every:60"},
    )
    check(desktop.status_code == 422, "desktop actions remain unschedulable")
    check(unknown.status_code == 404, "unknown tools remain rejected")
    check(malformed.status_code == 422, "required tool arguments remain validated")

    original_due = write_schedule["due_at"]
    paused = client.post(f"/schedules/{write_id}/enabled", json={"enabled": False})
    check(paused.status_code == 200 and not paused.json()["schedule"]["enabled"], "operator can pause a schedule")
    now[0] += 3600
    resumed = client.post(f"/schedules/{write_id}/enabled", json={"enabled": True})
    resumed_schedule = resumed.json()["schedule"]
    check(resumed.status_code == 200 and resumed_schedule["enabled"], "operator can resume a valid schedule")
    check(
        resumed_schedule["due_at"] == now[0] + 60
        and resumed_schedule["due_at"] != original_due,
        "resume starts at a fresh future occurrence",
    )
    store = ScheduleAdminStore(db_path)
    # Drive the budget to exhausted directly. Budget is now reserved at claim,
    # not incremented on ran=True (F-902), so simulate the end-state: runs_used
    # at max_runs. The point of this check is that an exhausted schedule cannot
    # be silently re-enabled, regardless of how it got exhausted.
    with store._lock:
        store._conn.execute(
            "UPDATE schedules SET runs_used=max_runs WHERE id=? AND max_runs>0",
            (write_id,))
        store._conn.commit()
    store.set_enabled(write_id, False, now=now[0])
    store.close()
    exhausted = client.post(f"/schedules/{write_id}/enabled", json={"enabled": True})
    check(
        exhausted.status_code == 409 and "budget" in exhausted.json()["detail"],
        "exhausted run budget cannot be silently re-enabled",
    )

    renew_preview_resp = client.post(
        f"/schedules/{write_id}/renew/preview",
        json={"ttl_days": 60, "max_runs": 2, "enable": True},
    )
    renew_preview = renew_preview_resp.json()["preview"]
    renew_token = token_for(renew_preview)
    check(
        renew_preview_resp.status_code == 200
        and renew_preview["operation"] == "renew"
        and renew_preview["schedule_id"] == write_id,
        "renewal gets a separately bound preview",
    )

    missing_renewal = client.post(
        f"/schedules/{write_id}/renew",
        json={"ttl_days": 60, "max_runs": 2, "enable": True},
    )
    check(missing_renewal.status_code == 409, "write renewal requires an issued token")
    create_token_reuse = client.post(
        f"/schedules/{write_id}/renew",
        json={
            "ttl_days": 60,
            "max_runs": 2,
            "enable": True,
            "approval_token": token_for(preview),
        },
    )
    check(create_token_reuse.status_code == 409, "a create token cannot authorize renewal")
    changed_enable = client.post(
        f"/schedules/{write_id}/renew",
        json={
            "ttl_days": 60,
            "max_runs": 2,
            "enable": False,
            "approval_token": renew_token,
        },
    )
    changed_renew_budget = client.post(
        f"/schedules/{write_id}/renew",
        json={
            "ttl_days": 60,
            "max_runs": 3,
            "enable": True,
            "approval_token": renew_token,
        },
    )
    check(changed_enable.status_code == 409, "changed renewal state invalidates token")
    check(changed_renew_budget.status_code == 409, "changed renewal budget invalidates token")

    now[0] += 120
    renewed_resp = client.post(
        f"/schedules/{write_id}/renew",
        json={
            "ttl_days": 60,
            "max_runs": 2,
            "enable": True,
            "approval_token": renew_token,
        },
    )
    renewed = renewed_resp.json()["schedule"]
    check(renewed_resp.status_code == 200, "matching renewal token succeeds")
    check(
        renewed["runs_used"] == 0
        and renewed["max_runs"] == 2
        and renewed["enabled"]
        and renewed["due_at"] == now[0] + 60,
        "renewal resets budget and starts at a fresh future occurrence",
    )
    check(
        renewed["approved_fingerprint"] == preview["action_fingerprint"]
        and renewed["approval_valid"],
        "renewal preserves the immutable action approval",
    )
    renew_replay = client.post(
        f"/schedules/{write_id}/renew",
        json={
            "ttl_days": 60,
            "max_runs": 2,
            "enable": True,
            "approval_token": renew_token,
        },
    )
    check(renew_replay.status_code == 409, "renewal token is also single-use")

    read_renew = client.post(
        f"/schedules/{read_schedule['schedule_id']}/renew",
        json={"ttl_days": 20, "max_runs": 3},
    )
    check(read_renew.status_code == 200, "read renewal invents no write token")

    class FakeRuntime:
        def status(self):
            return SimpleNamespace(
                configured=True,
                running=True,
                resources_open=True,
                last_error=None,
            )

    app.state.scheduler_runtime = FakeRuntime()
    live = client.get("/schedules/status").json()
    check(
        live["configured"] and live["running"] and live["resources_open"],
        "status reports the production-owned runtime when present",
    )
    check(
        client.delete(f"/schedules/{write_id}").status_code == 405,
        "administration surface still has no deletion endpoint",
    )
finally:
    if old_scheduler is not None:
        os.environ["KALIV_SCHEDULER"] = old_scheduler

# --- approval receipts through the REAL token flow (T-014) -------------------
# The store suite proves the bookkeeping with faked receipt dicts. Here the
# receipt's content must come from the ACTUAL verified token: the device_id,
# issued_at and nonce the backend signed are what the detail view shows.

t014_now = int(time.time())
t014_nonce_create = base64.urlsafe_b64encode(
    secrets.token_bytes(32)).decode().rstrip("=")
t014_nonce_renew = base64.urlsafe_b64encode(
    secrets.token_bytes(32)).decode().rstrip("=")
t014_preview = client.post(
    "/schedules/preview",
    json={
        "tool": "append_note",
        "args": {"text": "T-014 receipt-spor"},
        "cadence": "every:60",
        "ttl_days": 30,
        "max_runs": 2,
    },
).json()["preview"]
t014_token = token_for(
    t014_preview,
    device_id="pixel-6a-t014",
    issued_at=t014_now - 5,
    nonce=t014_nonce_create,
)
t014_resp = client.post(
    "/schedules", json=create_body(t014_preview, token=t014_token))
check(t014_resp.status_code == 200,
      "a token-approved write schedule is created")
t014_id = t014_resp.json()["schedule"]["schedule_id"]

detail = client.get(f"/schedules/{t014_id}").json()
receipts = detail.get("approval_receipts")
check(isinstance(receipts, list) and len(receipts) == 1,
      "the detail view exposes exactly one receipt after create")
rc = receipts[0]
check(rc["kind"] == "create"
      and rc["device_id"] == "pixel-6a-t014"
      and rc["issued_at"] == t014_now - 5
      and rc["nonce"] == t014_nonce_create
      and rc["revision"] == 0,
      "the receipt carries the token's OWN device, issue time and nonce -- "
      "attribution comes from the verified token, not from guesswork")
check(rc["consumed_at"] >= rc["issued_at"],
      "consumption follows issuance, as a real approval must")

t014_renew_preview = client.post(
    f"/schedules/{t014_id}/renew/preview",
    json={"ttl_days": 30, "max_runs": 2},
).json()["preview"]
t014_renew_token = token_for(
    t014_renew_preview,
    device_id="desktop-t014",
    issued_at=t014_now + 1,
    nonce=t014_nonce_renew,
)
renew_resp = client.post(
    f"/schedules/{t014_id}/renew",
    json={"ttl_days": 30, "max_runs": 2,
          "approval_token": t014_renew_token},
)
check(renew_resp.status_code == 200, "the same grant can be renewed by token")

detail2 = client.get(f"/schedules/{t014_id}").json()
receipts2 = detail2.get("approval_receipts")
check(len(receipts2) == 2
      and receipts2[0]["kind"] == "create"
      and receipts2[1]["kind"] == "renew",
      "renewal APPENDS its receipt -- the approval history is complete and "
      "ordered")
check(receipts2[1]["device_id"] == "desktop-t014"
      and receipts2[1]["nonce"] == t014_nonce_renew
      and receipts2[1]["revision"] == 1,
      "the renew receipt names the OTHER device and the bumped revision -- "
      "each incarnation of the grant knows exactly who approved it, and when")

print(f"\n===== SCHEDULE API: {passed} passed, {failed} failed =====")
raise SystemExit(1 if failed else 0)
