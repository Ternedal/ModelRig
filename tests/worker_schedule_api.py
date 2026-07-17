"""Human schedule API: exact approval binding, renewal and dormant status.

Run: PYTHONPATH=worker python3 tests/worker_schedule_api.py
"""
from __future__ import annotations

import base64
import json
import os
import sys
import tempfile
from types import SimpleNamespace

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "worker"))

from app.schedule_admin import (  # noqa: E402
    APPROVAL_TOKEN_AUDIENCE,
    APPROVAL_TOKEN_PREFIX,
    APPROVAL_TOKEN_VERSION,
    ScheduleAdmin,
    ScheduleAdminStore,
)
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
    # schedulable defaults to False here for the same reason it does in the real
    # registry (F-604): unattended execution is something a tool argues for. A
    # fake that forgets to say so is refused, which is exactly what happened
    # when this fixture met the new gate -- the fail-closed default worked, and
    # the fixture was the thing that had not been told.
    def __init__(self, name, risk, sensitivity="operational", params=None,
                 schedulable=False, unschedulable_because=""):
        self.name = name
        self.risk = risk
        self.sensitivity = sensitivity
        self.params = params or {"type": "object", "properties": {}}
        self.schedulable = schedulable
        self.unschedulable_because = unschedulable_because or (
            "" if schedulable else "denne fake erklærer sig ikke planlægbar")

    def human_summary(self, args):
        return f"{self.name}: {json.dumps(args, sort_keys=True, ensure_ascii=False)}"


def approval_token(binding, *, private_key, now, expires_in=300, nonce="test-nonce-0123456789"):
    claims = {
        "v": APPROVAL_TOKEN_VERSION,
        "aud": APPROVAL_TOKEN_AUDIENCE,
        "binding": binding,
        "exp": int(now + expires_in),
        "nonce": nonce,
    }
    payload = json.dumps(claims, separators=(",", ":")).encode("utf-8")
    signature = private_key.sign(payload)
    enc = lambda raw: base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")
    return f"{APPROVAL_TOKEN_PREFIX}.{enc(payload)}.{enc(signature)}"


private_key = Ed25519PrivateKey.generate()
public_key_b64 = base64.b64encode(
    private_key.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    )
).decode("ascii")


root = tempfile.mkdtemp(prefix="kaliv-schedule-api-")
db_path = os.path.join(root, "schedules.db")
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
    approval_public_key=public_key_b64,
)
app = FastAPI()
app.include_router(build_schedule_router(admin))
client = TestClient(app)

