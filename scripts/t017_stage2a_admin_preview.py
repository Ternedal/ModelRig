#!/usr/bin/env python3
"""Apply only T-017 ScheduleAdmin preview/fingerprint changes.

Temporary transport. Persistence/create/renew output changes are deliberately
left for a later stage.
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
            f"{PATH}: expected one match, found {count}: {old[:160]!r}"
        )
    target.write_text(text.replace(old, new, 1), encoding="utf-8")


replace_once(
    '''    refusal,\n)\n\nMAX_TTL_DAYS''',
    '''    refusal,\n)\nfrom .scheduler_time import (\n    DEFAULT_TIMEZONE,\n    MISFIRE_POLICY,\n    ScheduleTimeError,\n    local_due_iso,\n    validate_timezone,\n)\n\nMAX_TTL_DAYS''',
)
replace_once("_APPROVAL_VERSION = 1", "_APPROVAL_VERSION = 2")
replace_once(
    '''    cadence: str\n    risk: str\n''',
    '''    cadence: str\n    timezone: str\n    misfire_policy: str\n    due_at_local: str\n    risk: str\n''',
)
replace_once(
    '''            "cadence": self.cadence,\n            "risk": self.risk,\n''',
    '''            "cadence": self.cadence,\n            "timezone": self.timezone,\n            "misfire_policy": self.misfire_policy,\n            "due_at_local": self.due_at_local,\n            "risk": self.risk,\n''',
)

replace_once(
    '''    def preview(\n        self,\n        tool: str,\n        args: dict[str, Any],\n        cadence: str,\n        *,\n        ttl_days: int = DEFAULT_TTL_DAYS,\n        max_runs: int = DEFAULT_MAX_RUNS,\n    ) -> SchedulePreview:\n''',
    '''    def preview(\n        self,\n        tool: str,\n        args: dict[str, Any],\n        cadence: str,\n        *,\n        ttl_days: int = DEFAULT_TTL_DAYS,\n        max_runs: int = DEFAULT_MAX_RUNS,\n        timezone_name: str = DEFAULT_TIMEZONE,\n        misfire_policy: str = MISFIRE_POLICY,\n    ) -> SchedulePreview:\n''',
)
replace_once(
    '''            args=args,\n            cadence=cadence,\n            ttl_days=ttl_days,\n            max_runs=max_runs,\n            enable=True,\n''',
    '''            args=args,\n            cadence=cadence,\n            timezone_name=timezone_name,\n            misfire_policy=misfire_policy,\n            ttl_days=ttl_days,\n            max_runs=max_runs,\n            enable=True,\n''',
)

replace_once(
    '''        return self._preview(\n            operation="renew",\n            schedule_id=schedule_id,\n            tool=current.tool,\n            args=current.args,\n            cadence=current.cadence,\n            ttl_days=ttl_days,\n            max_runs=max_runs,\n            enable=enable,\n        )\n''',
    '''        return self._preview(\n            operation="renew",\n            schedule_id=schedule_id,\n            tool=current.tool,\n            args=current.args,\n            cadence=current.cadence,\n            timezone_name=current.timezone,\n            misfire_policy=current.misfire_policy,\n            ttl_days=ttl_days,\n            max_runs=max_runs,\n            enable=enable,\n        )\n''',
)
replace_once(
    '''            preview = self._preview(\n                operation="renew",\n                schedule_id=schedule_id,\n                tool=current.tool,\n                args=current.args,\n                cadence=current.cadence,\n                ttl_days=ttl_days,\n                max_runs=max_runs,\n                enable=enable,\n            )\n''',
    '''            preview = self._preview(\n                operation="renew",\n                schedule_id=schedule_id,\n                tool=current.tool,\n                args=current.args,\n                cadence=current.cadence,\n                timezone_name=current.timezone,\n                misfire_policy=current.misfire_policy,\n                ttl_days=ttl_days,\n                max_runs=max_runs,\n                enable=enable,\n            )\n''',
)

replace_once(
    '''    def _preview(\n        self,\n        *,\n        operation: str,\n        schedule_id: str | None,\n        tool: str,\n        args: dict[str, Any],\n        cadence: str,\n        ttl_days: int,\n        max_runs: int,\n        enable: bool | None,\n    ) -> SchedulePreview:\n''',
    '''    def _preview(\n        self,\n        *,\n        operation: str,\n        schedule_id: str | None,\n        tool: str,\n        args: dict[str, Any],\n        cadence: str,\n        timezone_name: str,\n        misfire_policy: str,\n        ttl_days: int,\n        max_runs: int,\n        enable: bool | None,\n    ) -> SchedulePreview:\n''',
)
replace_once(
    '''        self._validate_bounds(ttl_days, max_runs)\n        self._validate_args(args)\n        registry = self._registry_factory()\n''',
    '''        self._validate_bounds(ttl_days, max_runs)\n        self._validate_args(args)\n        try:\n            zone = validate_timezone(timezone_name).key\n        except ScheduleTimeError as exc:\n            raise ScheduleAdminError(str(exc)) from exc\n        if misfire_policy != MISFIRE_POLICY:\n            raise ScheduleAdminError(\n                f"ukendt misfire-policy {misfire_policy!r}; "\n                f"kun {MISFIRE_POLICY!r} støttes")\n        registry = self._registry_factory()\n''',
)
replace_once(
    '''        self._validate_tool_args(spec, args)\n        cad = parse_cadence(cadence)\n        now = self._clock()\n        try:\n''',
    '''        self._validate_tool_args(spec, args)\n        cad = parse_cadence(cadence)\n        now = self._clock()\n        due_at = next_run(cad, now, zone)\n        try:\n''',
)
replace_once(
    '''                args=args,\n                cadence=cadence,\n                ttl_days=ttl_days,\n                max_runs=max_runs,\n                enable=enable,\n''',
    '''                args=args,\n                cadence=cadence,\n                timezone_name=zone,\n                misfire_policy=misfire_policy,\n                ttl_days=ttl_days,\n                max_runs=max_runs,\n                enable=enable,\n''',
)
replace_once(
    '''            args=dict(args),\n            cadence=cadence,\n            risk=risk,\n''',
    '''            args=dict(args),\n            cadence=cadence,\n            timezone=zone,\n            misfire_policy=misfire_policy,\n            due_at_local=local_due_iso(due_at, zone),\n            risk=risk,\n''',
)
replace_once(
    '''            approval_fingerprint=approval_fp,\n            due_at=next_run(cad, now),\n            expires_at=now + ttl_days * 86400,\n''',
    '''            approval_fingerprint=approval_fp,\n            due_at=due_at,\n            expires_at=now + ttl_days * 86400,\n''',
)

replace_once(
    '''    def _grant_fingerprint(\n        *,\n        operation: str,\n        schedule_id: str | None,\n        tool: str,\n        args: dict[str, Any],\n        cadence: str,\n        ttl_days: int,\n        max_runs: int,\n        enable: bool | None,\n    ) -> str:\n''',
    '''    def _grant_fingerprint(\n        *,\n        operation: str,\n        schedule_id: str | None,\n        tool: str,\n        args: dict[str, Any],\n        cadence: str,\n        timezone_name: str,\n        misfire_policy: str,\n        ttl_days: int,\n        max_runs: int,\n        enable: bool | None,\n    ) -> str:\n''',
)
replace_once(
    '''            "args": args,\n            "cadence": cadence,\n            "ttl_days": ttl_days,\n''',
    '''            "args": args,\n            "cadence": cadence,\n            "timezone": timezone_name,\n            "misfire_policy": misfire_policy,\n            "ttl_days": ttl_days,\n''',
)
replace_once(
    '''                "scheduled write approval does not match the previewed action, cadence, expiry, budget and enable state"\n''',
    '''                "scheduled write approval does not match the previewed action, cadence, timezone, misfire policy, expiry, budget and enable state"\n''',
)

print("T-017 stage 2A admin preview applied")
