"""Contract test: every test file is actually REACHED by CI's glob.

A test that never runs is worse than no test: it looks like coverage on the
tin and proves nothing. CI runs a glob loop rather than a hand-kept list --
which is the right call, and exactly why a file named outside the patterns
would sit there green-looking and never execute. Nothing would ever say so.

The patterns are read out of the workflow itself, so this cannot drift from
what CI does: change the loop and this test follows.

Run: python3 tests/workflow_test_coverage.py
"""
from __future__ import annotations

import fnmatch
import re
from pathlib import Path

root = Path(__file__).resolve().parents[1]
workflow = (root / ".github/workflows/_tests.yml").read_text(encoding="utf-8")

passed = failed = 0


def check(cond, msg):
    global passed, failed
    if cond:
        passed += 1
        print(f"  PASS: {msg}")
    else:
        failed += 1
        print(f"  FAIL: {msg}")


m = re.search(r"for f in ([^;]+); do", workflow)
check(m is not None, "the workflow still runs tests through a glob loop this test can read")
if m is None:
    print("\n===== TEST COVERAGE: cannot verify -- workflow shape changed =====")
    raise SystemExit(1)

patterns = m.group(1).split()
check(len(patterns) >= 2, f"glob patterns found: {' '.join(patterns)}")

files = sorted(p.relative_to(root).as_posix() for p in (root / "tests").glob("*.py"))
check(len(files) > 10, f"{len(files)} test files on disk")

missed = [f for f in files if not any(fnmatch.fnmatch(f, g) for g in patterns)]
check(
    not missed,
    "every test file matches a CI pattern"
    if not missed
    else f"UNREACHED BY CI: {', '.join(missed)} -- rename them or widen the glob",
)

# The detector must be able to fail, or it is decoration.
fake = ["tests/agent_smoke.py", "tests/worker_unit.py"]
fake_missed = [f for f in fake if not any(fnmatch.fnmatch(f, g) for g in patterns)]
check(fake_missed == ["tests/agent_smoke.py"],
      "self-test: a file outside the patterns IS detected (tests/agent_smoke.py)")

print(f"\n===== TEST COVERAGE: {passed} passed, {failed} failed =====")
raise SystemExit(1 if failed else 0)
