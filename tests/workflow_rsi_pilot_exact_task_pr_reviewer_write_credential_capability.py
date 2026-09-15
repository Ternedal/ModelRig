"""Exact-head entrypoint for ADR-DC-074 reviewer-write capability."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SUPPORT = ROOT / "tests" / "support"
if str(SUPPORT) not in sys.path:
    sys.path.insert(0, str(SUPPORT))

from rsi_pilot_exact_task_pr_reviewer_write_credential_capability_contract import (  # noqa: E402
    run_contract,
)


if __name__ == "__main__":
    run_contract()
