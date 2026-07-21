"""Deterministic wall-clock semantics for durable schedules.

A schedule's timezone is persisted IANA data, never the host's current zone.
Daily times use three explicit policies:

* nonexistent local time (spring forward): shift minute-by-minute to the first
  valid local instant;
* ambiguous local time (fall back): choose the first occurrence (fold=0);
* misfire after downtime: run one due occurrence now, report older occurrences
  as missed, and advance to the next future occurrence.

These choices prevent system-zone changes and clock rollback from inventing a
second occurrence for the same local day.
"""
from __future__ import annotations

from datetime import date, datetime, time as dt_time, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

DEFAULT_TIMEZONE = "Europe/Copenhagen"
MISFIRE_POLICY = "run_once"
NONEXISTENT_TIME_POLICY = "shift_forward"
AMBIGUOUS_TIME_POLICY = "first"
_MAX_GAP_MINUTES = 180


class ScheduleTimeError(ValueError):
    """A timezone or local wall-clock value that cannot be represented safely."""


def validate_timezone(name: str) -> ZoneInfo:
    candidate = (name or "").strip()
    if not candidate:
        raise ScheduleTimeError("timezone skal være et eksplicit IANA-navn")
    try:
        return ZoneInfo(candidate)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ScheduleTimeError(f"ukendt IANA-timezone {candidate!r}") from exc


def _roundtrip_matches(local_naive: datetime, zone: ZoneInfo, fold: int) -> bool:
    aware = local_naive.replace(tzinfo=zone, fold=fold)
    returned = aware.astimezone(timezone.utc).astimezone(zone)
    return returned.replace(tzinfo=None) == local_naive and returned.fold == fold


def resolve_local_daily(
    local_date: date,
    hour: int,
    minute: int,
    timezone_name: str,
) -> datetime:
    """Resolve one local daily occurrence according to the documented policies."""
    zone = validate_timezone(timezone_name)
    requested = datetime.combine(local_date, dt_time(hour=hour, minute=minute))

    for shift in range(_MAX_GAP_MINUTES + 1):
        candidate = requested + timedelta(minutes=shift)
        valid_folds = [fold for fold in (0, 1) if _roundtrip_matches(candidate, zone, fold)]
        if not valid_folds:
            continue
        # A normal instant commonly round-trips for fold=0 only. During a fall-back
        # overlap both folds are valid; choosing fold=0 means the first occurrence.
        return candidate.replace(tzinfo=zone, fold=min(valid_folds))

    raise ScheduleTimeError(
        f"lokalt tidspunkt {requested.isoformat(timespec='minutes')} kunne ikke "
        f"opløses i {timezone_name!r} inden for {_MAX_GAP_MINUTES} minutter"
    )


def next_daily_run(
    *,
    hour: int,
    minute: int,
    after: float,
    timezone_name: str,
) -> float:
    """Next selected daily occurrence strictly after ``after``."""
    zone = validate_timezone(timezone_name)
    after_utc = datetime.fromtimestamp(after, tz=timezone.utc)
    local_date = after_utc.astimezone(zone).date()

    for day_offset in (0, 1, 2):
        candidate = resolve_local_daily(
            local_date + timedelta(days=day_offset),
            hour,
            minute,
            timezone_name,
        )
        timestamp = candidate.timestamp()
        if timestamp > after:
            return timestamp

    raise ScheduleTimeError("kunne ikke finde næste daglige occurrence")


def catch_up_daily(
    *,
    hour: int,
    minute: int,
    due_at: float,
    now: float,
    timezone_name: str,
) -> tuple[int, float]:
    """Return missed count and next future due time under run-once misfire policy."""
    validate_timezone(timezone_name)
    if now < due_at:
        return 0, due_at

    occurrences = 0
    due = due_at
    while due <= now:
        due = next_daily_run(
            hour=hour,
            minute=minute,
            after=due,
            timezone_name=timezone_name,
        )
        occurrences += 1
        if occurrences > 370_000:
            raise ScheduleTimeError("for mange daglige occurrences i catch-up-vinduet")

    # Exactly one due occurrence is claimed now. Older occurrences are reported
    # as missed, never replayed and never charged to the run budget.
    return max(0, occurrences - 1), due


def local_due_iso(timestamp: float, timezone_name: str) -> str:
    """Server-authoritative local representation for clients and receipts."""
    zone = validate_timezone(timezone_name)
    return datetime.fromtimestamp(timestamp, tz=timezone.utc).astimezone(zone).isoformat()
