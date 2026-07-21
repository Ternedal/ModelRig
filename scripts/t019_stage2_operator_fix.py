#!/usr/bin/env python3
"""Apply only the T-019 operator receipt-archive and local-state ignore fixes."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_once(path: str, old: str, new: str) -> None:
    target = ROOT / path
    text = target.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{path}: expected one match, found {count}: {old[:200]!r}")
    target.write_text(text.replace(old, new, 1), encoding="utf-8")


OPERATOR = "scripts/scheduler_pilot_operator.py"
replace_once(
    OPERATOR,
    '''        if completed.get("state") != "released" or completed.get("claim_id") != active.get("claim_id"):\n            raise OperatorError("pause-barrieren afsluttede ikke released på samme claim")\n\n        deadline = self.monotonic() + wait_seconds\n''',
    '''        if completed.get("state") != "released" or completed.get("claim_id") != active.get("claim_id"):\n            raise OperatorError("pause-barrieren afsluttede ikke released på samme claim")\n        archive_path = self.barrier_dir / f"pause-{active.get('claim_id')}.json"\n        if archive_path.exists():\n            raise OperatorError(f"pause-receipt findes allerede: {archive_path}")\n        os.replace(self.barrier_dir / COMPLETED_NAME, archive_path)\n\n        deadline = self.monotonic() + wait_seconds\n''',
)
replace_once(
    OPERATOR,
    '''            "api_verified": True,\n            "receipt": str(self.barrier_dir / COMPLETED_NAME),\n        }\n''',
    '''            "api_verified": True,\n            "receipt": str(archive_path),\n        }\n''',
)

GITIGNORE = ".gitignore"
replace_once(
    GITIGNORE,
    '''/validation/stage-a-easy-state.json\n/validation/stage-a-runtime/\n/validation/archive/\n''',
    '''/validation/stage-a-easy-state.json\n/validation/stage-a-runtime/\n/validation/archive/\n\n# T-019 scheduler-pilot operator: resumable state, barrier arms and local receipts.\n# These contain rig/process observations and remain local until the final reviewed\n# scheduler-pilot report is copied to dated evidence.\n/validation/scheduler-pilot-operator-state.json\n/validation/scheduler-pilot-operator-state.json.tmp-*\n/validation/scheduler-pilot-barrier/\n''',
)

print("T-019 operator resume fixes applied")
