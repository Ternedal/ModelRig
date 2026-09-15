"""Execute the ADR-DC-074 contract under pytest discovery."""
from __future__ import annotations
import sys
from pathlib import Path

SUPPORT = Path(__file__).resolve().parent / "support"
if str(SUPPORT) not in sys.path:
    sys.path.insert(0, str(SUPPORT))

from rsi_pilot_exact_task_pr_post_reviewer_request_handoff_requirements_contract import run_contract


def test_rsi_pilot_exact_task_pr_post_reviewer_request_handoff_requirements_contract() -> None:
    run_contract()
