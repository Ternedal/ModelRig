#!/usr/bin/env python3
"""T-017 ScheduleAdmin preview and approval-fingerprint time contracts.

Run: PYTHONPATH=worker python3 tests/worker_schedule_admin_preview_time.py
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


root = tempfile.mkdtemp(prefix="kaliv-t017-admin-preview-")
db_path = os.path.join(root, "schedules.db")
now = resolve_local_daily(
    date(2026, 3, 28), 10, 0, "Europe/Copenhagen"
).timestamp()
admin = ScheduleAdmin(
    store_factory=lambda: ScheduleAdminStore(db_path),
    registry_factory=lambda: {"append_note": FakeTool()},
    clock=lambda: now,
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
default = admin.preview("append_note", args, "daily:02:30")

check(not os.path.exists(db_path), "preview opens no schedule database")
check(copenhagen.timezone == "Europe/Copenhagen", "preview exposes canonical IANA timezone")
check(default.timezone == "Europe/Copenhagen", "default preview uses explicit rig timezone")
check(copenhagen.misfire_policy == "run_once", "preview exposes explicit run-once policy")
check(
    "T03:00:00+02:00" in copenhagen.due_at_local,
    "preview exposes shifted spring-forward due time with offset",
)
check(
    copenhagen.due_at != new_york.due_at,
    "same wall-clock cadence in different zones has different UTC identity",
)
check(
    copenhagen.approval_fingerprint != new_york.approval_fingerprint,
    "changing timezone invalidates standing-grant approval fingerprint",
)
serialized = copenhagen.to_dict()
check(
    serialized["timezone"] == copenhagen.timezone
    and serialized["misfire_policy"] == copenhagen.misfire_policy
    and serialized["due_at_local"] == copenhagen.due_at_local,
    "serialized preview carries the authoritative time contract",
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
check(invalid_zone_refused, "unknown timezone is rejected before preview")

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
check(invalid_policy_refused, "unsupported misfire policy is rejected before preview")
check(not os.path.exists(db_path), "rejected preview still persists nothing")

# Renewal preview is read from the persisted grant. It may not reinterpret the
# same daily cadence in the host timezone or silently choose another policy.
store = ScheduleAdminStore(db_path)
persisted = store.create(
    "append_note",
    args,
    "daily:02:30",
    approve_write=True,
    ttl_days=30,
    max_runs=5,
    now=now,
    timezone_name="America/New_York",
    misfire_policy="run_once",
)
store.close()
renew = admin.preview_renew(
    persisted.schedule_id,
    ttl_days=60,
    max_runs=2,
    enable=True,
)
check(renew.timezone == "America/New_York", "renew preview reuses persisted timezone")
check(renew.misfire_policy == "run_once", "renew preview reuses persisted misfire policy")
check(
    renew.approval_fingerprint != copenhagen.approval_fingerprint,
    "renew approval remains bound to persisted timezone",
)

print(f"\n===== SCHEDULE ADMIN PREVIEW TIME: {passed} passed, {failed} failed =====")
raise SystemExit(1 if failed else 0)
