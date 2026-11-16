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
    # ADR-SYS-002 D2: the documentation class, as in the real repository.
    (root / "release_fingerprint_exclusions.txt").write_text(
        (ROOT / "release_fingerprint_exclusions.txt").read_text(encoding="utf-8"), encoding="utf-8"
    )
    (root / "docs").mkdir()
    (root / "docs" / "GUIDE.md").write_text("# guide\n", encoding="utf-8")
    (root / "HANDOFF.md").write_text("# handoff\n", encoding="utf-8")
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

skipped = {
    "name": "ci",
    "head_sha": "a" * 40,
    "status": "completed",
    "conclusion": "skipped",
    "id": 3,
}
check(
    anchor._latest_by_name([skipped, newest, older])["ci"]["id"] == 2,
    "a newer skipped no-op run does not hide the latest executable run",
)

runs_with_skipped_codeql = green_runs()["workflow_runs"]
runs_with_skipped_codeql.insert(
    0, {"name": "codeql", "status": "completed", "conclusion": "skipped"}
)
check(
    freeze._workflow_checks(runs_with_skipped_codeql)["codeql"] == "success",
    "candidate freeze ignores a newer skipped no-op and accepts older exact-SHA success",
)

skipped_only_codeql = [
    run for run in green_runs()["workflow_runs"] if run["name"] != "codeql"
]
skipped_only_codeql.insert(
    0, {"name": "codeql", "status": "completed", "conclusion": "skipped"}
)
try:
    freeze._workflow_checks(skipped_only_codeql)
    check(False, "skipped-only workflow evidence must not satisfy candidate freeze")
except freeze.CandidateFreezeError:
    check(True, "skipped-only workflow evidence fails closed")

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

import json as _json
_unchanged_path = repo / freeze.DEFAULT_REPORT
_unchanged = _json.loads(_unchanged_path.read_text(encoding="utf-8"))
for mutate, fragment, label in (
    (lambda a: dict(a, release_fingerprint="1" * 64), "anchor release fingerprint no longer matches", "forged anchor fingerprint on the unchanged-main path"),
    (lambda a: {k: v for k, v in a.items() if k != "release_fingerprint"}, "anchor release fingerprint is missing", "missing anchor fingerprint on the unchanged-main path"),
    (lambda a: dict(a, release_fingerprint="not-hex"), "anchor release fingerprint is missing", "non-canonical anchor fingerprint on the unchanged-main path"),
):
    bad = dict(_unchanged); bad["main_anchor"] = mutate(_unchanged["main_anchor"])
    _unchanged_path.write_text(_json.dumps(bad), encoding="utf-8")
    try:
        freeze.load_receipt(repo, now=now)
        check(False, f"{label} must be rejected")
    except freeze.CandidateFreezeError as exc:
        check(fragment in str(exc), f"{label} is rejected")
_unchanged_path.write_text(_json.dumps(_unchanged), encoding="utf-8")
freeze.load_receipt(repo, now=now)
check(True, "the restored receipt is accepted again")

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

# ADR-SYS-002 D7: the receipt carries the release fingerprint of candidate and anchor.
check(
    len(receipt["candidate"].get("release_fingerprint", "")) == 64
    and len(receipt["main_anchor"].get("release_fingerprint", "")) == 64,
    "receipt records release fingerprints for candidate and main anchor (D7)",
)

# ADR-SYS-002 D3 / contract test 2: a documentation-only advance of origin/main
# keeps the freeze; a code advance or a rewritten main does not.
docs_repo, docs_main_sha, docs_candidate_sha = fixture()
freeze.create_receipt(docs_candidate_sha, root=docs_repo, token="test-token", api=free_tag_api(), now=now)
git(docs_repo, "switch", "-q", "-c", "main-docs", docs_main_sha)
(docs_repo / "docs" / "GUIDE.md").write_text("# guide\nmore words\n", encoding="utf-8")
(docs_repo / "HANDOFF.md").write_text("# handoff\nstatus line\n", encoding="utf-8")
(docs_repo / "docs" / "NEW.md").write_text("new doc\n", encoding="utf-8")
git(docs_repo, "add", "-A")
git(docs_repo, "commit", "-q", "-m", "docs only on main")
git(docs_repo, "push", "-q", "origin", "main-docs:main")
git(docs_repo, "switch", "-q", "candidate")
try:
    freeze.load_receipt(docs_repo, now=now)
    check(True, "receipt survives a documentation-only advance of origin/main (D3)")
except freeze.CandidateFreezeError as exc:
    check(False, f"docs-only main advance must keep the freeze: {exc}")

# a receipt whose recorded fingerprint is not the candidate's is rejected
docs_receipt_path = docs_repo / freeze.DEFAULT_REPORT
docs_receipt = _json.loads(docs_receipt_path.read_text(encoding="utf-8"))
tampered = dict(docs_receipt)
tampered["candidate"] = dict(docs_receipt["candidate"], release_fingerprint="0" * 64)
docs_receipt_path.write_text(_json.dumps(tampered), encoding="utf-8")
try:
    freeze.load_receipt(docs_repo, now=now)
    check(False, "a receipt with a foreign release fingerprint must be rejected")
except freeze.CandidateFreezeError as exc:
    check("no longer matches the candidate" in str(exc), "a tampered release fingerprint is rejected")

