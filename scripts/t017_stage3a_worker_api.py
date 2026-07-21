#!/usr/bin/env python3
"""Apply only T-017 worker HTTP request-field forwarding.

Temporary transport. Backend claim structs and the explicit v2 token envelope
are deliberately deferred to stage 3B.
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PATH = "worker/app/schedule_api.py"


def replace_once(old: str, new: str) -> None:
    target = ROOT / PATH
    text = target.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(
            f"{PATH}: expected one match, found {count}: {old[:180]!r}"
        )
    target.write_text(text.replace(old, new, 1), encoding="utf-8")


replace_once(
    '''from .scheduler import DEFAULT_MAX_RUNS, DEFAULT_TTL_DAYS, ScheduleError, enabled\n''',
    '''from .scheduler import DEFAULT_MAX_RUNS, DEFAULT_TTL_DAYS, ScheduleError, enabled\nfrom .scheduler_time import DEFAULT_TIMEZONE, MISFIRE_POLICY\n''',
)
replace_once(
    '''    cadence: str = Field(min_length=1, max_length=100)\n    ttl_days: int = Field(default=DEFAULT_TTL_DAYS, ge=1, le=MAX_TTL_DAYS)\n''',
    '''    cadence: str = Field(min_length=1, max_length=100)\n    timezone: str = Field(default=DEFAULT_TIMEZONE, min_length=1, max_length=100)\n    misfire_policy: str = Field(default=MISFIRE_POLICY, min_length=1, max_length=32)\n    ttl_days: int = Field(default=DEFAULT_TTL_DAYS, ge=1, le=MAX_TTL_DAYS)\n''',
)

# Preview route only. The complete function-local block prevents the same call
# shape in create_schedule from being selected accidentally.
replace_once(
    '''    @router.post("/preview")\n    def preview_schedule(\n        request: Request, req: PreviewScheduleReq\n    ) -> dict[str, Any]:\n        _require_operator(request, operator_allowed)\n        try:\n            preview = service.preview(\n                req.tool,\n                req.args,\n                req.cadence,\n                ttl_days=req.ttl_days,\n                max_runs=req.max_runs,\n            )\n        except (ScheduleAdminError, ScheduleError) as exc:\n''',
    '''    @router.post("/preview")\n    def preview_schedule(\n        request: Request, req: PreviewScheduleReq\n    ) -> dict[str, Any]:\n        _require_operator(request, operator_allowed)\n        try:\n            preview = service.preview(\n                req.tool,\n                req.args,\n                req.cadence,\n                ttl_days=req.ttl_days,\n                max_runs=req.max_runs,\n                timezone_name=req.timezone,\n                misfire_policy=req.misfire_policy,\n            )\n        except (ScheduleAdminError, ScheduleError) as exc:\n''',
)

# The create route has its own preview call and then persists the same canonical
# terms. Anchor the complete route-local blocks so no renewal path is touched.
replace_once(
    '''            preview = service.preview(\n                req.tool,\n                req.args,\n                req.cadence,\n                ttl_days=req.ttl_days,\n                max_runs=req.max_runs,\n            )\n            approved_fingerprint, receipt = _approval_for(\n''',
    '''            preview = service.preview(\n                req.tool,\n                req.args,\n                req.cadence,\n                ttl_days=req.ttl_days,\n                max_runs=req.max_runs,\n                timezone_name=req.timezone,\n                misfire_policy=req.misfire_policy,\n            )\n            approved_fingerprint, receipt = _approval_for(\n''',
)
replace_once(
    '''                req.cadence,\n                ttl_days=req.ttl_days,\n                max_runs=req.max_runs,\n                approved_fingerprint=approved_fingerprint,\n                receipt=receipt,\n            )\n''',
    '''                req.cadence,\n                ttl_days=req.ttl_days,\n                max_runs=req.max_runs,\n                timezone_name=req.timezone,\n                misfire_policy=req.misfire_policy,\n                approved_fingerprint=approved_fingerprint,\n                receipt=receipt,\n            )\n''',
)

print("T-017 stage 3A worker HTTP fields applied")
