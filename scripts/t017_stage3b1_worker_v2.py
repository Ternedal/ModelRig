#!/usr/bin/env python3
"""Apply only T-017 worker-side approval v2 read compatibility.

Temporary transport. Backend issuance remains unchanged until stage 3B2.
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
            f"{path}: expected one match, found {count}: {old[:180]!r}"
        )
    target.write_text(text.replace(old, new, 1), encoding="utf-8")


APPROVAL = "worker/app/schedule_approval.py"

replace_once(
    APPROVAL,
    '''from . import paths as _paths\n''',
    '''from . import paths as _paths\nfrom .scheduler_time import DEFAULT_TIMEZONE, MISFIRE_POLICY\n''',
)
replace_once(
    APPROVAL,
    '''    if not isinstance(claims, dict) or claims.get("v") != 1:\n        raise ScheduleApprovalError("schedule approval token version is unsupported")\n\n    nonce = claims.get("nonce")\n''',
    '''    if not isinstance(claims, dict):\n        raise ScheduleApprovalError("schedule approval token payload is invalid")\n    version = claims.get("v")\n    if version not in (1, 2):\n        raise ScheduleApprovalError("schedule approval token version is unsupported")\n\n    nonce = claims.get("nonce")\n''',
)
replace_once(
    APPROVAL,
    '''    expected = {\n        "operation": getattr(preview, "operation", None),\n        "schedule_id": getattr(preview, "schedule_id", None),\n        "tool": getattr(preview, "tool", None),\n        "args": getattr(preview, "args", None),\n        "cadence": getattr(preview, "cadence", None),\n        "ttl_days": getattr(preview, "ttl_days", None),\n        "max_runs": getattr(preview, "max_runs", None),\n        "enable": getattr(preview, "enable", None),\n        "action_fingerprint": getattr(preview, "action_fingerprint", None),\n        "approval_fingerprint": getattr(preview, "approval_fingerprint", None),\n    }\n''',
    '''    preview_timezone = getattr(preview, "timezone", DEFAULT_TIMEZONE)\n    preview_misfire = getattr(preview, "misfire_policy", MISFIRE_POLICY)\n    if version == 1 and (\n        preview_timezone != DEFAULT_TIMEZONE\n        or preview_misfire != MISFIRE_POLICY\n    ):\n        raise ScheduleApprovalError(\n            "legacy schedule approval token cannot authorize a non-default "\n            "timezone or misfire policy; confirm the preview again"\n        )\n\n    expected = {\n        "operation": getattr(preview, "operation", None),\n        "schedule_id": getattr(preview, "schedule_id", None),\n        "tool": getattr(preview, "tool", None),\n        "args": getattr(preview, "args", None),\n        "cadence": getattr(preview, "cadence", None),\n        "ttl_days": getattr(preview, "ttl_days", None),\n        "max_runs": getattr(preview, "max_runs", None),\n        "enable": getattr(preview, "enable", None),\n        "action_fingerprint": getattr(preview, "action_fingerprint", None),\n        "approval_fingerprint": getattr(preview, "approval_fingerprint", None),\n    }\n    if version == 2:\n        expected["timezone"] = preview_timezone\n        expected["misfire_policy"] = preview_misfire\n''',
)
replace_once(
    APPROVAL,
    '''                "schedule approval does not match the previewed action, cadence, expiry, budget or enable state"\n''',
    '''                "schedule approval does not match the previewed action, cadence, timezone, misfire policy, expiry, budget or enable state"\n''',
)

# The existing non-default worker HTTP test must exercise the new explicit v2
# envelope. Other old tests remain v1 and prove the compatibility restriction.
API_TEST = "tests/worker_schedule_api_time.py"
replace_once(API_TEST, '        "v": 1,\n', '        "v": 2,\n')
replace_once(
    API_TEST,
    '''        "cadence": preview["cadence"],\n        "ttl_days": preview["ttl_days"],\n''',
    '''        "cadence": preview["cadence"],\n        "timezone": preview["timezone"],\n        "misfire_policy": preview["misfire_policy"],\n        "ttl_days": preview["ttl_days"],\n''',
)
replace_once(
    API_TEST,
    '''        # The v1 envelope has no separate timezone claims, but this signed value\n        # is version 2 and already hashes timezone + misfire policy.\n        "approval_fingerprint": preview["approval_fingerprint"],\n''',
    '''        # v2 carries explicit time terms as well as the canonical fingerprint.\n        "approval_fingerprint": preview["approval_fingerprint"],\n''',
)
replace_once(
    API_TEST,
    '''This stage changes worker request forwarding only, not the signed claim schema.\n''',
    '''This test now exercises the explicit v2 claim schema read by the worker.\n''',
)

print("T-017 stage 3B1 worker v2 reader applied")
