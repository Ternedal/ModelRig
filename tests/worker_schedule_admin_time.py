#!/usr/bin/env python3
"""T-017 ScheduleAdmin timezone, preview and approval-fingerprint contracts.

Run: PYTHONPATH=worker python3 tests/worker_schedule_admin_time.py
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from datetime import date

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "worker"))

from app.schedule_admin import (  # noqa: E402
    ScheduleAdmin,
    ScheduleAdminError,
    ScheduleAdminStore,
)
from app.scheduler import next_run, parse_cadence  # noqa: E402
from app.scheduler_time import resolve_local_daily  # noqa: E402

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
    risk = "write"
    sensitivity = "private"
    schedulable = True
    unschedulable_because = ""
    params = {
        "type": "object",
        "properties": {"text": {"type": "string"}},
        "required": ["text"],
    }

    @staticmethod
    def human_summary(args):
        return f"append {json.dumps(args['text'], ensure_ascii=False)}"


root = tempfile.mkdtemp(prefix="kaliv-t017-admin-")
db_path = os.path.join(root, "schedules.db")
clock = [
    resolve_local_daily(
        date(2026, 3, 28), 10, 0, "Europe/Copenhagen"
    ).timestamp()
]
admin = ScheduleAdmin(
    store_factory=lambda: ScheduleAdminStore(db_path),
    registry_factory=lambda: {"append_note": FakeTool()},
    clock=lambda: clock[0],
)
args = {"text": "DST-plan"}

copenhagen = admin.preview(
    "append_note",
    args,
    "daily:02:30",
    ttl_days=30,
    max_runs=5,
    timezone_name="Europe/Copenhagen",
)
new_york = admin.preview(
    "append_note",
    args,
    "daily:02:30",
    ttl_days=30,
    max_runs=5,
    timezone_name="America/New_York",
)

check(copenhagen.timezone == "Europe/Copenhagen", "preview exposes canonical IANA timezone")
check(copenhagen.misfire_policy == "run_once", "preview exposes explicit run-once policy")
check(
    "T03:00:00+02:00" in copenhagen.due_at_local,
    "preview exposes server-authoritative shifted spring due time with offset",
)
check(
    copenhagen.due_at != new_york.due_at,
    "same wall-clock cadence in different zones has different UTC due time",
)
check(
    copenhagen.approval_fingerprint != new_york.approval_fingerprint,
    "changing timezone changes the standing-grant approval fingerprint",
)
check(
    copenhagen.to_dict()["timezone"] == "Europe/Copenhagen"
    and copenhagen.to_dict()["misfire_policy"] == "run_once"
    and copenhagen.to_dict()["due_at_local"] == copenhagen.due_at_local,
    "serialized preview carries the same authoritative time contract",
)

try:
    admin.preview(
        "append_note",
        args,
        "daily:08:00",
        timezone_name="Mars/Olympus_Mons",
    )
    invalid_zone_refused = False
except ScheduleAdminError as exc:
    invalid_zone_refused = "IANA" in str(exc)
check(invalid_zone_refused, "admin rejects unknown timezone before preview")

try:
    admin.preview(
        "append_note",
        args,
        "daily:08:00",
        misfire_policy="replay_all",
    )
    invalid_policy_refused = False
except ScheduleAdminError as exc:
    invalid_policy_refused = "misfire" in str(exc)
check(invalid_policy_refused, "admin rejects unsupported misfire policy")

created = admin.create(
    "append_note",
    args,
    "daily:02:30",
    ttl_days=30,
    max_runs=5,
    timezone_name="America/New_York",
    misfire_policy="run_once",
    approved_fingerprint=new_york.approval_fingerprint,
)
schedule_id = created["schedule_id"]
check(created["timezone"] == "America/New_York", "create persists the previewed timezone")
check(created["misfire_policy"] == "run_once", "create persists the previewed misfire policy")
check(created["due_at_local"] == new_york.due_at_local, "create reports the same local due time as preview")
check(admin.get(schedule_id)["timezone"] == "America/New_York", "get preserves authoritative timezone")
check(admin.list_all()[0]["due_at_local"] == new_york.due_at_local, "list preserves authoritative local due time")

paused = admin.set_enabled(schedule_id, False)
check(not paused["enabled"], "timezone-bound schedule can be paused")
clock[0] += 12 * 3600
resumed = admin.set_enabled(schedule_id, True)
expected_resume = next_run(
    parse_cadence("daily:02:30"), clock[0], "America/New_York"
)
check(resumed["due_at"] == expected_resume, "resume uses persisted timezone, not host timezone")
check(resumed["timezone"] == "America/New_York", "resume cannot change schedule timezone")

renew_preview = admin.preview_renew(
    schedule_id,
    ttl_days=60,
    max_runs=2,
    enable=True,
)
check(
    renew_preview.timezone == "America/New_York"
    and renew_preview.misfire_policy == "run_once",
    "renew preview reuses the immutable stored time contract",
)
renewed = admin.renew(
    schedule_id,
    ttl_days=60,
    max_runs=2,
    enable=True,
    approved_fingerprint=renew_preview.approval_fingerprint,
)
check(renewed["timezone"] == "America/New_York", "renewal preserves immutable timezone")
check(renewed["misfire_policy"] == "run_once", "renewal preserves immutable misfire policy")
check(
    renewed["due_at"] == next_run(
        parse_cadence("daily:02:30"), clock[0], "America/New_York"
    ),
    "enabled renewal calculates fresh due time in persisted timezone",
)

print(f"\n===== SCHEDULE ADMIN TIME: {passed} passed, {failed} failed =====")
raise SystemExit(1 if failed else 0)
