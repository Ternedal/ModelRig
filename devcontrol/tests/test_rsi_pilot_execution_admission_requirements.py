"""Discovered DevControl wrapper for the ADR-DC-026 adversarial contract."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SUPPORT = ROOT / "tests" / "support"
if str(SUPPORT) not in sys.path:
    sys.path.insert(0, str(SUPPORT))

from rsi_pilot_execution_admission_requirements_contract import run_contract  # noqa: E402


class PilotExecutionAdmissionRequirementsContractTest(unittest.TestCase):
    def test_adversarial_contract(self) -> None:
        run_contract()


if __name__ == "__main__":
    unittest.main()
