#!/usr/bin/env python3
"""T-017 ScheduleAdmin create/describe/renew timezone persistence contracts.

This layer starts from an already canonical preview. HTTP request models and
signed approval tokens remain outside this test.
Run: PYTHONPATH=worker python3 tests/worker_schedule_admin_persistence_time.py
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from datetime import date

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "worker"))

from app.schedule_admin import ScheduleAdmin, ScheduleAdminStore  # noqa: E402
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


class FakeWriteTool:
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


root = tempfile.mkdtemp(prefix="kaliv-t017-admin-persist-")
db_path = os.path.join(root, "schedules.db")
clock = [
    resolve_local_daily(
        date(2026, 3, 28), 10, 0, "Europe/Copenhagen"
    ).timestamp()
]
registry = {"append_note": FakeWriteTool()}
admin = ScheduleAdmin(
    store_factory=lambda: ScheduleAdminStore(db_path),
    registry_factory=lambda: registry,
    clock=lambda: clock[0],
)
args = {"text": "New York-plan"}

preview = admin.preview(
    "append_note",
    args,
    "daily:02:30",
    ttl_days=30,
    max_runs=5,
    timezone_name="America/New_York",
    misfire_policy="run_once",
)
created = admin.create(
    "append_note",
    args,
    "daily:02:30",
    ttl_days=30,
    max_runs=5,
    timezone_name="America/New_York",
    misfire_policy="run_once",
    approved_fingerprint=preview.approval_fingerprint,
)
schedule_id = created["schedule_id"]

check(created["timezone"] == "America/New_York", "create persists previewed IANA timezone")
check(created["misfire_policy"] == "run_once", "create persists previewed misfire policy")
check(created["due_at"] == preview.due_at, "create preserves previewed UTC due identity")
check(created["due_at_local"] == preview.due_at_local, "create preserves previewed local due representation")
check(created["approval_valid"], "timezone-bound write keeps its action approval valid")

stored = admin.get(schedule_id)
listed = admin.list_all()
check(stored["timezone"] == "America/New_York", "get exposes persisted timezone")
check(stored["due_at_local"] == created["due_at_local"], "get uses server-authoritative local due time")
check(len(listed) == 1 and listed[0]["timezone"] == "America/New_York", "list exposes persisted timezone")
check(len(listed) == 1 and listed[0]["due_at_local"] == created["due_at_local"], "list exposes authoritative local due time")

paused = admin.set_enabled(schedule_id, False)
check(not paused["enabled"] and paused["timezone"] == "America/New_York", "pause preserves timezone contract")
clock[0] += 12 * 3600
resumed = admin.set_enabled(schedule_id, True)
expected_resume = next_run(
    parse_cadence("daily:02:30"), clock[0], "America/New_York"
)
check(resumed["due_at"] == expected_resume, "resume calculates next run in persisted timezone")
check(resumed["timezone"] == "America/New_York", "resume cannot reinterpret timezone")

renew_preview = admin.preview_renew(
    schedule_id,
    ttl_days=60,
    max_runs=2,
    enable=True,
)
renewed = admin.renew(
    schedule_id,
    ttl_days=60,
    max_runs=2,
    enable=True,
    approved_fingerprint=renew_preview.approval_fingerprint,
)
expected_renew = next_run(
    parse_cadence("daily:02:30"), clock[0], "America/New_York"
)
check(renewed["timezone"] == "America/New_York", "renewal preserves immutable timezone")
check(renewed["misfire_policy"] == "run_once", "renewal preserves immutable misfire policy")
check(renewed["due_at"] == expected_renew, "enabled renewal restarts in persisted timezone")
check(renewed["due_at_local"] == renew_preview.due_at_local, "renewal matches server preview local time")
check(renewed["runs_used"] == 0 and renewed["max_runs"] == 2, "renewal still resets run budget")
check(renewed["approval_valid"], "renewal keeps immutable action approval valid")

# Reopen through a new store/admin instance to prove this is durable data, not a
# value retained in the first administration object's memory.
reopened = ScheduleAdmin(
    store_factory=lambda: ScheduleAdminStore(db_path),
    registry_factory=lambda: registry,
    clock=lambda: clock[0],
).get(schedule_id)
check(reopened["timezone"] == "America/New_York", "timezone survives process-style reopen")
check(reopened["misfire_policy"] == "run_once", "misfire policy survives process-style reopen")
check(reopened["due_at_local"] == renewed["due_at_local"], "local due display survives reopen")

print(f"\n===== SCHEDULE ADMIN PERSISTENCE TIME: {passed} passed, {failed} failed =====")
raise SystemExit(1 if failed else 0)
