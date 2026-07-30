#!/usr/bin/env python3
"""A4-06 timeline plus A4-07/A4-08 composition and operator contracts."""

from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path


SUPPORT = Path(__file__).with_name("support")


def _load(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, SUPPORT / filename)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_timeline = _load("agent4_timeline_cases_core", "agent4_timeline_cases_core.py")
_composition = _load(
    "agent4_runtime_composition_cases",
    "agent4_runtime_composition_cases.py",
)
_operator = _load(
    "agent4_operator_read_cases",
    "agent4_operator_read_cases.py",
)

Agent4TimelineTests = _timeline.Agent4TimelineTests
Agent4RuntimeCompositionTests = _composition.Agent4RuntimeCompositionTests
Agent4OperatorReadTests = _operator.Agent4OperatorReadTests


if __name__ == "__main__":
    unittest.main()
