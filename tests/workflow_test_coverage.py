"""Contract test: every repository and landed DevControl test is reached by CI.

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
check(m is not None, "the workflow still runs repository tests through a readable glob loop")
if m is None:
    print("\n===== TEST COVERAGE: cannot verify -- workflow shape changed =====")
    raise SystemExit(1)

patterns = m.group(1).split()
check(len(patterns) >= 2, f"glob patterns found: {' '.join(patterns)}")

files = sorted(p.relative_to(root).as_posix() for p in (root / "tests").glob("*.py"))
check(len(files) > 10, f"{len(files)} repository test files on disk")

missed = [f for f in files if not any(fnmatch.fnmatch(f, g) for g in patterns)]
check(
    not missed,
    "every repository test file matches a CI pattern"
    if not missed
    else f"UNREACHED BY CI: {', '.join(missed)} -- rename them or widen the glob",
)

fake = ["tests/agent_smoke.py", "tests/worker_unit.py"]
fake_missed = [f for f in fake if not any(fnmatch.fnmatch(f, g) for g in patterns)]
check(
    fake_missed == ["tests/agent_smoke.py"],
    "self-test: a repository file outside the patterns is detected",
)

discovery_command = (
    "PYTHONPATH=devcontrol/src python3 -m unittest discover "
    "-s devcontrol/tests -p 'test_*.py' -v"
)
check(
    discovery_command in workflow,
    "the workflow runs the exact DevControl unittest discovery command",
)

devcontrol_tests = sorted((root / "devcontrol/tests").glob("test_*.py"))
expected = {
    "test_bounded_subprocess.py",
    "test_campaign_review.py",
    "test_durable_publication.py",
    "test_foundation.py",
    "test_proposal_reload.py",
    "test_review_reload.py",
    "test_slice2.py",
    "test_store_proposal.py",
}
observed = {path.name for path in devcontrol_tests}
check(observed == expected, f"the eight DC-L01–L02 test modules are present: {sorted(observed)}")
check(
    all(path.is_file() for path in devcontrol_tests),
    "every DevControl test matched by unittest discovery is a regular file",
)

print(f"\n===== TEST COVERAGE: {passed} passed, {failed} failed =====")
raise SystemExit(1 if failed else 0)
