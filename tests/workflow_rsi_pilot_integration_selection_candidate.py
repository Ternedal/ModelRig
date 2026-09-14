#!/usr/bin/env python3
"""Discovered wrapper for the ADR-DC-020 adversarial support contract."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "tests" / "support" / "rsi_pilot_integration_selection_candidate_contract.py"

spec = importlib.util.spec_from_file_location(
    "rsi_pilot_integration_selection_candidate_contract",
    CONTRACT,
)
assert spec is not None and spec.loader is not None
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)
module.run_contract()
print("RSI DC-L16 product integration selection candidate contract: PASS")
