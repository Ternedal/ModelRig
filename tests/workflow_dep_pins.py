"""Contract test: worker dependencies are pinned to exact versions.

CI installs from requirements.txt and the released worker exe is built from the
same file, so a `>=` here means the tests that went green and the binary Anders
runs are not necessarily the same software. That is the same class of hole as
an unpinned GitHub Action: a moving target that nobody watches move.

The four required deps are pinned today. This makes that a property instead of
a habit -- the fifth dep is the one that gets added in a hurry.

Run: python3 tests/workflow_dep_pins.py
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REQ = ROOT / "worker" / "requirements.txt"

passed = failed = 0


def check(cond, msg):
    global passed, failed
    if cond:
        passed += 1
        print(f"  PASS: {msg}")
    else:
        failed += 1
        print(f"  FAIL: {msg}")


check(REQ.exists(), "worker/requirements.txt exists")

PIN = re.compile(r"^[A-Za-z0-9_.\-\[\]]+==[^\s#]+$")
active, loose = [], []
for i, raw in enumerate(REQ.read_text(encoding="utf-8").splitlines(), 1):
    line = raw.split("#", 1)[0].strip()
    if not line:
        continue          # comments carry the optional extras, on purpose
    active.append(line)
    if not PIN.match(line):
        loose.append(f"line {i}: {line}")

check(len(active) >= 4, f"{len(active)} installed dependencies")
check(
    not loose,
    "every installed dependency is pinned with =="
    if not loose
    else "UNPINNED (CI and the shipped exe could differ): " + "; ".join(loose),
)

# The detector must be able to fail, or it is decoration.
check(not PIN.match("httpx>=0.28") and bool(PIN.match("httpx==0.28.1")),
      "self-test: a >= requirement IS detected as unpinned")

print(f"\n===== DEP PINS: {passed} passed, {failed} failed =====")
raise SystemExit(1 if failed else 0)