# the anchor's fingerprint is bound too (ChatGPT review on #2412): missing or forged -> rejected,
# on the unchanged-main path as well as after a docs-only advance
for label, repo_, sha_ in (("after docs-only advance", docs_repo, None),):
    receipt_path_ = repo_ / freeze.DEFAULT_REPORT
    good = _json.loads(receipt_path_.read_text(encoding="utf-8"))
    forged = dict(good); forged["main_anchor"] = dict(good["main_anchor"], release_fingerprint="1" * 64)
    receipt_path_.write_text(_json.dumps(forged), encoding="utf-8")
    try:
        freeze.load_receipt(repo_, now=now)
        check(False, f"a forged anchor fingerprint must be rejected ({label})")
    except freeze.CandidateFreezeError as exc:
        check("anchor release fingerprint no longer matches" in str(exc), f"a forged anchor fingerprint is rejected ({label})")
    missing = dict(good); missing["main_anchor"] = {k: v for k, v in good["main_anchor"].items() if k != "release_fingerprint"}
    receipt_path_.write_text(_json.dumps(missing), encoding="utf-8")
    try:
        freeze.load_receipt(repo_, now=now)
        check(False, f"a missing anchor fingerprint must be rejected ({label})")
    except freeze.CandidateFreezeError as exc:
        check("anchor release fingerprint is missing" in str(exc), f"a missing anchor fingerprint is rejected ({label})")
    receipt_path_.write_text(_json.dumps(good), encoding="utf-8")

# a receipt whose anchor the candidate does not contain is rejected even when main sits on that anchor
advanced_main = git(docs_repo, "rev-parse", "origin/main")
tampered = dict(docs_receipt)
tampered["main_anchor"] = dict(docs_receipt["main_anchor"], git_sha=advanced_main)
docs_receipt_path.write_text(_json.dumps(tampered), encoding="utf-8")
try:
    freeze.load_receipt(docs_repo, now=now)
    check(False, "an anchor outside the candidate's history must be rejected")
except freeze.CandidateFreezeError as exc:
    check("does not contain" in str(exc), "the candidate must still contain the frozen anchor")
docs_receipt_path.write_text(_json.dumps(docs_receipt), encoding="utf-8")

# the same repository, main advanced again with one byte of code: rejected, naming the path
git(docs_repo, "switch", "-q", "main-docs")
(docs_repo / "worker" / "app" / "build_identity.py").write_text(
    "def code_fingerprint():\n    return 'c' * 64\n", encoding="utf-8"
)
git(docs_repo, "add", "-A")
git(docs_repo, "commit", "-q", "-m", "code on main")
git(docs_repo, "push", "-q", "origin", "main-docs:main")
git(docs_repo, "switch", "-q", "candidate")
try:
    freeze.load_receipt(docs_repo, now=now)
    check(False, "a code advance of origin/main must break the freeze")
except freeze.CandidateFreezeError as exc:
    check(
        "non-documentation changes" in str(exc) and "worker/app/build_identity.py" in str(exc)
        and "rerun candidate freeze" in str(exc),
        "a code advance of origin/main is rejected and names the offending path",
    )

# a protected document (campaign runbook) is code for this purpose
runbook_repo, runbook_main_sha, runbook_candidate_sha = fixture()
freeze.create_receipt(runbook_candidate_sha, root=runbook_repo, token="test-token", api=free_tag_api(), now=now)
git(runbook_repo, "switch", "-q", "-c", "main-runbook", runbook_main_sha)
(runbook_repo / "RIGDAG_SIMPEL.md").write_text("# rigdag\nnew step\n", encoding="utf-8")
git(runbook_repo, "add", "-A")
git(runbook_repo, "commit", "-q", "-m", "runbook on main")
git(runbook_repo, "push", "-q", "origin", "main-runbook:main")
git(runbook_repo, "switch", "-q", "candidate")
try:
    freeze.load_receipt(runbook_repo, now=now)
    check(False, "a campaign runbook change on main must break the freeze (protected document)")
except freeze.CandidateFreezeError as exc:
    check("RIGDAG_SIMPEL.md" in str(exc), "a protected document on main is treated as a code change")

# a rewritten main whose history no longer holds the anchor is a new main
rewrite_repo, rewrite_main_sha, rewrite_candidate_sha = fixture()
freeze.create_receipt(rewrite_candidate_sha, root=rewrite_repo, token="test-token", api=free_tag_api(), now=now)
git(rewrite_repo, "switch", "-q", "--orphan", "rewritten")
(rewrite_repo / "ORPHAN.md").write_text("orphan\n", encoding="utf-8")
git(rewrite_repo, "add", "ORPHAN.md")
git(rewrite_repo, "commit", "-q", "-m", "rewritten main")
git(rewrite_repo, "push", "-q", "--force", "origin", "rewritten:main")
git(rewrite_repo, "switch", "-q", "candidate")
try:
    freeze.load_receipt(rewrite_repo, now=now)
    check(False, "a rewritten origin/main must break the freeze")
except freeze.CandidateFreezeError as exc:
    check("not in its history" in str(exc), "a rewritten origin/main is rejected as a new main")

# a receipt without the fingerprint (pre-ADR) is not accepted silently
legacy_repo, legacy_main_sha, legacy_candidate_sha = fixture()
freeze.create_receipt(legacy_candidate_sha, root=legacy_repo, token="test-token", api=free_tag_api(), now=now)
legacy_path = legacy_repo / freeze.DEFAULT_REPORT
legacy = _json.loads(legacy_path.read_text(encoding="utf-8"))
del legacy["candidate"]["release_fingerprint"]
legacy_path.write_text(_json.dumps(legacy), encoding="utf-8")
try:
    freeze.load_receipt(legacy_repo, now=now)
    check(False, "a receipt without a release fingerprint must be rejected")
except freeze.CandidateFreezeError as exc:
    check("release fingerprint is missing" in str(exc), "a pre-ADR receipt is rejected and asks for a re-freeze")

print(f"candidate freeze contracts: {passed} passed, {failed} failed")
if failed:
    raise SystemExit(1)
