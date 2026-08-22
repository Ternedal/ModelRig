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

ANCHOR_SPEC = importlib.util.spec_from_file_location(
    "anchor_and_freeze_test", ROOT / "scripts" / "anchor_and_freeze.py"
)
assert ANCHOR_SPEC and ANCHOR_SPEC.loader
anchor = importlib.util.module_from_spec(ANCHOR_SPEC)
sys.modules[ANCHOR_SPEC.name] = anchor
ANCHOR_SPEC.loader.exec_module(anchor)

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
    (root / ".gitignore").write_text(
        "/validation/pre-release-candidate-freeze-latest.json\n"
        "/validation/pre-release-candidate-freeze-latest.json.tmp\n",
        encoding="utf-8",
    )
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


def free_tag_api(tag_sha=None):
    """Green software checks; vVERSION either unused (404) or owned by tag_sha."""
    import urllib.error as _ue

    def api(url, _token):
        if "/git/ref/tags/" in url:
            if tag_sha is None:
                raise _ue.HTTPError(url, 404, "not found", {}, None)
            return {"object": {"type": "commit", "sha": tag_sha}}
        if "/actions/runs" in url:
            return green_runs()
        raise AssertionError(f"uventet API-url i testen: {url}")

    return api


# The re-freeze helper must wait on exactly the same authority set as the
# receipt gate. Otherwise it can start a freeze while one required check (the
# historical gap was CodeQL) is still missing or in progress.
check(
    set(anchor.VENTER_PAA) == set(freeze.REQUIRED_WORKFLOWS),
    "anchor helper waits on exactly all candidate-freeze software gates",
)
check(
    set(anchor.DISPATCH_FALLBACKS)
    == {"agent3-diagnostics", "agent3-full-diagnostics"},
    "only Agent 3 workflows are manual-dispatch fallbacks",
)

for label, workflow_path in (
    ("Agent 3 diagnostics", ROOT / ".github" / "workflows" / "agent3-diagnostics.yml"),
    (
        "Agent 3 full diagnostics",
        ROOT / ".github" / "workflows" / "agent3-full-diagnostics.yml",
    ),
):
    workflow = workflow_path.read_text(encoding="utf-8")
    check(
        "push:\n    branches: [main]" in workflow,
        f"{label} automatically produces exact-main freeze provenance",
    )
    check(
        "workflow_dispatch:" in workflow,
        f"{label} retains manual recovery dispatch",
    )

newest = {"name": "ci", "head_sha": "a" * 40, "status": "in_progress", "id": 2}
older = {
    "name": "ci",
    "head_sha": "a" * 40,
    "status": "completed",
    "conclusion": "success",
    "id": 1,
}
check(
    anchor._latest_by_name([newest, older])["ci"]["id"] == 2,
    "newer incomplete run cannot be hidden by an older green run",
)

repo, main_sha, candidate_sha = fixture()
now = datetime(2026, 7, 20, 20, 0, tzinfo=timezone.utc)
receipt = freeze.create_receipt(
    candidate_sha,
    root=repo,
    token="test-token",
    api=free_tag_api(),
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
check(True, "strict receipt reader accepts unchanged checkout and current main")

try:
    freeze.create_receipt(
        "a" * 40,
        root=repo,
        token="test-token",
        api=free_tag_api(),
        now=now,
    )
    check(False, "wrong expected SHA must fail")
except freeze.CandidateFreezeError as exc:
    check("does not equal expected" in str(exc), "wrong expected SHA fails by name")

# F-1901: a candidate whose VERSION is already a shipped tag cannot be promoted.
# Missing this check cost a full physical Stage A run on 2026-08-04: the campaign
# passed 7/7 on a version whose tag was published a week earlier.
try:
    freeze.create_receipt(
        candidate_sha,
        root=repo,
        token="test-token",
        api=free_tag_api(tag_sha="f" * 40),
        now=now,
    )
    check(False, "a VERSION already tagged elsewhere must fail the freeze")
except freeze.CandidateFreezeError as exc:
    check(
        "already tagged" in str(exc) and "bump VERSION" in str(exc),
        "a taken VERSION fails closed and names the fix",
    )

# The same tag pointing AT this candidate is the post-promotion state, not a clash.
receipt_after_tag = freeze.create_receipt(
    candidate_sha,
    root=repo,
    token="test-token",
    api=free_tag_api(tag_sha=candidate_sha),
    now=now,
)
check(
    receipt_after_tag["gate"]["passed"] is True,
    "a tag pointing at this same candidate is not a conflict",
)

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

# A receipt is not a permanent permission slip. Every consumer must refetch
# origin/main; otherwise a campaign can continue after main advances and the
# candidate is no longer the current release boundary.
stale_repo, stale_main_sha, stale_candidate_sha = fixture()
freeze.create_receipt(
    stale_candidate_sha,
    root=stale_repo,
    token="test-token",
    api=free_tag_api(),
    now=now,
)
git(stale_repo, "branch", "advanced-main", stale_candidate_sha)
git(stale_repo, "push", "-q", "origin", "advanced-main:main")
try:
    freeze.load_receipt(stale_repo, now=now)
    check(False, "receipt must fail after origin/main advances")
except freeze.CandidateFreezeError as exc:
    check(
        "origin/main moved" in str(exc) and "rerun candidate freeze" in str(exc),
        "receipt consumption refetches main and names the required re-freeze",
    )

print(f"candidate freeze contracts: {passed} passed, {failed} failed")
if failed:
    raise SystemExit(1)
