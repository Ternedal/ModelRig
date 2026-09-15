"""Exact-head entrypoint for ADR-DC-081 preflight review-thread capability."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SUPPORT = ROOT / "tests" / "support"
if str(SUPPORT) not in sys.path:
    sys.path.insert(0, str(SUPPORT))

from rsi_pilot_exact_task_pr_merge_preflight_review_thread_credential_capability_contract import run_contract  # noqa: E402


if __name__ == "__main__":
    run_contract()
