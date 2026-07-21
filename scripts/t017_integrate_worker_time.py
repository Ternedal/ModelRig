#!/usr/bin/env python3
"""Apply the reviewed T-017 worker integration as exact substitutions.

Temporary transport only. The trusted diagnostics workflow removes this file
before testing/committing the resulting canonical tree.
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_once(path: str, old: str, new: str) -> None:
    target = ROOT / path
    text = target.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{path}: expected one match, found {count}: {old[:100]!r}")
    target.write_text(text.replace(old, new, 1), encoding="utf-8")


# ---------------------------------------------------------------------------
# Canonical scheduler + persistence
# ---------------------------------------------------------------------------
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
    '''def next_run(\n    cadence: Cadence, after: float, timezone_name: str = DEFAULT_TIMEZONE\n) -> float:\n    """The next moment this should fire, strictly after ``after``.\n\n    Daily schedules are evaluated in their persisted IANA zone. Interval\n    schedules are elapsed-time cadences; their zone is still persisted and\n    displayed, but cannot change the arithmetic.\n    """\n    if cadence.kind == "every":\n        return after + cadence.seconds\n    if cadence.kind != "daily":\n        raise ScheduleError(f"ukendt cadence-kind {cadence.kind!r}")\n    try:\n        return next_daily_run(\n            hour=cadence.hour,\n            minute=cadence.minute,\n            after=after,\n            timezone_name=timezone_name,\n        )\n    except ScheduleTimeError as exc:\n        raise ScheduleError(str(exc)) from exc\n\n\ndef catch_up(\n    cadence: Cadence, due_at: float, now: float,\n    timezone_name: str = DEFAULT_TIMEZONE,\n) -> tuple[int, float]:\n''',
)
replace_once(
    "worker/app/scheduler.py",
    '''    if cadence.kind != "daily":\n        raise ScheduleError(f"ukendt cadence-kind {cadence.kind!r}")\n    missed = 0\n    due = due_at\n    while due <= now:\n        due = next_run(cadence, due)\n        missed += 1\n    # The one we are firing now is not a miss.\n    return max(0, missed - 1), due\n''',
    '''    if cadence.kind != "daily":\n        raise ScheduleError(f"ukendt cadence-kind {cadence.kind!r}")\n    try:\n        return catch_up_daily(\n            hour=cadence.hour,\n            minute=cadence.minute,\n            due_at=due_at,\n            now=now,\n            timezone_name=timezone_name,\n        )\n    except ScheduleTimeError as exc:\n        raise ScheduleError(str(exc)) from exc\n''',
)
replace_once(
    "worker/app/scheduler.py",
    "    missed: int\n    enabled: bool\n",
    "    missed: int\n    enabled: bool\n    timezone: str = DEFAULT_TIMEZONE\n    misfire_policy: str = MISFIRE_POLICY\n",
)
replace_once(
    "worker/app/scheduler.py",
    '''                       missed INTEGER NOT NULL DEFAULT 0,\n                       enabled INTEGER NOT NULL DEFAULT 1,\n                       created REAL NOT NULL)''',
    '''                       missed INTEGER NOT NULL DEFAULT 0,\n                       enabled INTEGER NOT NULL DEFAULT 1,\n                       timezone TEXT NOT NULL DEFAULT 'Europe/Copenhagen',\n                       misfire_policy TEXT NOT NULL DEFAULT 'run_once',\n                       created REAL NOT NULL)''',
)
replace_once(
    "worker/app/scheduler.py",
    '''            if "revision" not in scols:\n                self._conn.execute(\n                    "ALTER TABLE schedules ADD COLUMN "\n                    "revision INTEGER NOT NULL DEFAULT 0")\n''',
    '''            if "revision" not in scols:\n                self._conn.execute(\n                    "ALTER TABLE schedules ADD COLUMN "\n                    "revision INTEGER NOT NULL DEFAULT 0")\n            # T-017: old rows used the host timezone implicitly. The migration\n            # makes their meaning explicit and stable on the Copenhagen rig.\n            if "timezone" not in scols:\n                self._conn.execute(\n                    "ALTER TABLE schedules ADD COLUMN timezone TEXT NOT NULL "\n                    "DEFAULT 'Europe/Copenhagen'")\n            if "misfire_policy" not in scols:\n                self._conn.execute(\n                    "ALTER TABLE schedules ADD COLUMN misfire_policy TEXT NOT NULL "\n                    "DEFAULT 'run_once'")\n''',
)
replace_once(
    "worker/app/scheduler.py",
    '''    def create(self, tool: str, args: dict, cadence: str, *,\n               approve_write: bool = False, ttl_days: int = DEFAULT_TTL_DAYS,\n               max_runs: int = DEFAULT_MAX_RUNS, now: float | None = None,\n               receipt: dict | None = None) -> Schedule:\n''',
    '''    def create(self, tool: str, args: dict, cadence: str, *,\n               approve_write: bool = False, ttl_days: int = DEFAULT_TTL_DAYS,\n               max_runs: int = DEFAULT_MAX_RUNS, now: float | None = None,\n               receipt: dict | None = None,\n               timezone_name: str = DEFAULT_TIMEZONE,\n               misfire_policy: str = MISFIRE_POLICY) -> Schedule:\n''',
)
replace_once(
    "worker/app/scheduler.py",
    '''        now = time.time() if now is None else now\n        cad = parse_cadence(cadence)          # raises before anything is stored\n        if ttl_days <= 0:\n''',
    '''        now = time.time() if now is None else now\n        cad = parse_cadence(cadence)          # raises before anything is stored\n        try:\n            zone = validate_timezone(timezone_name).key\n        except ScheduleTimeError as exc:\n            raise ScheduleError(str(exc)) from exc\n        if misfire_policy != MISFIRE_POLICY:\n            raise ScheduleError(\n                f"ukendt misfire-policy {misfire_policy!r}; kun {MISFIRE_POLICY!r} støttes")\n        if ttl_days <= 0:\n''',
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
replace_once(
    "worker/app/scheduler.py",
    '''                        cadence = parse_cadence(schedule.cadence)\n                        missed, next_due = catch_up(cadence, schedule.due_at, now)\n''',
    '''                        cadence = parse_cadence(schedule.cadence)\n                        if schedule.misfire_policy != MISFIRE_POLICY:\n                            raise ScheduleError(\n                                f"ukendt misfire-policy {schedule.misfire_policy!r}")\n                        missed, next_due = catch_up(\n                            cadence, schedule.due_at, now, schedule.timezone)\n''',
)
replace_once(
    "worker/app/scheduler.py",
    '''                        missed=schedule.missed + missed,\n                        enabled=True,\n                    )\n''',
    '''                        missed=schedule.missed + missed,\n                        enabled=True,\n                        timezone=schedule.timezone,\n                        misfire_policy=schedule.misfire_policy,\n                    )\n''',
)
replace_once(
    "worker/app/scheduler.py",
    '''                cadence = parse_cadence(schedule.cadence)\n                missed, due = catch_up(cadence, schedule.due_at, now)\n''',
    '''                cadence = parse_cadence(schedule.cadence)\n                if schedule.misfire_policy != MISFIRE_POLICY:\n                    raise ScheduleError(\n                        f"ukendt misfire-policy {schedule.misfire_policy!r}")\n                missed, due = catch_up(\n                    cadence, schedule.due_at, now, schedule.timezone)\n''',
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

# ---------------------------------------------------------------------------
# Human administration, preview and approval binding
# ---------------------------------------------------------------------------
replace_once(
    "worker/app/schedule_admin.py",
    '''    refusal,\n)\n\nMAX_TTL_DAYS''',
    '''    refusal,\n)\nfrom .scheduler_time import (\n    DEFAULT_TIMEZONE,\n    MISFIRE_POLICY,\n    ScheduleTimeError,\n    local_due_iso,\n    validate_timezone,\n)\n\nMAX_TTL_DAYS''',
)
replace_once("worker/app/schedule_admin.py", "_APPROVAL_VERSION = 1", "_APPROVAL_VERSION = 2")
replace_once(
    "worker/app/schedule_admin.py",
    '''    cadence: str\n    risk: str\n''',
    '''    cadence: str\n    timezone: str\n    misfire_policy: str\n    due_at_local: str\n    risk: str\n''',
)
replace_once(
    "worker/app/schedule_admin.py",
    '''            "cadence": self.cadence,\n            "risk": self.risk,\n''',
    '''            "cadence": self.cadence,\n            "timezone": self.timezone,\n            "misfire_policy": self.misfire_policy,\n            "due_at_local": self.due_at_local,\n            "risk": self.risk,\n''',
)
replace_once(
    "worker/app/schedule_admin.py",
    '''                    due_at = next_run(parse_cadence(row["cadence"]), now)\n''',
    '''                    due_at = next_run(\n                        parse_cadence(row["cadence"]), now, row["timezone"])\n''',
)
replace_once(
    "worker/app/schedule_admin.py",
    '''        ttl_days: int = DEFAULT_TTL_DAYS,\n        max_runs: int = DEFAULT_MAX_RUNS,\n    ) -> SchedulePreview:\n''',
    '''        ttl_days: int = DEFAULT_TTL_DAYS,\n        max_runs: int = DEFAULT_MAX_RUNS,\n        timezone_name: str = DEFAULT_TIMEZONE,\n        misfire_policy: str = MISFIRE_POLICY,\n    ) -> SchedulePreview:\n''',
)
replace_once(
    "worker/app/schedule_admin.py",
    '''            cadence=cadence,\n            ttl_days=ttl_days,\n''',
    '''            cadence=cadence,\n            timezone_name=timezone_name,\n            misfire_policy=misfire_policy,\n            ttl_days=ttl_days,\n''',
)
replace_once(
    "worker/app/schedule_admin.py",
    '''            cadence=current.cadence,\n            ttl_days=ttl_days,\n''',
    '''            cadence=current.cadence,\n            timezone_name=current.timezone,\n            misfire_policy=current.misfire_policy,\n            ttl_days=ttl_days,\n''',
)
replace_once(
    "worker/app/schedule_admin.py",
    '''        max_runs: int = DEFAULT_MAX_RUNS,\n        approved_fingerprint: str | None = None,\n''',
    '''        max_runs: int = DEFAULT_MAX_RUNS,\n        timezone_name: str = DEFAULT_TIMEZONE,\n        misfire_policy: str = MISFIRE_POLICY,\n        approved_fingerprint: str | None = None,\n''',
)
replace_once(
    "worker/app/schedule_admin.py",
    '''        preview = self.preview(\n            tool, args, cadence, ttl_days=ttl_days, max_runs=max_runs\n        )\n''',
    '''        preview = self.preview(\n            tool, args, cadence, ttl_days=ttl_days, max_runs=max_runs,\n            timezone_name=timezone_name, misfire_policy=misfire_policy,\n        )\n''',
)
replace_once(
    "worker/app/schedule_admin.py",
    '''                max_runs=max_runs,\n                now=self._clock(),\n                receipt=receipt,\n''',
    '''                max_runs=max_runs,\n                now=self._clock(),\n                receipt=receipt,\n                timezone_name=preview.timezone,\n                misfire_policy=preview.misfire_policy,\n''',
)
# The renew() method contains a second immutable-action preview call.
needle = '''                cadence=current.cadence,\n                ttl_days=ttl_days,\n                max_runs=max_runs,\n                enable=enable,\n'''
replace_once(
    "worker/app/schedule_admin.py",
    needle,
    '''                cadence=current.cadence,\n                timezone_name=current.timezone,\n                misfire_policy=current.misfire_policy,\n                ttl_days=ttl_days,\n                max_runs=max_runs,\n                enable=enable,\n''',
)
replace_once(
    "worker/app/schedule_admin.py",
    '''            "cadence": schedule.cadence,\n            "risk": risk,\n''',
    '''            "cadence": schedule.cadence,\n            "timezone": schedule.timezone,\n            "misfire_policy": schedule.misfire_policy,\n            "due_at_local": local_due_iso(schedule.due_at, schedule.timezone),\n            "risk": risk,\n''',
)
replace_once(
    "worker/app/schedule_admin.py",
    '''        cadence: str,\n        ttl_days: int,\n''',
    '''        cadence: str,\n        timezone_name: str,\n        misfire_policy: str,\n        ttl_days: int,\n''',
)
replace_once(
    "worker/app/schedule_admin.py",
    '''        self._validate_bounds(ttl_days, max_runs)\n        self._validate_args(args)\n''',
    '''        self._validate_bounds(ttl_days, max_runs)\n        self._validate_args(args)\n        try:\n            zone = validate_timezone(timezone_name).key\n        except ScheduleTimeError as exc:\n            raise ScheduleAdminError(str(exc)) from exc\n        if misfire_policy != MISFIRE_POLICY:\n            raise ScheduleAdminError(\n                f"ukendt misfire-policy {misfire_policy!r}; kun {MISFIRE_POLICY!r} støttes")\n''',
)
replace_once(
    "worker/app/schedule_admin.py",
    '''                cadence=cadence,\n                ttl_days=ttl_days,\n''',
    '''                cadence=cadence,\n                timezone_name=zone,\n                misfire_policy=misfire_policy,\n                ttl_days=ttl_days,\n''',
)
replace_once(
    "worker/app/schedule_admin.py",
    '''            cadence=cadence,\n            risk=risk,\n''',
    '''            cadence=cadence,\n            timezone=zone,\n            misfire_policy=misfire_policy,\n            due_at_local=local_due_iso(next_run(cad, now, zone), zone),\n            risk=risk,\n''',
)
replace_once(
    "worker/app/schedule_admin.py",
    '''            due_at=next_run(cad, now),\n            expires_at=now + ttl_days * 86400,\n''',
    '''            due_at=next_run(cad, now, zone),\n            expires_at=now + ttl_days * 86400,\n''',
)
replace_once(
    "worker/app/schedule_admin.py",
    '''        cadence: str,\n        ttl_days: int,\n        max_runs: int,\n''',
    '''        cadence: str,\n        timezone_name: str,\n        misfire_policy: str,\n        ttl_days: int,\n        max_runs: int,\n''',
)
replace_once(
    "worker/app/schedule_admin.py",
    '''            "cadence": cadence,\n            "ttl_days": ttl_days,\n''',
    '''            "cadence": cadence,\n            "timezone": timezone_name,\n            "misfire_policy": misfire_policy,\n            "ttl_days": ttl_days,\n''',
)

# ---------------------------------------------------------------------------
# Worker API defaults and canonical arguments
# ---------------------------------------------------------------------------
replace_once(
    "worker/app/schedule_api.py",
    '''from .scheduler import DEFAULT_MAX_RUNS, DEFAULT_TTL_DAYS, ScheduleError, enabled\n''',
    '''from .scheduler import DEFAULT_MAX_RUNS, DEFAULT_TTL_DAYS, ScheduleError, enabled\nfrom .scheduler_time import DEFAULT_TIMEZONE, MISFIRE_POLICY\n''',
)
replace_once(
    "worker/app/schedule_api.py",
    '''    cadence: str = Field(min_length=1, max_length=100)\n    ttl_days: int = Field(default=DEFAULT_TTL_DAYS, ge=1, le=MAX_TTL_DAYS)\n''',
    '''    cadence: str = Field(min_length=1, max_length=100)\n    timezone: str = Field(default=DEFAULT_TIMEZONE, min_length=1, max_length=100)\n    misfire_policy: str = Field(default=MISFIRE_POLICY, min_length=1, max_length=30)\n    ttl_days: int = Field(default=DEFAULT_TTL_DAYS, ge=1, le=MAX_TTL_DAYS)\n''',
)
# Preview route and create route each pass the same new immutable terms.
for _ in range(2):
    replace_once(
        "worker/app/schedule_api.py",
        '''                req.cadence,\n                ttl_days=req.ttl_days,\n''',
        '''                req.cadence,\n                timezone_name=req.timezone,\n                misfire_policy=req.misfire_policy,\n                ttl_days=req.ttl_days,\n''',
    )
replace_once(
    "worker/app/schedule_api.py",
    '''                max_runs=req.max_runs,\n                approved_fingerprint=approved_fingerprint,\n''',
    '''                max_runs=req.max_runs,\n                timezone_name=req.timezone,\n                misfire_policy=req.misfire_policy,\n                approved_fingerprint=approved_fingerprint,\n''',
)

# ---------------------------------------------------------------------------
# Worker-side signed approval verification. V1 remains valid only for the
# immutable legacy default zone/policy; every non-default zone requires V2.
# ---------------------------------------------------------------------------
replace_once(
    "worker/app/schedule_approval.py",
    '''from . import paths as _paths\n''',
    '''from . import paths as _paths\nfrom .scheduler_time import DEFAULT_TIMEZONE, MISFIRE_POLICY\n''',
)
replace_once(
    "worker/app/schedule_approval.py",
    '''    if not isinstance(claims, dict) or claims.get("v") != 1:\n        raise ScheduleApprovalError("schedule approval token version is unsupported")\n''',
    '''    if not isinstance(claims, dict) or claims.get("v") not in (1, 2):\n        raise ScheduleApprovalError("schedule approval token version is unsupported")\n    version = claims["v"]\n''',
)
replace_once(
    "worker/app/schedule_approval.py",
    '''    expected = {\n        "operation": getattr(preview, "operation", None),\n''',
    '''    preview_timezone = getattr(preview, "timezone", DEFAULT_TIMEZONE)\n    preview_misfire = getattr(preview, "misfire_policy", MISFIRE_POLICY)\n    if version == 1 and (\n        preview_timezone != DEFAULT_TIMEZONE or preview_misfire != MISFIRE_POLICY\n    ):\n        raise ScheduleApprovalError(\n            "legacy schedule approval cannot authorize a non-default timezone or misfire policy")\n\n    expected = {\n        "operation": getattr(preview, "operation", None),\n''',
)
replace_once(
    "worker/app/schedule_approval.py",
    '''        "approval_fingerprint": getattr(preview, "approval_fingerprint", None),\n    }\n    for name, value in expected.items():\n''',
    '''        "approval_fingerprint": getattr(preview, "approval_fingerprint", None),\n    }\n    if version == 2:\n        expected["timezone"] = preview_timezone\n        expected["misfire_policy"] = preview_misfire\n    for name, value in expected.items():\n''',
)
replace_once(
    "worker/app/schedule_approval.py",
    '''                "schedule approval does not match the previewed action, cadence, expiry, budget or enable state"\n''',
    '''                "schedule approval does not match the previewed action, cadence, timezone, misfire policy, expiry, budget or enable state"\n''',
)

# ---------------------------------------------------------------------------
# Existing raw cadence tests become explicit about UTC; persisted schedules use
# their own stored timezone and therefore never read the host zone.
# ---------------------------------------------------------------------------
path = ROOT / "tests/worker_scheduler.py"
text = path.read_text(encoding="utf-8")
text = text.replace("S.next_run(S.Cadence(\"every\", seconds=900), base)",
                    "S.next_run(S.Cadence(\"every\", seconds=900), base, \"UTC\")")
text = text.replace("S.next_run(S.Cadence(\"daily\", hour=3, minute=0), base)",
                    "S.next_run(S.Cadence(\"daily\", hour=3, minute=0), base, \"UTC\")")
text = text.replace("S.next_run(S.Cadence(\"daily\", hour=3, minute=0), early)",
                    "S.next_run(S.Cadence(\"daily\", hour=3, minute=0), early, \"UTC\")")
text = text.replace("S.next_run, S.Cadence(\"mystery\"), base)",
                    "S.next_run, S.Cadence(\"mystery\"), base, \"UTC\")")
text = text.replace("S.catch_up(cad, due, now)", "S.catch_up(cad, due, now, \"UTC\")")
path.write_text(text, encoding="utf-8")

# ---------------------------------------------------------------------------
# Focused integration contract: migration, persistence, approval binding,
# server-authoritative display and occurrence-ledger behaviour around fall-back.
# ---------------------------------------------------------------------------
(ROOT / "tests/worker_scheduler_time_integration.py").write_text(r'''#!/usr/bin/env python3
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import sys
import tempfile
from datetime import date

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "worker"))

from app.schedule_admin import ScheduleAdmin  # noqa: E402
from app.schedule_approval import ScheduleApprovalError, verify_schedule_approval  # noqa: E402
from app.scheduler import ScheduleStore  # noqa: E402
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
    params = {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]}

    @staticmethod
    def human_summary(args):
        return f"append {args['text']}"


root = tempfile.mkdtemp(prefix="t017-")
legacy_path = os.path.join(root, "legacy.db")
conn = sqlite3.connect(legacy_path)
conn.execute("""CREATE TABLE schedules (
    id TEXT PRIMARY KEY, tool TEXT NOT NULL, args TEXT NOT NULL,
    cadence TEXT NOT NULL, approved_fingerprint TEXT,
    expires_at REAL NOT NULL, max_runs INTEGER NOT NULL DEFAULT 0,
    runs_used INTEGER NOT NULL DEFAULT 0, due_at REAL NOT NULL,
    missed INTEGER NOT NULL DEFAULT 0, enabled INTEGER NOT NULL DEFAULT 1,
    created REAL NOT NULL)""")
conn.execute(
    "INSERT INTO schedules VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
    ("legacy", "clock", "{}", "daily:08:00", None, 2_000_000_000.0, 0, 0,
     1_900_000_000.0, 0, 1, 1_800_000_000.0),
)
conn.commit()
conn.close()

legacy_store = ScheduleStore(legacy_path)
legacy = legacy_store.get("legacy")
check(legacy.timezone == "Europe/Copenhagen", "legacy row migrates to explicit Copenhagen timezone")
check(legacy.misfire_policy == "run_once", "legacy row migrates to explicit run-once policy")
legacy_store.close()

store_path = os.path.join(root, "new.db")
store = ScheduleStore(store_path)
spring_before = resolve_local_daily(date(2026, 3, 28), 10, 0, "Europe/Copenhagen").timestamp()
schedule = store.create(
    "clock", {}, "daily:02:30", now=spring_before,
    timezone_name="Europe/Copenhagen", misfire_policy="run_once",
)
check(schedule.timezone == "Europe/Copenhagen", "new schedule persists selected IANA zone")
check(schedule.misfire_policy == "run_once", "new schedule persists misfire policy")
check(
    store.get(schedule.schedule_id).due_at == schedule.due_at,
    "timezone-bound due time survives database roundtrip",
)
store.close()

admin = ScheduleAdmin(
    store_factory=lambda: ScheduleStore(os.path.join(root, "admin.db")),
    registry_factory=lambda: {"append": FakeTool()},
    clock=lambda: spring_before,
)
args = {"text": "DST"}
cph = admin.preview("append", args, "daily:02:30", timezone_name="Europe/Copenhagen")
nyc = admin.preview("append", args, "daily:02:30", timezone_name="America/New_York")
check(cph.timezone == "Europe/Copenhagen" and cph.misfire_policy == "run_once",
      "preview exposes canonical timezone and misfire policy")
check(cph.due_at_local.endswith("+01:00") or cph.due_at_local.endswith("+02:00"),
      "preview exposes server-authoritative local due time with offset")
check(cph.approval_fingerprint != nyc.approval_fingerprint,
      "changing timezone changes the standing-grant approval fingerprint")

secret = b"0123456789abcdef0123456789abcdef-test"

def signed(preview, version):
    claims = {
        "v": version,
        "nonce": base64.urlsafe_b64encode(secrets.token_bytes(32)).decode().rstrip("="),
        "device_id": "pixel",
        "operation": preview.operation,
        "schedule_id": preview.schedule_id,
        "tool": preview.tool,
        "args": preview.args,
        "cadence": preview.cadence,
        "ttl_days": preview.ttl_days,
        "max_runs": preview.max_runs,
        "enable": preview.enable,
        "action_fingerprint": preview.action_fingerprint,
        "approval_fingerprint": preview.approval_fingerprint,
        "issued_at": 1_800_000_000,
        "expires_at": 1_800_000_120,
    }
    if version == 2:
        claims["timezone"] = preview.timezone
        claims["misfire_policy"] = preview.misfire_policy
    raw = json.dumps(claims, sort_keys=True, separators=(",", ":")).encode()
    payload = base64.urlsafe_b64encode(raw).decode().rstrip("=")
    sig = hmac.new(secret, payload.encode(), hashlib.sha256).digest()
    return payload + "." + base64.urlsafe_b64encode(sig).decode().rstrip("=")

verify_schedule_approval(
    signed(cph, 2), cph, now=1_800_000_001, secret_factory=lambda: secret)
check(True, "V2 approval binds timezone and misfire policy")
try:
    verify_schedule_approval(
        signed(nyc, 1), nyc, now=1_800_000_001, secret_factory=lambda: secret)
    legacy_refused = False
except ScheduleApprovalError as exc:
    legacy_refused = "legacy" in str(exc)
check(legacy_refused, "legacy token cannot authorize a non-default timezone")

fall_path = os.path.join(root, "fall.db")
owner = ScheduleStore(fall_path)
peer = ScheduleStore(fall_path)
fall_due = resolve_local_daily(date(2026, 10, 25), 2, 30, "Europe/Copenhagen").timestamp()
fall_schedule = owner.create(
    "clock", {}, "daily:02:30", now=fall_due - 60,
    timezone_name="Europe/Copenhagen",
)
check(fall_schedule.due_at == fall_due, "fall-back schedule selects first occurrence")
claims = owner.claim_due(now=fall_due + 90 * 60)
check(len(claims) == 1, "fall-back overlap yields one claim, not two")
check(peer.claim_due(now=fall_due + 90 * 60) == [], "peer cannot claim a hidden second overlap occurrence")
check(claims[0].schedule.due_at > fall_due + 20 * 3600,
      "claimed fall-back occurrence advances to the next local day")
owner.close()
peer.close()

print(f"scheduler time integration: {passed} passed, {failed} failed")
if failed:
    raise SystemExit(1)
''', encoding="utf-8")

print("T-017 worker integration patch applied")
