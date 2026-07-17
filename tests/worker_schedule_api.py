"""Human schedule API: exact approval binding, renewal and dormant status.

Run: PYTHONPATH=worker python3 tests/worker_schedule_api.py
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
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
    def __init__(self, name, risk, sensitivity="operational"):
        self.name = name
        self.risk = risk
        self.sensitivity = sensitivity

    def human_summary(self, args):
        return f"{self.name}: {json.dumps(args, sort_keys=True, ensure_ascii=False)}"


root = tempfile.mkdtemp(prefix="kaliv-schedule-api-")
db_path = os.path.join(root, "schedules.db")
now = [1_800_000_000.0]
registry = {
    "read_clock": FakeTool("read_clock", "read", "public"),
    "append_note": FakeTool("append_note", "write", "private"),
    "click_screen": FakeTool("click_screen", "desktop"),
}
admin = ScheduleAdmin(
    store_factory=lambda: ScheduleAdminStore(db_path),
    registry_factory=lambda: registry,
    clock=lambda: now[0],
)
app = FastAPI()
app.include_router(build_schedule_router(admin))
client = TestClient(app)

old_scheduler = os.environ.pop("KALIV_SCHEDULER", None)
try:
    # --- status + preview are truly non-persistent -----------------------------
    status = client.get("/schedules/status")
    check(status.status_code == 200, "scheduler status endpoint is available")
    check(status.json() == {
        "configured": False,
        "running": False,
        "resources_open": False,
        "last_error": None,
    }, "status tells the truth when production lifespan is absent and flag is off")
    check(not os.path.exists(db_path), "status does not create the schedule database")

    preview_resp = client.post("/schedules/preview", json={
        "tool": "append_note",
        "args": {"text": "Husk brygdag"},
        "cadence": "daily:08:00",
        "ttl_days": 30,
        "max_runs": 5,
    })
    check(preview_resp.status_code == 200, "write schedule can be previewed")
    preview = preview_resp.json()["preview"]
    approval = preview["approval_fingerprint"]
    check(preview["requires_approval"] and len(approval) == 32,
          "write preview returns an exact approval fingerprint")
    check(preview_resp.json()["executed"] is False and preview_resp.json()["persisted"] is False,
          "preview explicitly reports that it executed and persisted nothing")
    check("Husk brygdag" in preview["human_summary"],
          "preview exposes the exact human-readable action")
    check(not os.path.exists(db_path), "preview does not create the schedule database")

    # --- invalid or unapprovable schedules fail closed -------------------------
    unknown = client.post("/schedules/preview", json={
        "tool": "not_registered", "args": {}, "cadence": "every:60",
    })
    check(unknown.status_code == 404, "unknown tools are rejected")
    desktop = client.post("/schedules/preview", json={
        "tool": "click_screen", "args": {"x": 10}, "cadence": "every:60",
    })
    check(desktop.status_code == 422, "desktop actions can never be scheduled")
    too_fast = client.post("/schedules/preview", json={
        "tool": "read_clock", "args": {}, "cadence": "every:5",
    })
    check(too_fast.status_code == 422, "busy-loop cadences are rejected by scheduler policy")
    too_large = client.post("/schedules/preview", json={
        "tool": "append_note", "args": {"text": "x" * 21_000},
        "cadence": "every:60",
    })
    check(too_large.status_code == 422, "oversized argument payloads are bounded")

    missing_approval = client.post("/schedules", json={
        "tool": "append_note",
        "args": {"text": "Husk brygdag"},
        "cadence": "daily:08:00",
        "ttl_days": 30,
        "max_runs": 5,
    })
    check(missing_approval.status_code == 409,
          "a write cannot be persisted without returning the preview approval")
    check(not os.path.exists(db_path), "rejected write creates no schedule database")

    changed_args = client.post("/schedules", json={
        "tool": "append_note",
        "args": {"text": "En anden handling"},
        "cadence": "daily:08:00",
        "ttl_days": 30,
        "max_runs": 5,
        "approved_fingerprint": approval,
    })
    check(changed_args.status_code == 409,
          "changing one argument invalidates the old approval fingerprint")

    # --- exact write + read creation -------------------------------------------
    created_resp = client.post("/schedules", json={
        "tool": "append_note",
        "args": {"text": "Husk brygdag"},
        "cadence": "daily:08:00",
        "ttl_days": 30,
        "max_runs": 1,
        "approved_fingerprint": approval,
    })
    check(created_resp.status_code == 200, "the exact previewed write can be scheduled")
    write_schedule = created_resp.json()["schedule"]
    write_id = write_schedule["schedule_id"]
    check(created_resp.json()["executed"] is False,
          "creating a schedule never executes the action")
    check(write_schedule["approval_valid"] and write_schedule["eligible"],
          "persisted write is structurally eligible with matching approval")
    check(os.path.exists(db_path), "an explicit create request persists the schedule database")

    read_resp = client.post("/schedules", json={
        "tool": "read_clock", "args": {}, "cadence": "every:60",
        "ttl_days": 10,
    })
    check(read_resp.status_code == 200, "read schedules need no write approval")
    read_schedule = read_resp.json()["schedule"]
    check(read_schedule["approved_fingerprint"] is None and read_schedule["approval_valid"],
          "read schedule stores no fake approval fingerprint")

    listed = client.get("/schedules").json()["schedules"]
    check({item["schedule_id"] for item in listed} == {write_id, read_schedule["schedule_id"]},
          "list exposes every persisted schedule")
    check(client.get(f"/schedules/{write_id}").json()["schedule"]["args"] == {"text": "Husk brygdag"},
          "get returns the immutable approved arguments")
    check(client.get("/schedules/missing").status_code == 404,
          "missing schedule returns 404")

    # --- pause/resume starts fresh and refuses invalid standing grants ----------
    original_due = write_schedule["due_at"]
    paused = client.post(f"/schedules/{write_id}/enabled", json={"enabled": False})
    check(paused.status_code == 200 and not paused.json()["schedule"]["enabled"],
          "operator can pause a schedule")
    now[0] += 3600
    resumed = client.post(f"/schedules/{write_id}/enabled", json={"enabled": True})
    resumed_schedule = resumed.json()["schedule"]
    check(resumed.status_code == 200 and resumed_schedule["enabled"],
          "operator can resume a still-valid schedule")
    check(resumed_schedule["due_at"] > now[0] and resumed_schedule["due_at"] != original_due,
          "resume starts at a fresh future occurrence instead of replaying misses")

    # Consume the one-run budget through the real store, then pause it. Enabling
    # the exhausted standing grant must be refused until a human renews it.
    store = ScheduleAdminStore(db_path)
    store.record_claim_result(write_id, ran=True)
    store.set_enabled(write_id, False, now=now[0])
    store.close()
    exhausted = client.post(f"/schedules/{write_id}/enabled", json={"enabled": True})
    check(exhausted.status_code == 409 and "budget" in exhausted.json()["detail"],
          "an exhausted run budget cannot be silently re-enabled")

    # --- renewal is another exact human approval -------------------------------
    missing_renewal = client.post(f"/schedules/{write_id}/renew", json={
        "ttl_days": 60, "max_runs": 2, "enable": True,
    })
    check(missing_renewal.status_code == 409,
          "renewing a write requires the exact approval again")

    now[0] += 120
    renewed_resp = client.post(f"/schedules/{write_id}/renew", json={
        "ttl_days": 60,
        "max_runs": 2,
        "approved_fingerprint": approval,
        "enable": True,
    })
    renewed = renewed_resp.json()["schedule"]
    check(renewed_resp.status_code == 200, "matching approval renews the write schedule")
    check(renewed["runs_used"] == 0 and renewed["max_runs"] == 2,
          "renewal resets the consumed budget and installs the new bound")
    check(renewed["enabled"] and renewed["due_at"] > now[0],
          "explicit enable on renewal starts at a fresh future occurrence")
    check(renewed["approved_fingerprint"] == approval and renewed["approval_valid"],
          "renewal preserves exact argument binding")

    read_renew = client.post(
        f"/schedules/{read_schedule['schedule_id']}/renew",
        json={"ttl_days": 20, "max_runs": 3},
    )
    check(read_renew.status_code == 200,
          "read schedule renewal does not invent a write confirmation")

    # A runtime attached by the production lifespan is surfaced without opening
    # another store. This is status only; the API cannot flip KALIV_SCHEDULER.
    class FakeRuntime:
        def status(self):
            return SimpleNamespace(
                configured=True,
                running=True,
                resources_open=True,
                last_error=None,
            )

    app.state.scheduler_runtime = FakeRuntime()
    live_status = client.get("/schedules/status").json()
    check(live_status["configured"] and live_status["running"] and live_status["resources_open"],
          "status reports the production-owned runtime when present")

    check(client.delete(f"/schedules/{write_id}").status_code == 405,
          "administration surface has no schedule deletion endpoint")
finally:
    if old_scheduler is not None:
        os.environ["KALIV_SCHEDULER"] = old_scheduler

print(f"\n===== SCHEDULE API: {passed} passed, {failed} failed =====")
raise SystemExit(1 if failed else 0)
