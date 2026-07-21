#!/usr/bin/env python3
"""Retire scheduler approval v1 after every issuer and fixture uses v2.

Temporary transport. This stage changes only worker verification and test token
helpers; backend issuance is already v2.
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
            f"{path}: expected one match, found {count}: {old[:200]!r}"
        )
    target.write_text(text.replace(old, new, 1), encoding="utf-8")


APPROVAL = "worker/app/schedule_approval.py"
replace_once(
    APPROVAL,
    '''from . import paths as _paths\nfrom .scheduler_time import DEFAULT_TIMEZONE, MISFIRE_POLICY\n''',
    '''from . import paths as _paths\n''',
)
replace_once(
    APPROVAL,
    '''    version = claims.get("v")\n    if version not in (1, 2):\n        raise ScheduleApprovalError("schedule approval token version is unsupported")\n''',
    '''    version = claims.get("v")\n    if version != 2:\n        raise ScheduleApprovalError("schedule approval token version is unsupported")\n''',
)
replace_once(
    APPROVAL,
    '''    preview_timezone = getattr(preview, "timezone", DEFAULT_TIMEZONE)\n    preview_misfire = getattr(preview, "misfire_policy", MISFIRE_POLICY)\n    if version == 1 and (\n        preview_timezone != DEFAULT_TIMEZONE\n        or preview_misfire != MISFIRE_POLICY\n    ):\n        raise ScheduleApprovalError(\n            "legacy schedule approval token cannot authorize a non-default "\n            "timezone or misfire policy; confirm the preview again"\n        )\n\n    expected = {\n''',
    '''    preview_timezone = getattr(preview, "timezone", None)\n    preview_misfire = getattr(preview, "misfire_policy", None)\n\n    expected = {\n''',
)
replace_once(
    APPROVAL,
    '''        "cadence": getattr(preview, "cadence", None),\n        "ttl_days": getattr(preview, "ttl_days", None),\n''',
    '''        "cadence": getattr(preview, "cadence", None),\n        "timezone": preview_timezone,\n        "misfire_policy": preview_misfire,\n        "ttl_days": getattr(preview, "ttl_days", None),\n''',
)
replace_once(
    APPROVAL,
    '''    if version == 2:\n        expected["timezone"] = preview_timezone\n        expected["misfire_policy"] = preview_misfire\n    for name, value in expected.items():\n''',
    '''    for name, value in expected.items():\n''',
)

CRYPTO = "tests/worker_schedule_approval.py"
replace_once(CRYPTO, '''        "v": 1,\n''', '''        "v": 2,\n''')
replace_once(
    CRYPTO,
    '''        "tool": preview.tool,\n        "args": preview.args,\n        "cadence": preview.cadence,\n        "ttl_days": preview.ttl_days,\n        "max_runs": preview.max_runs,\n''',
    '''        "tool": preview.tool,\n        "args": preview.args,\n        "cadence": preview.cadence,\n        "timezone": preview.timezone,\n        "misfire_policy": preview.misfire_policy,\n        "ttl_days": preview.ttl_days,\n        "max_runs": preview.max_runs,\n''',
)
replace_once(
    CRYPTO,
    '''    args={"text": "Husk brygdag"},\n    cadence="daily:08:00",\n    ttl_days=30,\n''',
    '''    args={"text": "Husk brygdag"},\n    cadence="daily:08:00",\n    timezone="Europe/Copenhagen",\n    misfire_policy="run_once",\n    ttl_days=30,\n''',
)

API = "tests/worker_schedule_api.py"
replace_once(API, '''        "v": 1,\n''', '''        "v": 2,\n''')
replace_once(
    API,
    '''        "tool": preview["tool"],\n        "args": preview["args"],\n        "cadence": preview["cadence"],\n        "ttl_days": preview["ttl_days"],\n        "max_runs": preview["max_runs"],\n        "enable": preview["enable"],\n''',
    '''        "tool": preview["tool"],\n        "args": preview["args"],\n        "cadence": preview["cadence"],\n        "timezone": preview["timezone"],\n        "misfire_policy": preview["misfire_policy"],\n        "ttl_days": preview["ttl_days"],\n        "max_runs": preview["max_runs"],\n        "enable": preview["enable"],\n''',
)
replace_once(
    API,
    '''def create_body(preview, token=None, **changes):\n    body = {\n        "tool": preview["tool"],\n        "args": preview["args"],\n        "cadence": preview["cadence"],\n        "ttl_days": preview["ttl_days"],\n        "max_runs": preview["max_runs"],\n    }\n''',
    '''def create_body(preview, token=None, **changes):\n    body = {\n        "tool": preview["tool"],\n        "args": preview["args"],\n        "cadence": preview["cadence"],\n        "timezone": preview["timezone"],\n        "misfire_policy": preview["misfire_policy"],\n        "ttl_days": preview["ttl_days"],\n        "max_runs": preview["max_runs"],\n    }\n''',
)

TRANSITION = "tests/worker_schedule_approval_time.py"
replace_once(
    TRANSITION,
    '''Stage 3B1 is deliberately read-side only: the worker accepts explicit v2 claims\nwhile retaining v1 solely for the historical Copenhagen/run_once contract.\nThat legacy exception is temporary and is removed only after every issuer uses v2.\n''',
    '''All issuers now use explicit v2 claims. Version 1 is rejected even for the\nhistorical Copenhagen/run_once terms so no unsigned time defaults survive.\n''',
)
replace_once(
    TRANSITION,
    '''check(\n    refused(token_for(nondefault, version=1, include_time=False), nondefault, "legacy"),\n    "v1 cannot authorize a non-default timezone grant",\n)\n\nlegacy = preview(timezone="Europe/Copenhagen", misfire_policy="run_once")\nlegacy_verified = verify_schedule_approval(\n    token_for(legacy, version=1, include_time=False),\n    legacy,\n    now=NOW + 1,\n    secret_factory=lambda: SECRET,\n)\ncheck(legacy_verified.device_id == "pixel-6a-t017-v2", "v1 remains valid only for historical default terms")\ncheck(\n    refused(token_for(legacy, version=3), legacy, "version"),\n    "unknown token version remains fail-closed",\n)\n''',
    '''legacy = preview(timezone="Europe/Copenhagen", misfire_policy="run_once")\ncheck(\n    refused(token_for(legacy, version=1, include_time=False), legacy, "version"),\n    "v1 is rejected even for historical default terms",\n)\ncheck(\n    refused(token_for(legacy, version=3), legacy, "version"),\n    "unknown token version remains fail-closed",\n)\n''',
)

print("T-017 stage 3B3 approval v1 retired")
