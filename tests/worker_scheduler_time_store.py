#!/usr/bin/env python3
"""T-017 persistence, migration and occurrence-ledger timezone contracts.

Run: PYTHONPATH=worker python3 tests/worker_scheduler_time_store.py
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
import tempfile
from datetime import date

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "worker"))

from app import scheduler as S  # noqa: E402
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


def legacy_database(path: str) -> None:
    conn = sqlite3.connect(path)
    conn.execute(
        """CREATE TABLE schedules (
               id TEXT PRIMARY KEY,
               tool TEXT NOT NULL,
               args TEXT NOT NULL,
               cadence TEXT NOT NULL,
               approved_fingerprint TEXT,
               expires_at REAL NOT NULL,
               max_runs INTEGER NOT NULL DEFAULT 0,
               runs_used INTEGER NOT NULL DEFAULT 0,
               due_at REAL NOT NULL,
               missed INTEGER NOT NULL DEFAULT 0,
               enabled INTEGER NOT NULL DEFAULT 1,
               created REAL NOT NULL)"""
    )
    conn.execute(
        "INSERT INTO schedules VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            "legacy",
            "rig_status",
            json.dumps({}),
            "daily:08:00",
            None,
            2_000_000_000.0,
            0,
            0,
            1_900_000_000.0,
            0,
            1,
            1_800_000_000.0,
        ),
    )
    conn.commit()
    conn.close()


root = tempfile.mkdtemp(prefix="kaliv-t017-store-")

# Existing databases used the host timezone implicitly. Migration makes that
# historical Copenhagen meaning explicit rather than silently adopting a new
# Windows timezone after an operator or OS change.
legacy_path = os.path.join(root, "legacy.db")
legacy_database(legacy_path)
legacy_store = S.ScheduleStore(legacy_path)
legacy = legacy_store.get("legacy")
check(legacy is not None, "legacy schedule survives migration")
check(
    legacy is not None and legacy.timezone == "Europe/Copenhagen",
    "legacy schedule migrates to explicit Copenhagen timezone",
)
check(
    legacy is not None and legacy.misfire_policy == "run_once",
    "legacy schedule migrates to explicit run-once misfire policy",
)
legacy_store.close()

# A new schedule persists its IANA zone and policy and calculates its due time
# from those fields, not from the host process timezone.
store_path = os.path.join(root, "new.db")
store = S.ScheduleStore(store_path)
before_spring = resolve_local_daily(
    date(2026, 3, 28), 10, 0, "Europe/Copenhagen"
).timestamp()
spring = store.create(
    "rig_status",
    {},
    "daily:02:30",
    now=before_spring,
    timezone_name="Europe/Copenhagen",
    misfire_policy="run_once",
)
expected_shift = resolve_local_daily(
    date(2026, 3, 29), 2, 30, "Europe/Copenhagen"
).timestamp()
check(spring.due_at == expected_shift, "spring-forward occurrence shifts to first valid local minute")
check(spring.timezone == "Europe/Copenhagen", "new schedule stores its IANA timezone")
check(spring.misfire_policy == "run_once", "new schedule stores explicit misfire policy")
roundtrip = store.get(spring.schedule_id)
check(
    roundtrip is not None
    and roundtrip.timezone == spring.timezone
    and roundtrip.misfire_policy == spring.misfire_policy
    and roundtrip.due_at == spring.due_at,
    "timezone, policy and due time survive database roundtrip",
)

before_count = len(store.list_all())
try:
    store.create(
        "rig_status",
        {},
        "daily:08:00",
        now=before_spring,
        timezone_name="Mars/Olympus_Mons",
    )
    invalid_zone_refused = False
except S.ScheduleError as exc:
    invalid_zone_refused = "IANA" in str(exc)
check(invalid_zone_refused, "unknown timezone is rejected before persistence")
check(len(store.list_all()) == before_count, "invalid timezone leaves no schedule row")

try:
    store.create(
        "rig_status",
        {},
        "daily:08:00",
        now=before_spring,
        misfire_policy="replay_all",
    )
    invalid_policy_refused = False
except S.ScheduleError as exc:
    invalid_policy_refused = "misfire" in str(exc)
check(invalid_policy_refused, "unsupported misfire policy is rejected before persistence")
check(len(store.list_all()) == before_count, "invalid policy leaves no schedule row")
store.close()

# Fall-back overlap chooses fold=0 and therefore creates one durable occurrence,
# never one claim per UTC representation of the same local wall-clock time.
fall_path = os.path.join(root, "fall.db")
owner = S.ScheduleStore(fall_path)
peer = S.ScheduleStore(fall_path)
fall_due = resolve_local_daily(
    date(2026, 10, 25), 2, 30, "Europe/Copenhagen"
).timestamp()
fall = owner.create(
    "rig_status",
    {},
    "daily:02:30",
    now=fall_due - 60,
    timezone_name="Europe/Copenhagen",
)
check(fall.due_at == fall_due, "fall-back schedule selects the first local occurrence")
claims = owner.claim_due(now=fall_due + 90 * 60)
check(len(claims) == 1, "fall-back overlap creates exactly one claim")
check(peer.claim_due(now=fall_due + 90 * 60) == [], "peer cannot claim a hidden second overlap")
check(
    len(claims) == 1
    and claims[0].occurrence_due_at == fall_due
    and claims[0].schedule.runs_used == 1,
    "the one claimed overlap reserves exactly one budget slot",
)
check(
    len(claims) == 1 and claims[0].schedule.due_at > fall_due + 20 * 3600,
    "fall-back claim advances to the next local day",
)
owner.close()
peer.close()

# Downtime uses run-once: one occurrence is claimed now, older due occurrences
# are counted as missed, and only the real claim consumes budget.
misfire_path = os.path.join(root, "misfire.db")
misfire_store = S.ScheduleStore(misfire_path)
first_due = resolve_local_daily(
    date(2026, 7, 10), 8, 0, "Europe/Copenhagen"
).timestamp()
misfire = misfire_store.create(
    "rig_status",
    {},
    "daily:08:00",
    now=first_due - 60,
    timezone_name="Europe/Copenhagen",
    max_runs=20,
)
now = resolve_local_daily(
    date(2026, 7, 17), 12, 0, "Europe/Copenhagen"
).timestamp()
misfire_claims = misfire_store.claim_due(now=now)
check(len(misfire_claims) == 1, "week-long downtime runs one occurrence, not a replay burst")
check(
    len(misfire_claims) == 1 and misfire_claims[0].missed_this_claim == 7,
    "older due occurrences are reported as missed",
)
check(
    len(misfire_claims) == 1 and misfire_claims[0].schedule.runs_used == 1,
    "missed occurrences do not consume run budget",
)

# Corrupt/unknown policy data fails closed at claim time and disables only that
# schedule rather than guessing a replay behaviour.
with misfire_store._lock:
    misfire_store._conn.execute(
        "UPDATE schedules SET misfire_policy='replay_all', due_at=? WHERE id=?",
        (now - 1, misfire.schedule_id),
    )
    misfire_store._conn.commit()
check(misfire_store.claim_due(now=now) == [], "unknown persisted policy is never executed")
corrupt = misfire_store.get(misfire.schedule_id)
check(corrupt is not None and not corrupt.enabled, "unknown persisted policy disables its schedule fail-closed")
misfire_store.close()

print(f"\n===== SCHEDULER TIME STORE: {passed} passed, {failed} failed =====")
raise SystemExit(1 if failed else 0)
