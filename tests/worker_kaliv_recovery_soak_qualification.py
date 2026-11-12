#!/usr/bin/env python3
"""Run the contract for the recovery_soak release-gate qualifier.

The contract lives in ``tests/support/``, which CI does not iterate, and no
test loaded it. It therefore never ran, and it had drifted from
``scripts/kaliv_recovery_soak_qualification.py`` in four places before anyone
could notice. This runner puts it in the suite.

Run: python3 tests/worker_kaliv_recovery_soak_qualification.py
"""
from __future__ import annotations

import importlib.util
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "kaliv_recovery_soak_qualification_contract_support",
    ROOT / "tests" / "support" / "kaliv_recovery_soak_qualification_contract.py",
)
assert SPEC and SPEC.loader
contract = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = contract
SPEC.loader.exec_module(contract)

try:
    contract.run_contract()
finally:
    shutil.rmtree(contract.COMPONENT_ROOT, ignore_errors=True)

print("Kaliv recovery soak qualification contract: PASS")
