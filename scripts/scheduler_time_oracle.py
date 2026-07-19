#!/usr/bin/env python3
"""Reference oracle for T-017 scheduler timezone, DST and misfire semantics.

This module is deliberately not imported by the worker. It freezes the intended
behavior in pure functions before the storage/API/runner migration is allowed to
change production code.

Policy:
- every:N is an absolute interval and does not change with civil-time offsets;
- daily:HH:MM is evaluated in an explicit IANA timezone;
- nonexistent local times are skipped for that civil date;
- ambiguous local times use the earlier UTC instant (fold=0) exactly once;
- downtime coalesces all due occurrences into at most one immediate claim;
- skipped/missed occurrences do not consume run-budget slots.
"""
from __future__ import annotations

import argparse
import json
import math
from dataclasses import asdict, dataclass
from datetime import date, datetime, time as wall_time, timedelta, timezone
from typing import Callable
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

UTC = timezone.utc
MISFIRE_COALESCE_ONCE = "coalesce_once"
MAX_DAILY_SEARCH_DAYS = 370
MAX_MISFIRE_OCCURRENCES = 500_000


class TimePolicyError(ValueError):
    """The requested civil-time schedule cannot be represented safely."""


@dataclass(frozen=True)
class DailyOccurrence:
    local_date: date
    hour: int
    minute: int
    timezone: str
    epoch: float
    fold: int
    resolution: str

    def to_dict(self) -> dict:
        value = asdict(self)
        value["local_date"] = self.local_date.isoformat()
        value["utc"] = datetime.fromtimestamp(self.epoch, UTC).isoformat()
        return value


@dataclass(frozen=True)
class MisfireDecision:
    run_due_at: float | None
    missed: int
    next_due_at: float
    policy: str = MISFIRE_COALESCE_ONCE

    def to_dict(self) -> dict:
        return asdict(self)


def load_zone(name: str) -> ZoneInfo:
    value = name.strip() if isinstance(name, str) else ""
    if not value:
        raise TimePolicyError("timezone must be a non-empty IANA name")
    try:
        zone = ZoneInfo(value)
    except ZoneInfoNotFoundError as exc:
        raise TimePolicyError(f"unknown IANA timezone: {value!r}") from exc
    if zone.key is None:
        raise TimePolicyError(f"timezone has no stable IANA key: {value!r}")
    return zone


def _validate_wall_time(hour: int, minute: int) -> None:
    if isinstance(hour, bool) or not isinstance(hour, int) or not 0 <= hour <= 23:
        raise TimePolicyError("hour must be an integer from 0 to 23")
    if isinstance(minute, bool) or not isinstance(minute, int) or not 0 <= minute <= 59:
        raise TimePolicyError("minute must be an integer from 0 to 59")


def _valid_candidates(local_naive: datetime, zone: ZoneInfo) -> list[tuple[float, int]]:
    """Return real UTC instants represented by this local wall time.

    zoneinfo permits constructing nonexistent times, so construction alone is
    not validation. Round-trip through UTC and require the same wall fields and
    fold. Normal time yields one candidate, a fall-back overlap yields two, and a
    spring-forward gap yields none.
    """
    candidates: dict[float, int] = {}
    for fold in (0, 1):
        aware = local_naive.replace(tzinfo=zone, fold=fold)
        utc = aware.astimezone(UTC)
        roundtrip = utc.astimezone(zone)
        if roundtrip.replace(tzinfo=None) == local_naive and roundtrip.fold == fold:
            candidates[utc.timestamp()] = fold
    return [(epoch, candidates[epoch]) for epoch in sorted(candidates)]


def resolve_daily(
    local_date: date,
    hour: int,
    minute: int,
    timezone_name: str,
) -> DailyOccurrence | None:
    """Resolve one civil date.

    None means the local clock label does not exist on that date and policy says
    to skip it. When a label occurs twice, the earlier UTC instant wins.
    """
    if not isinstance(local_date, date) or isinstance(local_date, datetime):
        raise TimePolicyError("local_date must be a date")
    _validate_wall_time(hour, minute)
    zone = load_zone(timezone_name)
    local_naive = datetime.combine(local_date, wall_time(hour, minute))
    candidates = _valid_candidates(local_naive, zone)
    if not candidates:
        return None
    epoch, fold = candidates[0]
    return DailyOccurrence(
        local_date=local_date,
        hour=hour,
        minute=minute,
        timezone=zone.key,
        epoch=epoch,
        fold=fold,
        resolution="ambiguous_earlier" if len(candidates) > 1 else "normal",
    )


