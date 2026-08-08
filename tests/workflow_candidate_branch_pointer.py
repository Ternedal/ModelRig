#!/usr/bin/env python3
"""The physical-candidate branch pointer is one fail-closed authority."""
from __future__ import annotations

import importlib.util
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "candidate_branch.py"
EXPECTED_VERSION = "1.58.151"
EXPECTED_BRANCH = "agent/unified-candidate-1.58.151-r3"

passed = failed = 0


def check(condition: bool, message: str) -> None:
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS: {message}")
    else:
        failed += 1
        print(f"  FAIL: {message}")


spec = importlib.util.spec_from_file_location("candidate_branch_contract", MODULE_PATH)
assert spec is not None and spec.loader is not None
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

check(
    module.load_candidate_branch(ROOT, EXPECTED_VERSION) == EXPECTED_BRANCH,
    "tracked pointer resolves to the replacement r3 candidate",
)


def rejected(payload: bytes | None, *, version: str = EXPECTED_VERSION) -> bool:
    root = Path(tempfile.mkdtemp(prefix="candidate-branch-pointer-"))
    if payload is not None:
        (root / module.POINTER_NAME).write_bytes(payload)
    try:
        module.load_candidate_branch(root, version)
    except module.CandidateBranchError:
        return True
    return False


for payload, label in (
    (None, "missing pointer is rejected"),
    (b"", "empty pointer is rejected"),
    (b"\xff\xfe", "non-UTF-8 pointer is rejected"),
    (b"x" * (module.MAX_BYTES + 1), "oversized pointer is rejected"),
    (b"main\n", "non-candidate branch is rejected"),
    (
        b"agent/unified-candidate-1.58.150-r3\n",
        "wrong candidate version is rejected",
    ),
    (
        b"agent/unified-candidate-1.58.151-r0\n",
        "zero replacement suffix is rejected",
    ),
    (
        b"agent/unified-candidate-1.58.151-r03\n",
        "ambiguous replacement suffix is rejected",
    ),
    (
        b"agent/unified-candidate-1.58.151-r3/extra\n",
        "branch path extension is rejected",
    ),
):
    check(rejected(payload), label)

wrong_version_root = Path(tempfile.mkdtemp(prefix="candidate-branch-version-"))
(wrong_version_root / module.POINTER_NAME).write_text(
    EXPECTED_BRANCH + "\n", encoding="utf-8"
)
try:
    module.load_candidate_branch(wrong_version_root, "1.58.152")
except module.CandidateBranchError:
    check(True, "call-site version drift is rejected")
else:
    check(False, "call-site version drift is rejected")

symlink_root = Path(tempfile.mkdtemp(prefix="candidate-branch-symlink-"))
target = symlink_root / "target"
target.write_text(EXPECTED_BRANCH + "\n", encoding="utf-8")
try:
    (symlink_root / module.POINTER_NAME).symlink_to(target)
except (OSError, NotImplementedError):
    print("  SKIP: symlink creation is unavailable on this runner")
else:
    try:
        module.load_candidate_branch(symlink_root, EXPECTED_VERSION)
    except module.CandidateBranchError:
        check(True, "symlink pointer is rejected")
    else:
        check(False, "symlink pointer is rejected")

for relative in (
    "scripts/stage_a_physical_operator.py",
    "scripts/stage_a_one_click.py",
    "scripts/scheduler_pilot_wizard.py",
    "scripts/agent3_readonly_pilot_one_click.py",
):
    text = (ROOT / relative).read_text(encoding="utf-8")
    check(
        "load_candidate_branch" in text,
        f"{relative} consumes the shared pointer loader",
    )
    check(
        'agent/unified-candidate-1.58.151"' not in text,
        f"{relative} does not hardcode the superseded branch",
    )

for relative in (
    "tests/workflow_stage_a_physical_operator.py",
    "tests/workflow_stage_a_one_click.py",
    "tests/workflow_scheduler_pilot_wizard.py",
    "tests/workflow_agent3_readonly_pilot_one_click.py",
    "tests/workflow_remaining_physical_pilots.py",
):
    text = (ROOT / relative).read_text(encoding="utf-8")
    check(
        'CANDIDATE_BRANCH' in text and '_BRANCH' in text,
        f"{relative} binds its retained contract to the tracked pointer",
    )

print(f"Candidate branch pointer contracts: {passed} passed, {failed} failed")
if failed:
    raise SystemExit(1)
