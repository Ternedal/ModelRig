"""Workflow entrypoint for ADR-DC-094 push-webhook ingress contract."""
from __future__ import annotations
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
SUPPORT = ROOT / "tests" / "support"
if str(SUPPORT) not in sys.path: sys.path.insert(0, str(SUPPORT))
from rsi_pilot_exact_task_pr_push_webhook_ingress_contract import run_contract
if __name__ == "__main__": run_contract()