def next_daily(
    after_epoch: float,
    hour: int,
    minute: int,
    timezone_name: str,
) -> DailyOccurrence:
    """First valid daily occurrence strictly after an absolute instant."""
    if (
        isinstance(after_epoch, bool)
        or not isinstance(after_epoch, (int, float))
        or not math.isfinite(after_epoch)
    ):
        raise TimePolicyError("after_epoch must be a finite number")
    _validate_wall_time(hour, minute)
    zone = load_zone(timezone_name)
    start_date = datetime.fromtimestamp(float(after_epoch), UTC).astimezone(zone).date()
    for offset in range(MAX_DAILY_SEARCH_DAYS):
        occurrence = resolve_daily(
            start_date + timedelta(days=offset),
            hour,
            minute,
            zone.key,
        )
        if occurrence is not None and occurrence.epoch > after_epoch:
            return occurrence
    raise TimePolicyError("no daily occurrence found inside the bounded search horizon")


def next_interval(after_epoch: float, seconds: int) -> float:
    if (
        isinstance(after_epoch, bool)
        or not isinstance(after_epoch, (int, float))
        or not math.isfinite(after_epoch)
    ):
        raise TimePolicyError("after_epoch must be a finite number")
    if isinstance(seconds, bool) or not isinstance(seconds, int) or seconds < 60:
        raise TimePolicyError("interval seconds must be an integer of at least 60")
    return float(after_epoch) + seconds


def coalesce_once(
    due_at: float,
    now: float,
    next_after: Callable[[float], float],
) -> MisfireDecision:
    """Coalesce one or many overdue occurrences into at most one claim.

    The claim retains the oldest due_at for audit truth. The next due instant is
    advanced past now. Only the coalesced claim consumes a run-budget slot; the
    returned missed count is informational.
    """
    for label, value in (("due_at", due_at), ("now", now)):
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
        ):
            raise TimePolicyError(f"{label} must be a finite number")
    due = float(due_at)
    current = float(now)
    if current < due:
        return MisfireDecision(run_due_at=None, missed=0, next_due_at=due)

    occurrences = 0
    next_due = due
    while next_due <= current:
        previous = next_due
        next_due = float(next_after(next_due))
        if not math.isfinite(next_due) or next_due <= previous:
            raise TimePolicyError("next_after must move strictly forward")
        occurrences += 1
        if occurrences > MAX_MISFIRE_OCCURRENCES:
            raise TimePolicyError("misfire scan exceeded its bounded occurrence limit")
    return MisfireDecision(
        run_due_at=due,
        missed=max(0, occurrences - 1),
        next_due_at=next_due,
    )


def coalesce_interval(due_at: float, now: float, seconds: int) -> MisfireDecision:
    """Constant-time coalescing for an absolute interval."""
    if isinstance(seconds, bool) or not isinstance(seconds, int) or seconds < 60:
        raise TimePolicyError("interval seconds must be an integer of at least 60")
    for label, value in (("due_at", due_at), ("now", now)):
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
        ):
            raise TimePolicyError(f"{label} must be a finite number")
    due = float(due_at)
    current = float(now)
    if current < due:
        return MisfireDecision(run_due_at=None, missed=0, next_due_at=due)
    occurrences = int((current - due) // seconds) + 1
    return MisfireDecision(
        run_due_at=due,
        missed=max(0, occurrences - 1),
        next_due_at=due + occurrences * seconds,
    )


def _parse_iso(value: str) -> float:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise TimePolicyError("after must be an ISO-8601 datetime") from exc
    if parsed.tzinfo is None:
        raise TimePolicyError("after must include an offset")
    return parsed.astimezone(UTC).timestamp()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--timezone", required=True)
    parser.add_argument("--daily", required=True, help="HH:MM")
    parser.add_argument("--after", required=True, help="ISO-8601 datetime with offset")
    args = parser.parse_args(argv)
    try:
        hour_text, minute_text = args.daily.split(":", 1)
        occurrence = next_daily(
            _parse_iso(args.after),
            int(hour_text),
            int(minute_text),
            args.timezone,
        )
    except (TimePolicyError, ValueError) as exc:
        parser.error(str(exc))
    print(json.dumps(occurrence.to_dict(), ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
