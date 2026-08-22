#!/usr/bin/env python3
"""Fail-closed regression for unknown reusable proof-receipt gate names."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import proof_campaign_gate_receipt as R  # noqa: E402

passed = failed = 0


def check(condition: bool, message: str) -> None:
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS: {message}")
    else:
        failed += 1
        print(f"  FAIL: {message}")


def expect_unknown_gate(name: str, action) -> None:
    try:
        action()
    except R.ReceiptError as exc:
        check(str(exc) == "unknown gate: not_a_gate", f"{name} rejects the unknown gate itself")
    except Exception as exc:
        check(False, f"{name} raised unexpected {type(exc).__name__}: {exc}")
    else:
        check(False, f"{name} accepted an unknown gate")


print("proof receipt unknown-gate guards:")

# Both public entry points must reject before commit lookup, configuration,
# evidence loading or scope reuse can reinterpret an unknown name.
expect_unknown_gate(
    "record",
    lambda: R.record("not_a_gate", "0" * 40, "test"),
)
expect_unknown_gate(
    "validate",
    lambda: R.validate("not_a_gate", "0" * 40),
)

print(f"\n===== PROOF RECEIPT UNKNOWN GATE: {passed} passed, {failed} failed =====")
raise SystemExit(1 if failed else 0)
