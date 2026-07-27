#!/usr/bin/env python3
"""KalivTokens.kt is generated, and must not drift from the token JSON.

The checklist item "semantic dark/light tokens implemented centrally" is an
agreement until something enforces it. This makes it a gate: if anyone edits a
generated token file by hand, or changes the JSON without regenerating, --check
goes red here.

Run: python3 tests/workflow_design_tokens.py
"""
from __future__ import annotations

import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
GEN = ROOT / "scripts" / "design_tokens.py"
TOKENS = ROOT / "assets" / "design" / "kaliv-ui-guide" / "kaliv-ui-tokens.json"
GENERATED = [
    ROOT / "desktop/composeApp/src/main/kotlin/dk/ternedal/modelrig/desktop/KalivTokens.kt",
    ROOT / "android/app/src/main/java/dk/ternedal/modelrig/ui/theme/KalivTokens.kt",
]

passed = failed = 0


def check(condition: bool, message: str) -> None:
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS: {message}")
    else:
        failed += 1
        print(f"  FAIL: {message}")


def run_check() -> int:
    return subprocess.run(
        [sys.executable, str(GEN), "--check"],
        capture_output=True, text=True, cwd=str(ROOT),
    ).returncode


check(TOKENS.is_file(), "the design token JSON is the declared source and exists")
check(GEN.is_file(), "the generator exists")
for g in GENERATED:
    check(g.is_file(), f"generated source exists: {g.relative_to(ROOT)}")
    if g.is_file():
        head = g.read_text(encoding="utf-8")[:200]
        check("GENERERET af scripts/design_tokens.py" in head,
              f"{g.name} carries the do-not-edit banner")

check(run_check() == 0, "generated token sources match the JSON")

# Sabotage: a gate that cannot go red is decoration. Each generated file is
# perturbed in turn and the check must fail, then the file is restored.
for g in GENERATED:
    original = g.read_text(encoding="utf-8")
    try:
        g.write_text(original.replace("0xFF0B0A09", "0xFF000000"), encoding="utf-8")
        check(run_check() != 0,
              f"hand-editing {g.name} turns the check RED")
    finally:
        g.write_text(original, encoding="utf-8")

check(run_check() == 0, "with the files restored, the check returns to green")

print(f"design token contracts: {passed} passed, {failed} failed")
if failed:
    raise SystemExit(1)
