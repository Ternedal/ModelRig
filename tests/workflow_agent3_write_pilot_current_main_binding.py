#!/usr/bin/env python3
"""Current-main T-022 candidate binding must be explicit and side-effect free."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENTRY = ROOT / "scripts" / "agent3_write_pilot_current_main.py"
LAUNCHER = ROOT / "START_AGENT3_WRITE_PILOT.cmd"
RUNBOOK = ROOT / "AGENT3_WRITE_PILOT_CURRENT_MAIN.md"
EXPECTED_BRANCH = "agent/t022-final-gate-current-main"
EXPECTED_VERSION = (ROOT / "VERSION").read_text(encoding="utf-8").strip()

passed = failed = 0


def check(condition: bool, message: str) -> None:
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS: {message}")
    else:
        failed += 1
        print(f"  FAIL: {message}")


check(ENTRY.is_file(), "the current-main binding entrypoint exists")
check(LAUNCHER.is_file(), "the authoritative top-level launcher exists")
check(RUNBOOK.is_file(), "the current-main operator note exists")

entry_source = ENTRY.read_text(encoding="utf-8")
launcher_source = LAUNCHER.read_text(encoding="utf-8")
runbook_source = RUNBOOK.read_text(encoding="utf-8")

check(EXPECTED_BRANCH in entry_source, "the entrypoint pins the exact current-main candidate branch")
check(EXPECTED_VERSION in entry_source, "the entrypoint pins the repository VERSION")
check(
    "agent3_write_pilot_current_main.py" in launcher_source,
    "the top-level launcher calls only the current-main binding",
)
check(
    "agent3_write_pilot_final_gate_operator.py" not in launcher_source,
    "the launcher cannot bypass current-main binding",
)
check(EXPECTED_BRANCH in runbook_source, "the runbook names the exact candidate branch")
check(EXPECTED_VERSION in runbook_source, "the runbook names the exact candidate version")

for forbidden in (
    "subprocess",
    "urllib",
    "requests",
    "urlopen",
    "Popen",
    "/confirm",
    "/approve",
    "merge_pull_request",
    "production_activation = True",
):
    check(forbidden not in entry_source, f"binding entrypoint has no {forbidden!r} execution path")

spec = importlib.util.spec_from_file_location("t022_current_main_binding", ENTRY)
check(spec is not None and spec.loader is not None, "the entrypoint is importable")
if spec is None or spec.loader is None:
    raise SystemExit(1)
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)

check(module.BRANCH == EXPECTED_BRANCH, "runtime branch equals the documented candidate")
check(module.VERSION == EXPECTED_VERSION, "runtime version equals the repository VERSION")

module.configure_candidate()
final_gate = module.operator.core
collector = final_gate.collector
negative = collector.negative_entry.core
positive = collector.positive

for label, candidate in (
    ("final gate", final_gate),
    ("collector", collector),
    ("negative operator", negative),
    ("positive operator", positive),
):
    check(candidate.BRANCH == EXPECTED_BRANCH, f"{label} receives the exact branch")
    check(candidate.VERSION == EXPECTED_VERSION, f"{label} receives the exact version")

check(
    getattr(final_gate, "GATE_REPORT", None) is not None,
    "binding preserves the established final-gate report surface",
)
check(
    getattr(collector, "REPORT", None) is not None,
    "binding preserves the established forensic report surface",
)

print(f"\n===== T-022 CURRENT-MAIN BINDING: {passed} passed, {failed} failed =====")
raise SystemExit(1 if failed else 0)
