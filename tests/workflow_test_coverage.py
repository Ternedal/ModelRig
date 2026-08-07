"""Contract test: every repository and landed DevControl test is reached by CI.

Run: python3 tests/workflow_test_coverage.py
"""
from __future__ import annotations

import fnmatch
import json
import re
import sys
from pathlib import Path
from types import SimpleNamespace

root = Path(__file__).resolve().parents[1]
workflow = (root / ".github/workflows/_tests.yml").read_text(encoding="utf-8")
sys.path.insert(0, str(root / "devcontrol/src"))

import kaliv_dev_control.github_read as github_read_module
from kaliv_dev_control.catalog import CatalogError, ProjectCommandSpec
from kaliv_dev_control.github_read import (
    GitHubReadError,
    UrllibReadOnlyTransport,
)

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
    "test_slice5.py",
    "test_store_proposal.py",
}
observed = {path.name for path in devcontrol_tests}
check(
    observed == expected,
    f"the nine DC-L01–L03 test modules are present: {sorted(observed)}",
)
check(
    all(path.is_file() for path in devcontrol_tests),
    "every DevControl test matched by unittest discovery is a regular file",
)

receipt_schema = json.loads(
    (
        root
        / "devcontrol/schemas/development-github-read-receipt-v1.schema.json"
    ).read_text(encoding="utf-8")
)
repository_pattern = re.compile(
    receipt_schema["properties"]["repository"]["pattern"]
)
check(
    repository_pattern.fullmatch("Ternedal/ModelRig") is not None,
    "the GitHub receipt schema accepts the canonical ModelRig repository",
)
invalid_repositories = (
    "./ModelRig",
    "Ternedal/..",
    "Ternedal/Model Rig",
    "Ternedal/\x00ModelRig",
)
check(
    all(repository_pattern.fullmatch(value) is None for value in invalid_repositories),
    "the GitHub receipt schema rejects dot segments, whitespace and NUL authority",
)

blocked_environment = True
for key, value in (
    ("GOROOT", "."),
    ("PYTHONUSERBASE", "."),
    ("GOTOOLCHAIN", "auto"),
):
    try:
        ProjectCommandSpec(
            "modelrig.contract.probe",
            "python",
            ("-V",),
            ".",
            10,
            {key: value},
        )
    except CatalogError:
        continue
    blocked_environment = False
check(
    blocked_environment,
    "catalog environment is a fixed-value positive list without runtime authority",
)


class _DeadlineSocket:
    def __init__(self) -> None:
        self.timeouts: list[float] = []

    def settimeout(self, value: float) -> None:
        self.timeouts.append(value)


class _SlowResponse:
    status = 200
    headers = {"Content-Type": "application/json"}

    def __init__(self) -> None:
        self.socket = _DeadlineSocket()
        self.fp = SimpleNamespace(
            raw=SimpleNamespace(_sock=self.socket)
        )
        self.closed = False

    def read1(self, amount: int) -> bytes:
        del amount
        return b"x"

    def close(self) -> None:
        self.closed = True


class _SlowOpener:
    def __init__(self, response: _SlowResponse) -> None:
        self.response = response

    def open(self, request, timeout):
        del request, timeout
        return self.response


slow_response = _SlowResponse()
transport = object.__new__(UrllibReadOnlyTransport)
transport._opener = _SlowOpener(slow_response)
ticks = iter((0.0, 0.2, 0.7, 1.1))
original_monotonic = github_read_module.time.monotonic
github_read_module.time.monotonic = lambda: next(ticks)
deadline_rejected = False
try:
    try:
        transport.get(
            "https://api.github.com/repos/Ternedal/ModelRig/commits/" + "a" * 40,
            headers={},
            timeout_seconds=1,
            max_bytes=100,
        )
    except GitHubReadError as exc:
        deadline_rejected = "wall-clock deadline" in str(exc)
finally:
    github_read_module.time.monotonic = original_monotonic
check(
    deadline_rejected
    and slow_response.closed
    and bool(slow_response.socket.timeouts),
    "slow-drip GitHub reads are stopped by one monotonic wall-clock deadline",
)

print(f"\n===== TEST COVERAGE: {passed} passed, {failed} failed =====")
raise SystemExit(1 if failed else 0)
