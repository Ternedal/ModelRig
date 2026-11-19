#!/usr/bin/env python3
"""Gate for the campaign freeze guard (ADR-SYS-003 D7, contract test 7):
scripts/freeze_guard.sh and .github/workflows/freeze-guard.yml.

The guard's whole point is the trust boundary (ChatGPT P1 on #2436): it runs
from the BASE and judges the candidate head as an object, so a candidate that
rewrites the classifier or the guard itself to `exit 0` is still refused. That
adversarial case is exercised here on a fixture repository; the workflow file
is pinned to check out the base and run the base's script; and the ruleset
pins the workflow to main (tests/workflow_repository_authority.py).
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
from support.source_code import code_of  # noqa: E402

PASSED = 0
FAILED = 0


def check(cond: bool, label: str) -> None:
    global PASSED, FAILED
    if cond:
        PASSED += 1
        print(f"PASS: {label}")
    else:
        FAILED += 1
        print(f"FAIL: {label}")


IDENT = ["-c", "user.name=t", "-c", "user.email=t@example.invalid"]


def git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", *IDENT, *args], cwd=repo, check=True, capture_output=True, text=True).stdout


def write(repo: Path, rel: str, text: str) -> None:
    p = repo / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def commit_all(repo: Path, msg: str) -> str:
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", msg)
    return git(repo, "rev-parse", "HEAD").strip()


def guard(repo: Path, base: str, head: str, *, freeze: str, checkout: str | None = None) -> tuple[int, str]:
    git(repo, "checkout", "-q", checkout or base)
    env = {k: v for k, v in os.environ.items() if k != "FREEZE"}
    env["FREEZE"] = freeze
    proc = subprocess.run(["bash", str(repo / "scripts" / "freeze_guard.sh"), base, head],
                          cwd=repo, env=env, capture_output=True, text=True, check=False)
    return proc.returncode, proc.stdout + proc.stderr


with tempfile.TemporaryDirectory() as tmpdir:
    repo = Path(tmpdir) / "repo"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    write(repo, "README.md", "# fixture\n")
    write(repo, "worker/app/x.py", "x = 1\n")
    (repo / "scripts").mkdir()
    shutil.copy(ROOT / "scripts" / "release_fingerprint.py", repo / "scripts" / "release_fingerprint.py")
    shutil.copy(ROOT / "scripts" / "freeze_guard.sh", repo / "scripts" / "freeze_guard.sh")
    shutil.copy(ROOT / "release_fingerprint_exclusions.txt", repo / "release_fingerprint_exclusions.txt")
    base = commit_all(repo, "base with guard and classifier")

    git(repo, "checkout", "-q", "-b", "docs", base)
    write(repo, "docs/NOTE.md", "docs only\n")
    docs_head = commit_all(repo, "docs change")

    git(repo, "checkout", "-q", "-b", "code", base)
    write(repo, "worker/app/y.py", "y = 2\n")
    code_head = commit_all(repo, "code change")

    # The adversary: a code change that also rewrites the classifier AND the
    # guard so that, if either were taken from the head, the verdict would be
    # "allowed".
    git(repo, "checkout", "-q", "-b", "adversary", base)
    write(repo, "worker/app/evil.py", "z = 3\n")
    write(repo, "scripts/release_fingerprint.py", "import json, sys\nprint(json.dumps({'docs_only': True, 'offending_paths': []}))\nsys.exit(0)\n")
    write(repo, "scripts/freeze_guard.sh", "#!/usr/bin/env bash\necho 'nothing to see'\nexit 0\n")
    adversary_head = commit_all(repo, "code change that neuters classifier and guard")

    # Base moved on with code after the branch point (merge-base must be used).
    git(repo, "checkout", "-q", "main")
    write(repo, "worker/app/moved.py", "m = 4\n")
    base_moved = commit_all(repo, "main moved on")

    # --- freeze off: everything passes, nothing is classified -----------------
    for name, head in (("docs", docs_head), ("code", code_head), ("adversary", adversary_head)):
        rc, out = guard(repo, base_moved, head, freeze="")
        check(rc == 0 and "nothing to enforce" in out, f"freeze off: {name} candidate passes without classification")
    for off in ("0", "true", "yes", " 1", "on"):
        rc, _ = guard(repo, base_moved, code_head, freeze=off)
        check(rc == 0, f"FREEZE={off!r} is not a freeze; only the literal '1' is")

    # --- freeze on ---------------------------------------------------------------
    rc, out = guard(repo, base_moved, docs_head, freeze="1")
    check(rc == 0 and "documentation-only candidate; allowed" in out, "freeze on: docs-only candidate is allowed")
    rc, out = guard(repo, base_moved, code_head, freeze="1")
    check(rc == 1 and "not documentation-only; it may not land" in out, "freeze on: code candidate is refused")
    rc, out = guard(repo, base_moved, adversary_head, freeze="1")
    check(rc == 1 and "not documentation-only" in out,
          "freeze on: a candidate that rewrote the classifier and the guard to 'allowed' is STILL refused (base's files judge)")
    check('"docs_only": false' in out and "worker/app/evil.py" in out, "…and the base's classifier names the offending code path")

    # --- preconditions are enforced, fail-closed --------------------------------
    rc, out = guard(repo, base_moved, code_head, freeze="1", checkout=code_head)
    check(rc == 1 and "the checkout must be the base" in out, "refuses to judge from any checkout other than the base")
    rc, out = guard(repo, base_moved, adversary_head, freeze="1", checkout=adversary_head)
    check(rc == 0 and "nothing to see" in out,
          "fixture: run from the adversary's checkout the adversary's script would say yes — which is exactly why the workflow checks out the base")
    rc, out = guard(repo, base_moved, "0" * 40, freeze="1")
    check(rc == 1 and "is not available" in out, "an unknown head is refused while frozen")
    rc, out = guard(repo, base_moved, "0" * 40, freeze="")
    check(rc == 1, "an unknown head is refused even when the freeze is off (precondition, not policy)")

    # --- the classifier itself failing, or no common history: refused while frozen
    git(repo, "checkout", "-q", "main")
    write(repo, "scripts/release_fingerprint.py", "import sys\nprint('broken classifier')\nsys.exit(3)\n")
    base_broken = commit_all(repo, "base whose classifier errors")
    rc, out = guard(repo, base_broken, code_head, freeze="1")
    check(rc == 1 and "could not be classified" in out, "freeze on: a classifier error (exit >= 2) refuses — unknown is never allowed while frozen")
    rc, out = guard(repo, base_broken, code_head, freeze="")
    check(rc == 0, "freeze off: the classifier is not even consulted")
    git(repo, "checkout", "-q", "--orphan", "unrelated")
    for p_ in list(repo.iterdir()):
        if p_.name != ".git":
            shutil.rmtree(p_) if p_.is_dir() else p_.unlink()
    write(repo, "ORPHAN.md", "no shared history\n")
    orphan_head = commit_all(repo, "orphan")
    rc, out = guard(repo, base_moved, orphan_head, freeze="1")
    check(rc == 1 and "no merge-base" in out, "freeze on: a head with no common history is refused")

# --- the workflow never executes the candidate ---------------------------------
wf = code_of(ROOT / ".github" / "workflows" / "freeze-guard.yml")
on_block = wf.split("jobs:", 1)[0]
check(re.search(r"(?m)^  merge_group:\n    types: \[checks_requested\]\n    branches: \[main\]", on_block) is not None, "freeze-guard fires on merge_group for main")
check(re.search(r"(?m)^  pull_request:\n    types: \[opened, synchronize, reopened, ready_for_review\]\n    branches: \[main\]", on_block) is not None, "freeze-guard fires on pull_request for main (advisory until the ruleset is active)")
check("push:" not in on_block and "workflow_dispatch:" not in on_block, "pushes to main and dispatch are not candidates")
jobs = wf.split("jobs:", 1)[1]
check("ref: ${{ github.event.pull_request.base.sha || github.event.merge_group.base_sha }}" in jobs, "the checkout is the BASE")
check("github.event.pull_request.head.sha }}\n" not in jobs.split("steps:", 1)[1].split("- name: Fetch", 1)[0], "the candidate head is never checked out")
check('test "$(git rev-parse HEAD)" = "$BASE_SHA"' in jobs, "the job asserts the checkout is the base before anything else")
check('git fetch --no-tags origin "$HEAD_SHA"' in jobs and 'git cat-file -e "$HEAD_SHA^{commit}"' in jobs, "the candidate head is fetched as an object only")
check('bash scripts/freeze_guard.sh "$BASE_SHA" "$HEAD_SHA"' in jobs, "the base's guard script judges")
check('if [ ! -f scripts/freeze_guard.sh ]; then' in jobs and 'if [ "${FREEZE:-}" = "1" ]; then' in jobs and "refusing (cannot enforce)" in jobs,
      "a base without the guard: refused while frozen (cannot enforce), otherwise nothing to enforce — same semantics as the script")
check("FREEZE: ${{ vars.KALIV_FREEZE }}" in jobs, "the freeze marker is the repository variable KALIV_FREEZE")
check("permissions:\n  contents: read" in wf, "the workflow has read-only permissions")
check("actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1" in jobs, "actions/checkout is pinned by SHA")
src = code_of(ROOT / "scripts" / "freeze_guard.sh")
check('test "$(git rev-parse HEAD)" = "$base_sha"' in src, "the script refuses a checkout that is not the base")
check('python3 -B scripts/release_fingerprint.py --repository-root "$root" changed "$merge_base" "$head_sha"' in src, "the script classifies with the BASE's classifier over merge-base..head")
check('if [ "$FREEZE" != "1" ]; then' in src, "only the literal '1' is a freeze")

print(f"===== FREEZE GUARD: {PASSED} passed, {FAILED} failed =====")
sys.exit(1 if FAILED else 0)
