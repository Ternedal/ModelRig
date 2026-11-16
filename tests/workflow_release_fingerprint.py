#!/usr/bin/env python3
"""ADR-SYS-002 contract tests 1, 4, 6 and the D4 equivalence rule.

These tests pin the release fingerprint's properties on a throwaway Git
repository built here, so they hold on any checkout and any platform:

1. A commit that touches only the documentation class leaves the fingerprint
   unchanged; a one-byte change in each protected class changes it.
4. An exclusion list that names a protected prefix is rejected; a protected
   document is in the fingerprint even though ``*.md`` is excluded (one byte
   in RIGDAG_SIMPEL.md moves it, one byte in HANDOFF.md does not); the
   protected lists are pinned verbatim.
6. The fingerprint is a function of the commit: a dirty working tree does not
   change it.
D4. ``equivalent()`` accepts an ancestor with the same fingerprint and a
   different tree, and rejects a different fingerprint, a non-ancestor and a
   descendant.

Contract tests 2, 3, 5 and 7 (freeze receipt, system gate and qualifiers,
tag placement) belong to the slices that change those scripts; they are not
here yet, and this file says so rather than pretending.

Run: python3 tests/workflow_release_fingerprint.py
"""
from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.dont_write_bytecode = True
sys.path.insert(0, str(ROOT / "scripts"))
import release_fingerprint as rf  # noqa: E402

passed = failed = 0


def check(ok: bool, label: str) -> None:
    global passed, failed
    if ok:
        passed += 1
    else:
        failed += 1
        print(f"FAIL: {label}")


def git(repo: Path, *args: str) -> str:
    proc = subprocess.run(["git", *args], cwd=str(repo), capture_output=True, text=True, check=True)
    return proc.stdout.strip()


def commit_all(repo: Path, message: str) -> str:
    git(repo, "add", "-A")
    git(repo, "-c", "user.name=t", "-c", "user.email=t@example.invalid", "commit", "-q", "-m", message)
    return git(repo, "rev-parse", "HEAD")


def write(repo: Path, relative: str, text: str) -> None:
    path = repo / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


LAYOUT = {
    "VERSION": "2.0.21\n",
    "worker/app/main.py": "print('worker')\n",
    "backend/main.go": "package main\n",
    "android/app/A.kt": "class A\n",
    "desktop/D.kt": "class D\n",
    "scripts/op.py": "print('op')\n",
    "scripts/op.ps1": "Write-Host 'op'\n",
    "tests/t.py": "assert True\n",
    "deploy/run.ps1": "Write-Host 'run'\n",
    ".github/workflows/ci.yml": "name: ci\n",
    "LAUNCH.cmd": "@echo off\n",
    "docs/GUIDE.md": "# guide\n",
    "README.md": "# readme\n",
    "HANDOFF.md": "# handoff\n",
    "RIGDAG_SIMPEL.md": "# rigdag\n",
    "STAGED_PHYSICAL_PROMOTION.md": "# promotion\n",
    "CURRENT_STATE.md": "# state\n",
    "LICENSE": "MIT\n",
    ".github/PULL_REQUEST_TEMPLATE.md": "# pr\n",
}
PROTECTED_EDITS = [
    "VERSION", "worker/app/main.py", "backend/main.go", "android/app/A.kt", "desktop/D.kt",
    "scripts/op.py", "scripts/op.ps1", "tests/t.py", "deploy/run.ps1", ".github/workflows/ci.yml",
    "LAUNCH.cmd", "RIGDAG_SIMPEL.md", "STAGED_PHYSICAL_PROMOTION.md", "CURRENT_STATE.md",
]
DOC_EDITS = ["docs/GUIDE.md", "README.md", "HANDOFF.md", "LICENSE", ".github/PULL_REQUEST_TEMPLATE.md"]

