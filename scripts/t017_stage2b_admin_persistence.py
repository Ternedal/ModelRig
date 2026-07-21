#!/usr/bin/env python3
"""Apply only T-017 ScheduleAdmin create/renew/describe persistence changes.

Temporary transport. Preview/fingerprint code is already proven and is not
modified by this stage. HTTP and token layers remain for later stages.
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PATH = "worker/app/schedule_admin.py"


def replace_once(old: str, new: str) -> None:
    target = ROOT / PATH
    text = target.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(
            f"{PATH}: expected one match, found {count}: {old[:180]!r}"
        )
    target.write_text(text.replace(old, new, 1), encoding="utf-8")


# The store-level renewal is the only direct due-time calculation left in the
# administration layer. It must use the row's persisted interpretation.
replace_once(
    '''                if enabled is True:\n                    # Explicitly starting a renewed schedule is a fresh promise,\n                    # not permission to replay whatever became due while paused.\n                    due_at = next_run(parse_cadence(row["cadence"]), now)\n''',
    '''                if enabled is True:\n                    # Explicitly starting a renewed schedule is a fresh promise,\n                    # not permission to replay whatever became due while paused.\n                    if row["misfire_policy"] != MISFIRE_POLICY:\n                        raise ScheduleError(\n                            f"ukendt misfire-policy "\n                            f"{row['misfire_policy']!r}")\n                    due_at = next_run(\n                        parse_cadence(row["cadence"]), now, row["timezone"])\n''',
)

# Public create consumes the already canonical preview terms and passes exactly
# those values to the durable scheduler store.
replace_once(
    '''    def create(\n        self,\n        tool: str,\n        args: dict[str, Any],\n        cadence: str,\n        *,\n        ttl_days: int = DEFAULT_TTL_DAYS,\n        max_runs: int = DEFAULT_MAX_RUNS,\n        approved_fingerprint: str | None = None,\n        receipt: dict[str, Any] | None = None,\n    ) -> dict[str, Any]:\n''',
    '''    def create(\n        self,\n        tool: str,\n        args: dict[str, Any],\n        cadence: str,\n        *,\n        ttl_days: int = DEFAULT_TTL_DAYS,\n        max_runs: int = DEFAULT_MAX_RUNS,\n        timezone_name: str = DEFAULT_TIMEZONE,\n        misfire_policy: str = MISFIRE_POLICY,\n        approved_fingerprint: str | None = None,\n        receipt: dict[str, Any] | None = None,\n    ) -> dict[str, Any]:\n''',
)
replace_once(
    '''        preview = self.preview(\n            tool, args, cadence, ttl_days=ttl_days, max_runs=max_runs\n        )\n''',
    '''        preview = self.preview(\n            tool, args, cadence, ttl_days=ttl_days, max_runs=max_runs,\n            timezone_name=timezone_name, misfire_policy=misfire_policy,\n        )\n''',
)
replace_once(
    '''                ttl_days=ttl_days,\n                max_runs=max_runs,\n                now=self._clock(),\n                receipt=receipt,\n            )\n''',
    '''                ttl_days=ttl_days,\n                max_runs=max_runs,\n                now=self._clock(),\n                receipt=receipt,\n                timezone_name=preview.timezone,\n                misfire_policy=preview.misfire_policy,\n            )\n''',
)

# Every administration read is server-authoritative: clients get both the UTC
# identity and the local representation calculated from the persisted zone.
replace_once(
    '''            "args": schedule.args,\n            "cadence": schedule.cadence,\n            "risk": risk,\n''',
    '''            "args": schedule.args,\n            "cadence": schedule.cadence,\n            "timezone": schedule.timezone,\n            "misfire_policy": schedule.misfire_policy,\n            "due_at_local": local_due_iso(schedule.due_at, schedule.timezone),\n            "risk": risk,\n''',
)

print("T-017 stage 2B admin persistence applied")
