#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "scheduler_time_oracle_tested",
    ROOT / "scripts" / "scheduler_time_oracle.py",
)
assert spec and spec.loader
oracle = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = oracle
spec.loader.exec_module(oracle)

UTC = timezone.utc
passed = failed = 0


def check(condition: bool, name: str) -> None:
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS: {name}")
    else:
        failed += 1
        print(f"  FAIL: {name}")


# Copenhagen spring-forward: 02:30 does not exist on 29 March 2026.
gap = oracle.resolve_daily(date(2026, 3, 29), 2, 30, "Europe/Copenhagen")
check(gap is None, "spring-forward nonexistent local time is skipped")

after_gap = datetime(2026, 3, 28, 12, tzinfo=UTC).timestamp()
next_after_gap = oracle.next_daily(after_gap, 2, 30, "Europe/Copenhagen")
check(
    next_after_gap.local_date == date(2026, 3, 30),
    "next daily occurrence skips the nonexistent civil date",
)
check(
    datetime.fromtimestamp(next_after_gap.epoch, UTC)
    == datetime(2026, 3, 30, 0, 30, tzinfo=UTC),
    "post-gap occurrence has the expected UTC instant",
)

# Copenhagen fall-back: 02:30 occurs twice on 25 October 2026.
overlap = oracle.resolve_daily(date(2026, 10, 25), 2, 30, "Europe/Copenhagen")
check(overlap is not None, "fall-back local time resolves")
check(overlap.fold == 0, "ambiguous local time chooses the first fold")
check(overlap.resolution == "ambiguous_earlier", "overlap decision is explicit")
check(
    datetime.fromtimestamp(overlap.epoch, UTC)
    == datetime(2026, 10, 25, 0, 30, tzinfo=UTC),
    "first fall-back occurrence is the earlier UTC instant",
)

second_fold_epoch = datetime(2026, 10, 25, 1, 30, tzinfo=UTC).timestamp()
after_first = oracle.next_daily(overlap.epoch, 2, 30, "Europe/Copenhagen")
check(
    after_first.local_date == date(2026, 10, 26),
    "the second fold is not emitted as a duplicate daily occurrence",
)
check(
    after_first.epoch > second_fold_epoch,
    "next occurrence is after the entire overlap window",
)

# Explicit zone means a changed process/system zone cannot change the answer.
copenhagen = oracle.next_daily(
    datetime(2026, 1, 15, 12, tzinfo=UTC).timestamp(),
    8,
    0,
    "Europe/Copenhagen",
)
new_york = oracle.next_daily(
    datetime(2026, 1, 15, 12, tzinfo=UTC).timestamp(),
    8,
    0,
    "America/New_York",
)
check(copenhagen.epoch != new_york.epoch, "IANA zone is part of the schedule truth")
check(copenhagen.timezone == "Europe/Copenhagen", "resolved occurrence retains zone identity")

# Invalid or underspecified values are rejected rather than guessed.
for bad_zone in ("", "Copenhagen", "Europe/DefinitelyMissing"):
    try:
        oracle.load_zone(bad_zone)
        rejected = False
    except oracle.TimePolicyError:
        rejected = True
    check(rejected, f"invalid IANA zone {bad_zone!r} is rejected")

# Downtime policy: one coalesced claim, all older overdue occurrences reported.
due = datetime(2026, 7, 10, 6, 0, tzinfo=UTC).timestamp()
now = datetime(2026, 7, 13, 12, 0, tzinfo=UTC).timestamp()
daily = oracle.coalesce_once(
    due,
    now,
    lambda after: oracle.next_daily(after, 8, 0, "Europe/Copenhagen").epoch,
)
check(daily.run_due_at == due, "misfire keeps the oldest due instant for audit")
check(daily.missed == 3, "three additional overdue daily occurrences are reported as missed")
check(
    datetime.fromtimestamp(daily.next_due_at, UTC)
    == datetime(2026, 7, 14, 6, 0, tzinfo=UTC),
    "daily misfire advances to the first future occurrence",
)

interval = oracle.coalesce_interval(100.0, 350.0, 60)
check(interval.run_due_at == 100.0, "interval downtime also coalesces to one claim")
check(interval.missed == 4, "interval missed count excludes the coalesced claim")
check(interval.next_due_at == 400.0, "interval next due is strictly in the future")

future = oracle.coalesce_interval(500.0, 350.0, 60)
check(future.run_due_at is None and future.missed == 0, "future occurrence is not claimed early")
check(future.next_due_at == 500.0, "future due instant is preserved")

# A persisted next_due after a claim stays authoritative through clock rollback.
claimed_next = daily.next_due_at
rolled_back_now = now - timedelta(hours=8).total_seconds()
rollback = oracle.coalesce_once(
    claimed_next,
    rolled_back_now,
    lambda after: oracle.next_daily(after, 8, 0, "Europe/Copenhagen").epoch,
)
check(rollback.run_due_at is None, "clock rollback does not replay a consumed occurrence")
check(rollback.next_due_at == claimed_next, "clock rollback preserves persisted next due")

# next_after must be monotonic; an invalid implementation cannot loop silently.
try:
    oracle.coalesce_once(100.0, 100.0, lambda value: value)
    monotonic_rejected = False
except oracle.TimePolicyError:
    monotonic_rejected = True
check(monotonic_rejected, "non-advancing next function is rejected")

print(f"\n===== SCHEDULER TIME ORACLE: {passed} passed, {failed} failed =====")
raise SystemExit(1 if failed else 0)