old_scheduler = os.environ.pop("KALIV_SCHEDULER", None)
try:
    # --- status + preview persist no schedules ---------------------------------
    status = client.get("/schedules/status")
    check(status.status_code == 200, "scheduler status endpoint is available")
    check(
        status.json()
        == {
            "configured": False,
            "running": False,
            "resources_open": False,
            "approval_verifier_configured": True,
            "last_error": None,
        },
        "status tells the truth when lifespan is absent and flag is off",
    )
    check(not os.path.exists(db_path), "status does not create the schedule DB")

    no_key_db = os.path.join(root, "no-key-schedules.db")
    no_key_admin = ScheduleAdmin(
        store_factory=lambda: ScheduleAdminStore(no_key_db),
        registry_factory=lambda: registry,
        clock=lambda: now[0],
        approval_public_key="",
    )
    no_key_app = FastAPI()
    no_key_app.include_router(build_schedule_router(no_key_admin))
    no_key_client = TestClient(no_key_app)
    no_key_write = no_key_client.post(
        "/schedules/preview",
        json={
            "tool": "append_note",
            "args": {"text": "Husk brygdag"},
            "cadence": "every:60",
        },
    )
    check(
        no_key_write.status_code == 503,
        "scheduled writes fail closed when the worker has no Ed25519 public key",
    )
    no_key_read = no_key_client.post(
        "/schedules/preview",
        json={"tool": "read_clock", "args": {}, "cadence": "every:60"},
    )
    check(
        no_key_read.status_code == 200,
        "missing approval keys do not invent a requirement for read-only schedules",
    )
    check(
        no_key_client.get("/schedules/status").json()["approval_verifier_configured"] is False,
        "status exposes the missing verifier without opening the database",
    )
    check(not os.path.exists(no_key_db), "missing-key previews create no schedule database")

    preview_resp = client.post(
        "/schedules/preview",
        json={
            "tool": "append_note",
            "args": {"text": "Husk brygdag"},
            "cadence": "every:60",
            "ttl_days": 30,
            "max_runs": 5,
        },
    )
    check(preview_resp.status_code == 200, "write schedule can be previewed")
    preview = preview_resp.json()["preview"]
    approval_binding = preview["approval_binding"]
    approval = approval_token(approval_binding, private_key=private_key, now=now[0])
    action_approval = preview["action_fingerprint"]
    check(
        preview["operation"] == "create"
        and preview["enable"] is True
        and preview["requires_approval"]
        and len(approval_binding) == 64
        and len(action_approval) == 32
        and approval.startswith(APPROVAL_TOKEN_PREFIX + "."),
        "preview exposes a non-authorising binding; the signed token is separate",
    )
    check(
        preview_resp.json()["executed"] is False
        and preview_resp.json()["schedule_persisted"] is False,
        "preview executes no tool and persists no schedule",
    )
    check(
        "Husk brygdag" in preview["human_summary"],
        "preview exposes the exact human-readable action",
    )
    check(not os.path.exists(db_path), "preview does not create the schedule DB")

    # --- invalid or unapprovable schedules fail closed -------------------------
    unknown = client.post(
        "/schedules/preview",
        json={"tool": "not_registered", "args": {}, "cadence": "every:60"},
    )
    check(unknown.status_code == 404, "unknown tools are rejected")
    desktop = client.post(
        "/schedules/preview",
        json={"tool": "click_screen", "args": {"x": 10}, "cadence": "every:60"},
    )
    check(desktop.status_code == 422, "desktop actions can never be scheduled")
    too_fast = client.post(
        "/schedules/preview",
        json={"tool": "read_clock", "args": {}, "cadence": "every:5"},
    )
    check(too_fast.status_code == 422, "busy-loop cadences are rejected")
    too_large = client.post(
        "/schedules/preview",
        json={
            "tool": "append_note",
            "args": {"text": "x" * 21_000},
            "cadence": "every:60",
        },
    )
    check(too_large.status_code == 422, "oversized arguments are bounded")
    missing_arg = client.post(
        "/schedules/preview",
        json={"tool": "append_note", "args": {}, "cadence": "every:60"},
    )
    check(missing_arg.status_code == 422, "required tool arguments are validated")
    wrong_type = client.post(
        "/schedules/preview",
        json={
            "tool": "append_note",
            "args": {"text": 42},
            "cadence": "every:60",
        },
    )
    check(wrong_type.status_code == 422, "tool argument types are validated")
    unknown_arg = client.post(
        "/schedules/preview",
        json={
            "tool": "append_note",
            "args": {"text": "ok", "path": "/tmp/escape"},
            "cadence": "every:60",
        },
    )
    check(unknown_arg.status_code == 422, "unknown tool arguments are rejected")

    missing_approval = client.post(
        "/schedules",
        json={
            "tool": "append_note",
            "args": {"text": "Husk brygdag"},
            "cadence": "every:60",
            "ttl_days": 30,
            "max_runs": 5,
        },
    )
    check(
        missing_approval.status_code == 409,
        "write cannot persist without a signed backend approval token",
    )
    check(not os.path.exists(db_path), "rejected write creates no schedule DB")

    changed_args = client.post(
        "/schedules",
        json={
            "tool": "append_note",
            "args": {"text": "En anden handling"},
            "cadence": "every:60",
            "ttl_days": 30,
            "max_runs": 5,
            "approval_token": approval,
        },
    )
    check(
        changed_args.status_code == 409,
        "changed argument invalidates the old signed standing-grant approval",
    )
    changed_cadence = client.post(
        "/schedules",
        json={
            "tool": "append_note",
            "args": {"text": "Husk brygdag"},
            "cadence": "every:3600",
            "ttl_days": 30,
            "max_runs": 5,
            "approval_token": approval,
        },
    )
    check(
        changed_cadence.status_code == 409,
        "changed cadence invalidates the old approval",
    )
    changed_horizon = client.post(
        "/schedules",
        json={
            "tool": "append_note",
            "args": {"text": "Husk brygdag"},
            "cadence": "every:60",
            "ttl_days": 31,
            "max_runs": 5,
            "approval_token": approval,
        },
    )
    check(
        changed_horizon.status_code == 409,
        "changed expiry horizon invalidates the old approval",
    )
    changed_budget = client.post(
        "/schedules",
        json={
            "tool": "append_note",
            "args": {"text": "Husk brygdag"},
            "cadence": "every:60",
            "ttl_days": 30,
            "max_runs": 6,
            "approval_token": approval,
        },
    )
    check(
        changed_budget.status_code == 409,
        "changed run budget invalidates the old approval",
    )

    # --- exact write + read creation -------------------------------------------
    # Preview the exact final budget rather than stretching the earlier 5-run
    # decision into a 1-run grant under the same approval.
    final_preview = client.post(
        "/schedules/preview",
        json={
            "tool": "append_note",
            "args": {"text": "Husk brygdag"},
            "cadence": "every:60",
            "ttl_days": 30,
            "max_runs": 1,
        },
    ).json()["preview"]
    final_binding = final_preview["approval_binding"]
    final_approval = approval_token(
        final_binding, private_key=private_key, now=now[0], nonce="final-create-0123456789"
    )
    created_resp = client.post(
        "/schedules",
        json={
            "tool": "append_note",
            "args": {"text": "Husk brygdag"},
            "cadence": "every:60",
            "ttl_days": 30,
            "max_runs": 1,
            "approval_token": final_approval,
        },
    )
    check(created_resp.status_code == 200, "exact previewed write can be scheduled")
    write_schedule = created_resp.json()["schedule"]
    write_id = write_schedule["schedule_id"]
    check(created_resp.json()["executed"] is False, "create never executes the action")
    check(
        write_schedule["approved_fingerprint"] == final_preview["action_fingerprint"]
        and write_schedule["approved_fingerprint"] != final_binding,
        "stored execution approval is only the immutable action fingerprint",
    )
    check(
        write_schedule["approval_valid"]
        and write_schedule["structurally_eligible"]
        and write_schedule["runtime_gate_checked"] is False,
        "schedule reports structural validity without pretending ToolGate was checked",
    )
    check(os.path.exists(db_path), "explicit create persists the schedule DB")
    replayed_create = client.post(
        "/schedules",
        json={
            "tool": "append_note",
            "args": {"text": "Husk brygdag"},
            "cadence": "every:60",
            "ttl_days": 30,
            "max_runs": 1,
            "approval_token": final_approval,
        },
    )
    check(replayed_create.status_code == 409, "approval token is single-use")

    read_resp = client.post(
        "/schedules",
        json={
            "tool": "read_clock",
            "args": {},
            "cadence": "every:60",
            "ttl_days": 10,
        },
    )
    check(read_resp.status_code == 200, "read schedules need no write approval")
    read_schedule = read_resp.json()["schedule"]
    check(
        read_schedule["approved_fingerprint"] is None
        and read_schedule["approval_valid"],
        "read schedule stores no fake approval fingerprint",
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
        "get returns the immutable approved arguments",
    )
    check(client.get("/schedules/missing").status_code == 404, "missing is 404")

    # --- pause/resume + exhausted standing grants ------------------------------
    original_due = write_schedule["due_at"]
    paused = client.post(f"/schedules/{write_id}/enabled", json={"enabled": False})
    check(
        paused.status_code == 200 and not paused.json()["schedule"]["enabled"],
        "operator can pause a schedule",
    )
    now[0] += 3600
    resumed = client.post(f"/schedules/{write_id}/enabled", json={"enabled": True})
    resumed_schedule = resumed.json()["schedule"]
    check(
        resumed.status_code == 200 and resumed_schedule["enabled"],
        "operator can resume a still-valid schedule",
    )
    check(
        resumed_schedule["due_at"] == now[0] + 60
        and resumed_schedule["due_at"] != original_due,
        "resume starts at a fresh future occurrence",
    )

    store = ScheduleAdminStore(db_path)
    store.record_claim_result(write_id, ran=True)
    store.set_enabled(write_id, False, now=now[0])
    store.close()
    exhausted = client.post(f"/schedules/{write_id}/enabled", json={"enabled": True})
    check(
        exhausted.status_code == 409 and "budget" in exhausted.json()["detail"],
        "exhausted run budget cannot be silently re-enabled",
    )

    # --- renewal is another full standing-grant approval -----------------------
    renew_preview_resp = client.post(
        f"/schedules/{write_id}/renew/preview",
        json={"ttl_days": 60, "max_runs": 2, "enable": True},
    )
    check(renew_preview_resp.status_code == 200, "renewal has its own preview route")
    renew_preview = renew_preview_resp.json()["preview"]
    renew_binding = renew_preview["approval_binding"]
    renew_approval = approval_token(
        renew_binding, private_key=private_key, now=now[0], nonce="renew-approval-0123456789"
    )
    check(
        renew_preview["operation"] == "renew"
        and renew_preview["schedule_id"] == write_id
        and renew_preview["enable"] is True
        and renew_preview_resp.json()["schedule_persisted"] is False,
        "renewal preview binds schedule id, bounds and enable state without writing",
    )

    missing_renewal = client.post(
        f"/schedules/{write_id}/renew",
        json={"ttl_days": 60, "max_runs": 2, "enable": True},
    )
    check(
        missing_renewal.status_code == 409,
        "renewing a write requires exact renewal approval",
    )
    create_token_reuse = client.post(
        f"/schedules/{write_id}/renew",
        json={
            "ttl_days": 60,
            "max_runs": 2,
            "enable": True,
            "approval_token": final_approval,
        },
    )
    check(
        create_token_reuse.status_code == 409,
        "a create approval cannot be reused as a renewal approval",
    )
    changed_enable = client.post(
        f"/schedules/{write_id}/renew",
        json={
            "ttl_days": 60,
            "max_runs": 2,
            "enable": False,
            "approval_token": renew_approval,
        },
    )
    check(
        changed_enable.status_code == 409,
        "changed renewal enable state invalidates approval",
    )
    changed_renew_budget = client.post(
        f"/schedules/{write_id}/renew",
        json={
            "ttl_days": 60,
            "max_runs": 3,
            "enable": True,
            "approval_token": renew_approval,
        },
    )
    check(
        changed_renew_budget.status_code == 409,
        "changed renewal budget invalidates approval",
    )
    forged = approval_token(
        renew_binding,
        private_key=Ed25519PrivateKey.generate(),
        now=now[0],
        nonce="forged-token-0123456789",
    )
    forged_resp = client.post(
        f"/schedules/{write_id}/renew",
        json={"ttl_days": 60, "max_runs": 2, "enable": True, "approval_token": forged},
    )
    check(forged_resp.status_code == 409, "a different private key cannot mint consent")
    expired = approval_token(
        renew_binding,
        private_key=private_key,
        now=now[0],
        expires_in=-10,
        nonce="expired-token-0123456789",
    )
    expired_resp = client.post(
        f"/schedules/{write_id}/renew",
        json={"ttl_days": 60, "max_runs": 2, "enable": True, "approval_token": expired},
    )
    check(expired_resp.status_code == 409, "expired approval tokens fail closed")

    now[0] += 120
    renewed_resp = client.post(
        f"/schedules/{write_id}/renew",
        json={
            "ttl_days": 60,
            "max_runs": 2,
            "approval_token": renew_approval,
            "enable": True,
        },
    )
    renewed = renewed_resp.json()["schedule"]
    check(renewed_resp.status_code == 200, "matching signed renewal approval succeeds")
    check(
        renewed["runs_used"] == 0 and renewed["max_runs"] == 2,
        "renewal resets consumed budget and installs new bound",
    )
    check(
        renewed["enabled"] and renewed["due_at"] == now[0] + 60,
        "explicit renewal enable starts at fresh future occurrence",
    )
    check(
        renewed["approved_fingerprint"] == action_approval
        and renewed["approval_valid"],
        "renewal persists the same immutable action approval",
    )

    read_renew = client.post(
        f"/schedules/{read_schedule['schedule_id']}/renew",
        json={"ttl_days": 20, "max_runs": 3},
    )
    check(
        read_renew.status_code == 200,
        "read renewal does not invent a write confirmation",
    )

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
        live["configured"] and live["running"] and live["resources_open"]
        and live["approval_verifier_configured"],
        "status reports production-owned runtime when present",
    )
    check(
        client.delete(f"/schedules/{write_id}").status_code == 405,
        "administration surface has no deletion endpoint",
    )
finally:
    if old_scheduler is not None:
        os.environ["KALIV_SCHEDULER"] = old_scheduler

print(f"\n===== SCHEDULE API: {passed} passed, {failed} failed =====")
raise SystemExit(1 if failed else 0)
