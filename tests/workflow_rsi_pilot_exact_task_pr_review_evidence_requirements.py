"""Exact-head qualification entrypoint for ADR-DC-092 review-evidence requirements."""
from __future__ import annotations
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
SUPPORT=ROOT/'tests'/'support'
if str(SUPPORT) not in sys.path: sys.path.insert(0,str(SUPPORT))
from rsi_pilot_exact_task_pr_review_evidence_requirements_contract import run_contract
if __name__=='__main__': run_contract()
