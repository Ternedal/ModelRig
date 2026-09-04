#!/usr/bin/env python3
"""Fail-closed regression for proof-scope Git failures (#674)."""
from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import proof_scope as P  # noqa: E402

passed = failed = 0


def check(condition: bool, message: str) -> None:
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS: {message}")
    else:
        failed += 1
        print(f"  FAIL: {message}")


print("proof_scope Git failure semantics:")

# The low-level adapter must preserve the distinction between successful empty
# output and a failed Git command. A non-repository directory is a deterministic
# local failure and needs no network or repository fixture.
with tempfile.TemporaryDirectory(prefix="modelrig-proof-scope-not-repo-") as td:
    check(
        P._git(Path(td), "rev-parse", "HEAD") is None,
        "_git returns None when Git exits non-zero",
    )

# Unknown proof names are unanswered questions, never reusable evidence.
check(
    P.scope_unchanged(ROOT, "not-a-proof", "a" * 40, "a" * 40) is None,
    "unknown proof name returns None even when the SHAs are equal",
)

# Equal strings are not enough. The commit must actually be readable before an
# exact-SHA receipt can be accepted.
with patch.object(P, "_git", return_value=None):
    check(
        P.scope_unchanged(ROOT, "workflows", "a" * 40, "a" * 40) is None,
        "unknown/unreadable exact SHA returns None rather than True",
    )

with patch.object(P, "_git", return_value="commit"):
    check(
        P.scope_unchanged(ROOT, "workflows", "a" * 40, "a" * 40) is True,
        "readable exact SHA remains reusable",
    )

# A failed name-only diff means the scope question is unanswered.
def fail_name_only(_root: Path, *args: str) -> str | None:
    if args[:2] == ("cat-file", "-t"):
        return "commit"
    if args[:2] == ("diff", "--name-only"):
        return None
    raise AssertionError(f"unexpected git call: {args!r}")


with patch.object(P, "_git", side_effect=fail_name_only):
    check(
        P.scope_unchanged(ROOT, "workflows", "a" * 40, "b" * 40) is None,
        "failed scope diff returns None rather than True",
    )
    check(
        P.changed_paths(ROOT, "workflows", "a" * 40, "b" * 40) == [],
        "changed_paths does not crash when Git cannot answer",
    )

# A content diff failure for a version-bearing file can never be used to claim
# that the change was only version bookkeeping.
with patch.object(P, "_git", return_value=None):
    check(
        P._kun_versionsbogholderi(
            ROOT,
            "worker/app/main.py",
            "a" * 40,
            "b" * 40,
        )
        is False,
        "failed content diff is not classified as version bookkeeping",
    )

# Reproduce the dangerous direction without constructing a damaged Git pack:
# name-only sees a version-site change, while the content diff is unreadable.
def changed_but_unreadable(_root: Path, *args: str) -> str | None:
    if args[:2] == ("cat-file", "-t"):
        return "commit"
    if args[:2] == ("diff", "--name-only"):
        return "worker/app/main.py"
    if args[:2] == ("diff", "--unified=0"):
        return None
    raise AssertionError(f"unexpected git call: {args!r}")


with patch.object(P, "_git", side_effect=changed_but_unreadable):
    check(
        P.scope_unchanged(ROOT, "workflows", "a" * 40, "b" * 40) is False,
        "unreadable changed version-site fails closed instead of permitting reuse",
    )

print(f"\n===== PROOF SCOPE FAIL-CLOSED: {passed} passed, {failed} failed =====")
raise SystemExit(1 if failed else 0)