with tempfile.TemporaryDirectory() as tmpdir:
    repo = Path(tmpdir)
    git(repo, "init", "-q", "-b", "main")
    for relative, text in LAYOUT.items():
        write(repo, relative, text)
    write(repo, rf.EXCLUSIONS_FILE, (ROOT / rf.EXCLUSIONS_FILE).read_text(encoding="utf-8"))
    base = commit_all(repo, "base")
    fp_base = rf.fingerprint(repo, base)
    check(len(fp_base) == 64, "fingerprint is a 64-hex digest")
    check(rf.fingerprint(repo, base) == fp_base, "fingerprint is deterministic")

    # --- contract test 1: documentation class vs protected classes ---------
    for relative in DOC_EDITS:
        write(repo, relative, LAYOUT[relative] + "x\n")
    docs_commit = commit_all(repo, "docs only")
    check(rf.fingerprint(repo, docs_commit) == fp_base, "a docs-only commit leaves the fingerprint unchanged")
    ok, offending = rf.docs_only(repo, base, docs_commit)
    check(ok and offending == [], "docs_only() says yes for a docs-only move")
    for relative in PROTECTED_EDITS:
        write(repo, relative, LAYOUT[relative] + "x\n")
        sha = commit_all(repo, f"touch {relative}")
        before = rf.fingerprint(repo, f"{sha}~1")
        check(rf.fingerprint(repo, sha) != before, f"one byte in {relative} changes the fingerprint")
        ok, offending = rf.docs_only(repo, f"{sha}~1", sha)
        check(not ok and offending == [relative], f"docs_only() names {relative} as offending")

    # a rename inside the documentation class is still docs-only; a new code file is not
    git(repo, "mv", "docs/GUIDE.md", "docs/GUIDE2.md")
    renamed = commit_all(repo, "rename doc")
    check(rf.fingerprint(repo, renamed) == rf.fingerprint(repo, f"{renamed}~1"), "renaming a doc leaves the fingerprint unchanged")
    write(repo, "worker/app/new.py", "x = 1\n")
    added = commit_all(repo, "add code")
    check(rf.fingerprint(repo, added) != rf.fingerprint(repo, f"{added}~1"), "adding a code file changes the fingerprint")
    (repo / "worker/app/new.py").unlink()
    removed = commit_all(repo, "remove code")
    check(rf.fingerprint(repo, removed) != rf.fingerprint(repo, f"{removed}~1"), "removing a code file changes the fingerprint")
    check(rf.fingerprint(repo, removed) == rf.fingerprint(repo, f"{added}~1"), "the same tree content gives the same fingerprint again")

    # moving a code file without changing its bytes is still a code change
    git(repo, "mv", "worker/app/main.py", "worker/app/entry.py")
    moved = commit_all(repo, "move code")
    check(rf.fingerprint(repo, moved) != rf.fingerprint(repo, f"{moved}~1"), "renaming a code file changes the fingerprint (paths are hashed, not only blobs)")

    # --- contract test 6: a dirty working tree does not matter ---------------
    head = git(repo, "rev-parse", "HEAD")
    fp_head = rf.fingerprint(repo, head)
    write(repo, "worker/app/entry.py", "print('dirty')\n")
    write(repo, "untracked.py", "x\n")
    check(rf.fingerprint(repo, head) == fp_head, "a dirty working tree does not change a commit's fingerprint")
    git(repo, "checkout", "--", "worker/app/entry.py")
    (repo / "untracked.py").unlink()

    # --- contract test 4: protected prefixes and documents -------------------
    for glob in ("worker/**", "scripts/*", "tests/**", "*.ps1", "*.cmd", "VERSION", ".github/**", "**", "*", "backend/main.go", "scripts/**/*.py"):
        try:
            rf.parse_exclusions(glob + "\n")
            check(False, f"exclusion glob {glob!r} must be rejected")
        except rf.FingerprintError:
            check(True, f"exclusion glob {glob!r} is rejected")
    for glob in ("docs/**", "*.md", "LICENSE", ".github/ISSUE_TEMPLATE/**", "brand/**"):
        try:
            rf.parse_exclusions(glob + "\n")
            check(True, f"exclusion glob {glob!r} is accepted")
        except rf.FingerprintError as exc:
            check(False, f"exclusion glob {glob!r} must be accepted: {exc}")
    try:
        rf.parse_exclusions("# only a comment\n")
        check(False, "an empty exclusion list is rejected")
    except rf.FingerprintError:
        check(True, "an empty exclusion list is rejected")
    ex = rf.load_exclusions(ROOT)
    check(ex.excludes("HANDOFF.md") and ex.excludes("docs/README.md") and ex.excludes("LICENSE"), "the real list excludes HANDOFF, docs/ and LICENSE")
    for doc in rf.PROTECTED_DOCUMENTS:
        check(not ex.excludes(doc), f"protected document {doc} is never excluded")
    check(not ex.excludes("worker/app/README.md") and not ex.excludes("scripts/notes.md"), "a .md under a protected prefix is never excluded")
    check(not ex.excludes("START_STAGE_B_TEST.cmd") and not ex.excludes("verify-repository-authority.ps1"), "root .cmd and .ps1 are never excluded")
    loose = rf.parse_exclusions("L*\nv*\n")  # accepted: no protected sample starts with L or v
    check(loose.excludes("LICENSE") and not loose.excludes("LAUNCH.cmd") and not loose.excludes("verify-repository-authority.ps1"),
          "a glob that happens to match a root .cmd/.ps1 still cannot exclude it (suffix protection)")
    check(rf.PROTECTED_DOCUMENTS == (
        "RIGDAG_SIMPEL.md", "STAGED_PHYSICAL_PROMOTION.md", "STAGE_B_UPDATER_EVIDENCE.md",
        "CURRENT_STATE.md", "ACTIVATION_READINESS.md", "ROUTE_INVENTORY.md",
    ), "the protected documents are pinned verbatim (ADR-SYS-002 D2, Q1, Q2)")
    check(rf.PROTECTED_PREFIXES == (
        "worker/", "backend/", "android/", "desktop/", "vr/", "renderers/", "bodyrig/", "scripts/", "tests/",
        "deploy/", "tools/", "contracts/", ".github/workflows/",
    ), "the protected prefixes are pinned verbatim (ADR-SYS-002 D2)")
    check(rf.PROTECTED_FILES == ("VERSION",) and rf.PROTECTED_SUFFIXES == (".cmd", ".ps1"), "VERSION, .cmd and .ps1 are protected")
    for doc in rf.PROTECTED_DOCUMENTS:
        check((ROOT / doc).is_file(), f"protected document {doc} exists in this repository")

    # --- D4: equivalent() ------------------------------------------------------
    anchor = git(repo, "rev-parse", "HEAD")
    write(repo, "HANDOFF.md", "# handoff\nstatus line\n")
    docs_after = commit_all(repo, "handoff status")
    ok, reason = rf.equivalent(repo, anchor, docs_after)
    check(ok and "ancestor" in reason, "an ancestor with the same fingerprint and a different tree is equivalent")
    check(git(repo, "rev-parse", f"{anchor}^{{tree}}") != git(repo, "rev-parse", f"{docs_after}^{{tree}}"), "…and the trees really differ")
    ok, _ = rf.equivalent(repo, docs_after, anchor)
    check(not ok, "a descendant is not equivalent (direction is evidence -> pin)")
    ok, _ = rf.equivalent(repo, anchor, anchor)
    check(ok, "the same commit is equivalent to itself")
    write(repo, "worker/app/entry.py", "print('changed')\n")
    code_after = commit_all(repo, "code")
    ok, reason = rf.equivalent(repo, anchor, code_after)
    check(not ok and "fingerprint differs" in reason, "an ancestor with a different fingerprint is not equivalent")
    git(repo, "checkout", "-q", "-b", "side", anchor)
    write(repo, "docs/SIDE.md", "side\n")
    side = commit_all(repo, "side docs")
    ok, reason = rf.equivalent(repo, side, code_after)
    check(not ok and "not an ancestor" in reason, "a non-ancestor is not equivalent even with docs-only content")
    git(repo, "checkout", "-q", "main")

    # --- the CLI answers with exit codes ---------------------------------------
    cli = [sys.executable, "-B", str(ROOT / "scripts" / "release_fingerprint.py"), "--repository-root", str(repo)]
    r = subprocess.run([*cli, "equivalent", anchor, docs_after], capture_output=True, text=True)
    check(r.returncode == 0 and '"equivalent": true' in r.stdout, "CLI equivalent exits 0 on equivalence")
    r = subprocess.run([*cli, "equivalent", anchor, code_after], capture_output=True, text=True)
    check(r.returncode == 1 and '"equivalent": false' in r.stdout, "CLI equivalent exits 1 otherwise")
    r = subprocess.run([*cli, "changed", anchor, code_after], capture_output=True, text=True)
    check(r.returncode == 1 and "worker/app/entry.py" in r.stdout, "CLI changed exits 1 and names the offending path")
    r = subprocess.run([*cli, "compute", "not-a-commit"], capture_output=True, text=True)
    check(r.returncode == 2 and '"ok": false' in r.stdout, "CLI fails closed on an unknown commit")

# --- the real repository ------------------------------------------------------
r = subprocess.run([sys.executable, "-B", str(ROOT / "scripts" / "release_fingerprint.py"), "check-exclusions"], cwd=str(ROOT), capture_output=True, text=True)
check(r.returncode == 0, "the repository's exclusion list is valid")

print(f"{passed} passed, {failed} failed")
print("not covered here (later slices): contract tests 2 (freeze receipt), 3 (gate + qualifiers), 5 (tag on candidate), 7 (mutations in those scripts)")
sys.exit(1 if failed else 0)
