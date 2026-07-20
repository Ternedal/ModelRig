#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "candidate_freeze_test", ROOT / "scripts" / "candidate_freeze_check.py"
)
assert SPEC and SPEC.loader
freeze = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = freeze
SPEC.loader.exec_module(freeze)

passed = failed = 0


def check(condition: bool, message: str) -> None:
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS: {message}")
    else:
        failed += 1
        print(f"  FAIL: {message}")


def git(root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args], cwd=root, capture_output=True, text=True, check=True
    )
    return result.stdout.strip()


def fixture() -> tuple[Path, str, str]:
    root = Path(tempfile.mkdtemp(prefix="candidate-freeze-"))
    git(root, "init", "-q")
    git(root, "config", "user.email", "test@example.invalid")
    git(root, "config", "user.name", "test")
    (root / "VERSION").write_text("1.58.141\n", encoding="utf-8")
    (root / "scripts").mkdir()
    (root / "scripts" / "version_tool.py").write_text(
        "import sys\nsys.exit(0)\n", encoding="utf-8"
    )
    (root / "worker" / "app").mkdir(parents=True)
    (root / "worker" / "app" / "build_identity.py").write_text(
        "def code_fingerprint():\n    return 'b' * 64\n", encoding="utf-8"
    )
    (root / "base.txt").write_text("main\n", encoding="utf-8")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "main")
    main_sha = git(root, "rev-parse", "HEAD")
    bare = Path(tempfile.mkdtemp(prefix="candidate-origin-")) / "origin.git"
    subprocess.run(["git", "init", "-q", "--bare", str(bare)], check=True)
    git(root, "remote", "add", "origin", str(bare))
    git(root, "push", "-q", "origin", "HEAD:main")
    git(root, "switch", "-q", "-c", "candidate")
    (root / "candidate.txt").write_text("candidate\n", encoding="utf-8")
    git(root, "add", "candidate.txt")
    git(root, "commit", "-q", "-m", "candidate")
    return root, main_sha, git(root, "rev-parse", "HEAD")


def green_runs():
    return {
        "workflow_runs": [
            {"name": name, "status": "completed", "conclusion": "success"}
            for name in freeze.REQUIRED_WORKFLOWS
        ]
    }


repo, main_sha, candidate_sha = fixture()
now = datetime(2026, 7, 20, 20, 0, tzinfo=timezone.utc)
receipt = freeze.create_receipt(
    candidate_sha,
    root=repo,
    token="test-token",
    api=lambda _url, _token: green_runs(),
    now=now,
)
check(receipt["candidate"]["git_sha"] == candidate_sha, "freeze pins exact expected SHA")
check(receipt["main_anchor"]["git_sha"] == main_sha, "freeze records current main ancestor")
check(
    receipt["software_checks"]
    == {name: "success" for name in freeze.REQUIRED_WORKFLOWS},
    "freeze requires all four exact-head software gates",
)
check(
    receipt["gate"]["release_validation_pending"] is True
    and receipt["gate"]["release_complete"] is False
    and receipt["gate"]["production_activation"] is False,
    "freeze cannot claim release completion or activation",
)
freeze.load_receipt(repo, now=now)
check(True, "strict receipt reader accepts unchanged checkout")

try:
    freeze.create_receipt(
        "a" * 40,
        root=repo,
        token="test-token",
        api=lambda _url, _token: green_runs(),
        now=now,
    )
    check(False, "wrong expected SHA must fail")
except freeze.CandidateFreezeError as exc:
    check("does not equal expected" in str(exc), "wrong expected SHA fails by name")

missing = green_runs()["workflow_runs"][:-1]
try:
    freeze._workflow_checks(missing)
    check(False, "missing software gate must fail")
except freeze.CandidateFreezeError:
    check(True, "missing software gate fails closed")

(repo / "candidate.txt").write_text("tampered\n", encoding="utf-8")
try:
    freeze.load_receipt(repo, now=now)
    check(False, "post-freeze edit must fail")
except freeze.CandidateFreezeError:
    check(True, "post-freeze edit is detected")

print(f"candidate freeze contracts: {passed} passed, {failed} failed")
if failed:
    raise SystemExit(1)
