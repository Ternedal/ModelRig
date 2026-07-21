#!/usr/bin/env python3
from __future__ import annotations

import os
import sys
import time
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "worker"))

from app import scheduler_time as T  # noqa: E402

passed = failed = 0


def check(condition: bool, message: str) -> None:
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS: {message}")
    else:
        failed += 1
        print(f"  FAIL: {message}")


def utc_ts(year: int, month: int, day: int, hour: int, minute: int) -> float:
    return datetime(year, month, day, hour, minute, tzinfo=timezone.utc).timestamp()


check(T.validate_timezone("Europe/Copenhagen").key == "Europe/Copenhagen", "IANA timezone validates")
try:
    T.validate_timezone("Not/A_Real_Zone")
    check(False, "unknown timezone is refused")
except T.ScheduleTimeError as exc:
    check("IANA" in str(exc), "unknown timezone fails with a useful reason")

spring = T.resolve_local_daily(date(2026, 3, 29), 2, 30, "Europe/Copenhagen")
check((spring.hour, spring.minute) == (3, 0), "spring-forward gap shifts to first valid minute")
check(spring.timestamp() == utc_ts(2026, 3, 29, 1, 0), "shifted spring occurrence has exact UTC identity")

fall = T.resolve_local_daily(date(2026, 10, 25), 2, 30, "Europe/Copenhagen")
check(fall.fold == 0, "fall-back overlap chooses first occurrence")
check(fall.timestamp() == utc_ts(2026, 10, 25, 0, 30), "first fall-back occurrence is stable in UTC")

next_after_first = T.next_daily_run(
    hour=2,
    minute=30,
    after=fall.timestamp(),
    timezone_name="Europe/Copenhagen",
)
next_local = datetime.fromtimestamp(next_after_first, tz=ZoneInfo("Europe/Copenhagen"))
check(next_local.date() == date(2026, 10, 26), "clock rollback cannot create a second same-day claim")
check((next_local.hour, next_local.minute) == (2, 30), "next day keeps the requested wall-clock time")

before_spring = utc_ts(2026, 3, 28, 3, 0)
next_spring = T.next_daily_run(
    hour=2,
    minute=30,
    after=before_spring,
    timezone_name="Europe/Copenhagen",
)
check(next_spring == spring.timestamp(), "next-run applies the nonexistent-time policy")

week_due = T.resolve_local_daily(date(2026, 3, 25), 8, 0, "Europe/Copenhagen").timestamp()
week_now = T.resolve_local_daily(date(2026, 4, 1), 10, 0, "Europe/Copenhagen").timestamp()
missed, next_due = T.catch_up_daily(
    hour=8,
    minute=0,
    due_at=week_due,
    now=week_now,
    timezone_name="Europe/Copenhagen",
)
check(missed == 7, "week-long downtime reports seven missed daily occurrences and runs once")
check(next_due > week_now, "misfire catch-up advances into the future")

not_due, unchanged = T.catch_up_daily(
    hour=8,
    minute=0,
    due_at=week_now + 60,
    now=week_now,
    timezone_name="Europe/Copenhagen",
)
check(not_due == 0 and unchanged == week_now + 60, "future occurrence is unchanged")

# The host timezone must not participate in the result. tzset is unavailable on
# Windows, but CI on Unix still proves no accidental time.localtime dependency.
if hasattr(time, "tzset"):
    original = os.environ.get("TZ")
    try:
        os.environ["TZ"] = "Pacific/Honolulu"
        time.tzset()
        honolulu_host = T.next_daily_run(
            hour=8,
            minute=0,
            after=utc_ts(2026, 7, 1, 12, 0),
            timezone_name="Europe/Copenhagen",
        )
        os.environ["TZ"] = "Asia/Tokyo"
        time.tzset()
        tokyo_host = T.next_daily_run(
            hour=8,
            minute=0,
            after=utc_ts(2026, 7, 1, 12, 0),
            timezone_name="Europe/Copenhagen",
        )
        check(honolulu_host == tokyo_host, "changing host timezone does not change schedule meaning")
    finally:
        if original is None:
            os.environ.pop("TZ", None)
        else:
            os.environ["TZ"] = original
        time.tzset()

check(T.MISFIRE_POLICY == "run_once", "misfire policy is explicit")
check(T.NONEXISTENT_TIME_POLICY == "shift_forward", "spring policy is explicit")
check(T.AMBIGUOUS_TIME_POLICY == "first", "fall-back policy is explicit")
check(
    T.local_due_iso(fall.timestamp(), "Europe/Copenhagen").endswith("+02:00"),
    "server-authoritative local ISO includes the selected offset",
)

print(f"scheduler time semantics: {passed} passed, {failed} failed")
if failed:
    raise SystemExit(1)
