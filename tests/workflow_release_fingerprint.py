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


def commit_index(repo: Path, message: str) -> str:
    """Commit the index as it stands (for entries that have no working-tree file, such as gitlinks)."""
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

    # mode and link type are identity too (review P2 on #2412): chmod +x and a
    # symlink in place of a regular file with the same bytes both change it
    import os as _os
    if _os.name != "nt":
        target = repo / "scripts" / "op.py"
        target.chmod(target.stat().st_mode | 0o111)
        git(repo, "update-index", "--chmod=+x", "scripts/op.py")
        chmod_sha = commit_all(repo, "chmod +x")
        check(rf.fingerprint(repo, chmod_sha) != rf.fingerprint(repo, f"{chmod_sha}~1"), "an executable bit changes the fingerprint (mode is hashed)")
        (repo / "backend" / "main.go").unlink()
        _os.symlink("../VERSION", repo / "backend" / "main.go")
        link_sha = commit_all(repo, "symlink")
        check(rf.fingerprint(repo, link_sha) != rf.fingerprint(repo, f"{link_sha}~1"), "a symlink in place of a file changes the fingerprint")
        ok, _ = rf.equivalent(repo, f"{link_sha}~1", link_sha)
        check(not ok, "a symlink swap is not equivalent evidence")
        (repo / "backend" / "main.go").unlink()
        write(repo, "backend/main.go", LAYOUT["backend/main.go"] + "x\n")
        commit_all(repo, "restore file")
    # a gitlink (submodule pointer) is part of the identity as well
    git(repo, "update-index", "--add", "--cacheinfo", "160000," + "a" * 40 + ",worker/vendor-sub")
    gitlink_sha = commit_index(repo, "gitlink")
    check(rf.fingerprint(repo, gitlink_sha) != rf.fingerprint(repo, f"{gitlink_sha}~1"), "adding a gitlink changes the fingerprint")
    git(repo, "update-index", "--add", "--cacheinfo", "160000," + "b" * 40 + ",worker/vendor-sub")
    gitlink2_sha = commit_index(repo, "gitlink moved")
    check(rf.fingerprint(repo, gitlink2_sha) != rf.fingerprint(repo, gitlink_sha), "moving a gitlink changes the fingerprint")
    git(repo, "rm", "-q", "--cached", "worker/vendor-sub")
    commit_index(repo, "gitlink removed")

    # --- contract test 6: a dirty working tree does not matter ---------------
    head = git(repo, "rev-parse", "HEAD")
    fp_head = rf.fingerprint(repo, head)
    write(repo, "worker/app/entry.py", "print('dirty')\n")
    write(repo, "untracked.py", "x\n")
    check(rf.fingerprint(repo, head) == fp_head, "a dirty working tree does not change a commit's fingerprint")
    git(repo, "checkout", "--", "worker/app/entry.py")
    (repo / "untracked.py").unlink()

    # --- contract test 4: protected prefixes and documents -------------------
    for glob in ("worker/**", "scripts/*", "tests/**", "*.ps1", "*.cmd", "*.py", "*.bat", "VERSION", ".github/**", "**", "*", "backend/main.go", "scripts/**/*.py"):
        try:
            rf.parse_exclusions(glob + "\n")
            check(False, f"exclusion glob {glob!r} must be rejected")
        except rf.FingerprintError:
            check(True, f"exclusion glob {glob!r} is rejected")
    for glob in ("docs/**/*.md", "docs/**/*.png", "*.md", "LICENSE", ".github/ISSUE_TEMPLATE/**", "brand/**"):
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
    check(not ex.excludes("docs/run.PS1") and not ex.excludes("docs/run.Cmd") and not ex.excludes("docs/x.bat") and not ex.excludes("docs/tool.py"),
          "runnable files under docs/ are never excluded, whatever the case of the suffix (review P3 on #2412)")
    check(not ex.excludes("docs/bodyrig/schemas/render-frame.schema.json"), "a schema under docs/ that tests read is in the fingerprint")
    wide = rf.parse_exclusions("docs/**\n")  # a broad glob is accepted; the suffix guard still wins inside it
    check(wide.excludes("docs/notes.txt") and not wide.excludes("docs/run.PS1") and not wide.excludes("docs/Run.CMD") and not wide.excludes("docs/x.BAT") and not wide.excludes("docs/t.Py"),
          "under a broad docs/** glob, runnable suffixes in any case are still protected")
    check(ex.excludes("docs/design/mockup.png") and ex.excludes("docs/a/b/c.md"), "images and markdown under docs/ are the documentation class")
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
    check(rf.PROTECTED_FILES == ("VERSION",) and rf.PROTECTED_SUFFIXES == (".cmd", ".ps1", ".psm1", ".bat", ".py"), "VERSION and the runnable suffixes are protected")
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
print("contract tests 2, 3, 5 live in workflow_candidate_freeze, the system-gate contract and workflow_freeze_check; 7 is the recorded mutation sweep")
sys.exit(1 if failed else 0)
