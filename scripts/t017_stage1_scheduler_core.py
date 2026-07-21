#!/usr/bin/env python3
"""Apply only T-017 scheduler-core and SQLite changes.

Temporary transport. The diagnostics workflow removes this file and the retired
monolithic patcher before committing the proven canonical tree.
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_once(path: str, old: str, new: str) -> None:
    target = ROOT / path
    text = target.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(
            f"{path}: expected one match, found {count}: {old[:120]!r}"
        )
    target.write_text(text.replace(old, new, 1), encoding="utf-8")


# Import the already-proven pure time engine into the canonical scheduler.
replace_once(
    "worker/app/scheduler.py",
    "from dataclasses import dataclass\n",
    "from dataclasses import dataclass\n\n"
    "from .scheduler_time import (\n"
    "    DEFAULT_TIMEZONE,\n"
    "    MISFIRE_POLICY,\n"
    "    ScheduleTimeError,\n"
    "    catch_up_daily,\n"
    "    next_daily_run,\n"
    "    validate_timezone,\n"
    ")\n",
)

replace_once(
    "worker/app/scheduler.py",
    '''def next_run(cadence: Cadence, after: float) -> float:\n    """The next moment this should fire, strictly after `after`."""\n    if cadence.kind == "every":\n        return after + cadence.seconds\n    if cadence.kind != "daily":\n        raise ScheduleError(f"ukendt cadence-kind {cadence.kind!r}")\n    lt = time.localtime(after)\n    candidate = time.mktime((\n        lt.tm_year, lt.tm_mon, lt.tm_mday,\n        cadence.hour, cadence.minute, 0, 0, 0, -1,\n    ))\n    if candidate <= after:\n        candidate = time.mktime((\n            lt.tm_year, lt.tm_mon, lt.tm_mday + 1,\n            cadence.hour, cadence.minute, 0, 0, 0, -1,\n        ))\n    return candidate\n\n\ndef catch_up(cadence: Cadence, due_at: float, now: float) -> tuple[int, float]:\n''',
    '''def next_run(\n    cadence: Cadence, after: float, timezone_name: str = DEFAULT_TIMEZONE\n) -> float:\n    """The next moment this should fire, strictly after ``after``.\n\n    Daily schedules use their persisted IANA zone. Interval schedules are\n    elapsed-time cadences; their zone is persisted for display but cannot alter\n    the arithmetic.\n    """\n    if cadence.kind == "every":\n        return after + cadence.seconds\n    if cadence.kind != "daily":\n        raise ScheduleError(f"ukendt cadence-kind {cadence.kind!r}")\n    try:\n        return next_daily_run(\n            hour=cadence.hour,\n            minute=cadence.minute,\n            after=after,\n            timezone_name=timezone_name,\n        )\n    except ScheduleTimeError as exc:\n        raise ScheduleError(str(exc)) from exc\n\n\ndef catch_up(\n    cadence: Cadence, due_at: float, now: float,\n    timezone_name: str = DEFAULT_TIMEZONE,\n) -> tuple[int, float]:\n''',
)

replace_once(
    "worker/app/scheduler.py",
    '''    if cadence.kind != "daily":\n        raise ScheduleError(f"ukendt cadence-kind {cadence.kind!r}")\n    missed = 0\n    due = due_at\n    while due <= now:\n        due = next_run(cadence, due)\n        missed += 1\n    # The one we are firing now is not a miss.\n    return max(0, missed - 1), due\n''',
    '''    if cadence.kind != "daily":\n        raise ScheduleError(f"ukendt cadence-kind {cadence.kind!r}")\n    try:\n        return catch_up_daily(\n            hour=cadence.hour,\n            minute=cadence.minute,\n            due_at=due_at,\n            now=now,\n            timezone_name=timezone_name,\n        )\n    except ScheduleTimeError as exc:\n        raise ScheduleError(str(exc)) from exc\n''',
)

# Persist the exact interpretation alongside the standing grant.
replace_once(
    "worker/app/scheduler.py",
    "    missed: int\n    enabled: bool\n",
    "    missed: int\n    enabled: bool\n"
    "    timezone: str = DEFAULT_TIMEZONE\n"
    "    misfire_policy: str = MISFIRE_POLICY\n",
)

replace_once(
    "worker/app/scheduler.py",
    '''                       missed INTEGER NOT NULL DEFAULT 0,\n                       enabled INTEGER NOT NULL DEFAULT 1,\n                       created REAL NOT NULL)''',
    '''                       missed INTEGER NOT NULL DEFAULT 0,\n                       enabled INTEGER NOT NULL DEFAULT 1,\n                       timezone TEXT NOT NULL DEFAULT 'Europe/Copenhagen',\n                       misfire_policy TEXT NOT NULL DEFAULT 'run_once',\n                       created REAL NOT NULL)''',
)

replace_once(
    "worker/app/scheduler.py",
    '''            if "revision" not in scols:\n                self._conn.execute(\n                    "ALTER TABLE schedules ADD COLUMN "\n                    "revision INTEGER NOT NULL DEFAULT 0")\n''',
    '''            if "revision" not in scols:\n                self._conn.execute(\n                    "ALTER TABLE schedules ADD COLUMN "\n                    "revision INTEGER NOT NULL DEFAULT 0")\n            # T-017: old rows used the rig's host timezone implicitly. The\n            # migration freezes that historical meaning as Copenhagen instead\n            # of silently adopting a later Windows timezone change.\n            if "timezone" not in scols:\n                self._conn.execute(\n                    "ALTER TABLE schedules ADD COLUMN timezone TEXT NOT NULL "\n                    "DEFAULT 'Europe/Copenhagen'")\n            if "misfire_policy" not in scols:\n                self._conn.execute(\n                    "ALTER TABLE schedules ADD COLUMN misfire_policy TEXT NOT NULL "\n                    "DEFAULT 'run_once'")\n''',
)

replace_once(
    "worker/app/scheduler.py",
    '''    def create(self, tool: str, args: dict, cadence: str, *,\n               approve_write: bool = False, ttl_days: int = DEFAULT_TTL_DAYS,\n               max_runs: int = DEFAULT_MAX_RUNS, now: float | None = None,\n               receipt: dict | None = None) -> Schedule:\n''',
    '''    def create(self, tool: str, args: dict, cadence: str, *,\n               approve_write: bool = False, ttl_days: int = DEFAULT_TTL_DAYS,\n               max_runs: int = DEFAULT_MAX_RUNS, now: float | None = None,\n               receipt: dict | None = None,\n               timezone_name: str = DEFAULT_TIMEZONE,\n               misfire_policy: str = MISFIRE_POLICY) -> Schedule:\n''',
)

replace_once(
    "worker/app/scheduler.py",
    '''        now = time.time() if now is None else now\n        cad = parse_cadence(cadence)          # raises before anything is stored\n        if ttl_days <= 0:\n''',
    '''        now = time.time() if now is None else now\n        cad = parse_cadence(cadence)          # raises before anything is stored\n        try:\n            zone = validate_timezone(timezone_name).key\n        except ScheduleTimeError as exc:\n            raise ScheduleError(str(exc)) from exc\n        if misfire_policy != MISFIRE_POLICY:\n            raise ScheduleError(\n                f"ukendt misfire-policy {misfire_policy!r}; "\n                f"kun {MISFIRE_POLICY!r} støttes")\n        if ttl_days <= 0:\n''',
)

replace_once(
    "worker/app/scheduler.py",
    '''            max_runs=max_runs, runs_used=0,\n            due_at=next_run(cad, now), missed=0, enabled=True,\n        )\n''',
    '''            max_runs=max_runs, runs_used=0,\n            due_at=next_run(cad, now, zone), missed=0, enabled=True,\n            timezone=zone, misfire_policy=misfire_policy,\n        )\n''',
)

replace_once(
    "worker/app/scheduler.py",
    '''                "INSERT INTO schedules (id, tool, args, cadence, approved_fingerprint,"\n                " expires_at, max_runs, runs_used, due_at, missed, enabled, created)"\n                " VALUES (?,?,?,?,?,?,?,?,?,?,1,?)",\n                (sched.schedule_id, tool, json.dumps(args, ensure_ascii=False), cadence,\n                 fp, sched.expires_at, max_runs, 0, sched.due_at, 0, now),\n''',
    '''                "INSERT INTO schedules (id, tool, args, cadence, approved_fingerprint,"\n                " expires_at, max_runs, runs_used, due_at, missed, enabled,"\n                " timezone, misfire_policy, created)"\n                " VALUES (?,?,?,?,?,?,?,?,?,?,1,?,?,?)",\n                (sched.schedule_id, tool, json.dumps(args, ensure_ascii=False), cadence,\n                 fp, sched.expires_at, max_runs, 0, sched.due_at, 0,\n                 sched.timezone, sched.misfire_policy, now),\n''',
)

# Claim, direct-record and resume all use the stored zone and reject unknown
# persisted policy instead of guessing or replaying.
replace_once(
    "worker/app/scheduler.py",
    '''                        cadence = parse_cadence(schedule.cadence)\n                        missed, next_due = catch_up(cadence, schedule.due_at, now)\n''',
    '''                        cadence = parse_cadence(schedule.cadence)\n                        if schedule.misfire_policy != MISFIRE_POLICY:\n                            raise ScheduleError(\n                                f"ukendt misfire-policy "\n                                f"{schedule.misfire_policy!r}")\n                        missed, next_due = catch_up(\n                            cadence, schedule.due_at, now, schedule.timezone)\n''',
)

replace_once(
    "worker/app/scheduler.py",
    '''                        missed=schedule.missed + missed,\n                        enabled=True,\n                    )\n''',
    '''                        missed=schedule.missed + missed,\n                        enabled=True,\n                        timezone=schedule.timezone,\n                        misfire_policy=schedule.misfire_policy,\n                    )\n''',
)

replace_once(
    "worker/app/scheduler.py",
    '''                cadence = parse_cadence(schedule.cadence)\n                missed, due = catch_up(cadence, schedule.due_at, now)\n''',
    '''                cadence = parse_cadence(schedule.cadence)\n                if schedule.misfire_policy != MISFIRE_POLICY:\n                    raise ScheduleError(\n                        f"ukendt misfire-policy "\n                        f"{schedule.misfire_policy!r}")\n                missed, due = catch_up(\n                    cadence, schedule.due_at, now, schedule.timezone)\n''',
)

replace_once(
    "worker/app/scheduler.py",
    '''            row = self._conn.execute(\n                "SELECT enabled, cadence FROM schedules WHERE id=?",\n                (schedule_id,),\n            ).fetchone()\n''',
    '''            row = self._conn.execute(\n                "SELECT enabled, cadence, timezone, misfire_policy "\n                "FROM schedules WHERE id=?",\n                (schedule_id,),\n            ).fetchone()\n''',
)

replace_once(
    "worker/app/scheduler.py",
    '''            if enabled:\n                due = next_run(parse_cadence(row["cadence"]), now)\n''',
    '''            if enabled:\n                if row["misfire_policy"] != MISFIRE_POLICY:\n                    raise ScheduleError(\n                        f"ukendt misfire-policy {row['misfire_policy']!r}")\n                due = next_run(\n                    parse_cadence(row["cadence"]), now, row["timezone"])\n''',
)

replace_once(
    "worker/app/scheduler.py",
    '''            runs_used=row["runs_used"], due_at=row["due_at"], missed=row["missed"],\n            enabled=bool(row["enabled"]),\n        )\n''',
    '''            runs_used=row["runs_used"], due_at=row["due_at"], missed=row["missed"],\n            enabled=bool(row["enabled"]), timezone=row["timezone"],\n            misfire_policy=row["misfire_policy"],\n        )\n''',
)

# The old cadence unit test deliberately used the CI host timezone. Make that
# test input explicit; persisted schedules are separately tested above.
replace_once(
    "tests/worker_scheduler.py",
    'S.next_run(S.Cadence("every", seconds=900), base)',
    'S.next_run(S.Cadence("every", seconds=900), base, "UTC")',
)
replace_once(
    "tests/worker_scheduler.py",
    'S.next_run(S.Cadence("daily", hour=3, minute=0), base)',
    'S.next_run(S.Cadence("daily", hour=3, minute=0), base, "UTC")',
)
replace_once(
    "tests/worker_scheduler.py",
    'S.next_run(S.Cadence("daily", hour=3, minute=0), early)',
    'S.next_run(S.Cadence("daily", hour=3, minute=0), early, "UTC")',
)
replace_once(
    "tests/worker_scheduler.py",
    'S.next_run, S.Cadence("mystery"), base)',
    'S.next_run, S.Cadence("mystery"), base, "UTC")',
)
replace_once(
    "tests/worker_scheduler.py",
    "S.catch_up(cad, due, now)",
    'S.catch_up(cad, due, now, "UTC")',
)

print("T-017 stage 1 scheduler core applied")
