"""Tests for read-path scoping (ISOLATION_DESIGN I1).

A path check is trusted to be an arbitrary-file-read barrier, so every known
escape is driven at it: `..` in various dresses, absolute paths outside the
root, the sibling-prefix trick, NUL bytes, and the Windows drive-relative /
UNC shapes. On POSIX the Windows-specific ones are exercised as ordinary
strings, which still proves the traversal logic; the point is that none of
them resolve INSIDE the root.

Run: PYTHONPATH=worker python3 tests/worker_read_scope.py
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "worker"))

from app.read_scope import PathDenied, ReadScope  # noqa: E402

passed = failed = 0


def check(cond, msg):
    global passed, failed
    if cond:
        passed += 1
        print(f"  PASS: {msg}")
    else:
        failed += 1
        print(f"  FAIL: {msg}")


def denied(scope, p) -> bool:
    try:
        scope.resolve(p)
        return False
    except PathDenied:
        return True


ROOT = os.path.abspath(os.path.join(os.sep, "data", "kaliv-docs"))
scope = ReadScope(ROOT)

# --- things that must be ALLOWED ---------------------------------------------

check(scope.resolve("notes.md") == os.path.join(ROOT, "notes.md"),
      "a plain relative name resolves under the root")
check(scope.resolve("sub/deep/report.pdf") == os.path.join(ROOT, "sub", "deep", "report.pdf"),
      "a nested relative path resolves under the root")
check(scope.resolve(ROOT) == ROOT, "the root itself is in scope")
check(scope.resolve(os.path.join(ROOT, "x.txt")) == os.path.join(ROOT, "x.txt"),
      "an absolute path already inside the root is allowed")
check(scope.contains("a/b/../c.txt"),
      "a '..' that stays inside the root is fine (a/c.txt)")

# --- traversal, in its various dresses ---------------------------------------

check(denied(scope, "../../../etc/passwd"), "classic ../ escape is refused")
check(denied(scope, "sub/../../escape.txt"),
      "a '..' that climbs OUT after going in is refused (net escape)")
check(denied(scope, os.path.join(os.sep, "etc", "passwd")),
      "an absolute path outside the root is refused")
check(denied(scope, os.path.join(os.sep, "data", "kaliv-docs-secrets", "x")),
      "the sibling-PREFIX trick is refused (kaliv-docs-secrets vs kaliv-docs)")

# --- malformed input ---------------------------------------------------------

check(denied(scope, ""), "empty path is refused")
check(denied(scope, "   "), "whitespace-only path is refused")
check(denied(scope, "ok\x00/etc/passwd"), "a NUL byte in the path is refused")

# --- Windows shapes (strings on POSIX, real on Windows) ----------------------
# None of these may resolve inside a POSIX root; the traversal reasoning is
# what is under test.
for weird in ("C:secret.txt", "C:\\Windows\\System32\\config",
              "\\\\server\\share\\x", "//server/share/x"):
    check(denied(scope, weird),
          f"windows-shaped path does not resolve inside a posix root: {weird!r}")

# --- resolve refuses rather than silently clamping ---------------------------
# The important behavioural promise: an out-of-root path is an ERROR, not
# quietly rewritten to something inside.
try:
    scope.resolve("../../elsewhere")
    check(False, "an out-of-root path must raise, not clamp")
except PathDenied as e:
    check("uden for" in str(e), "the refusal explains the path was out of root")

# --- a different root, to be sure it is the root that decides ----------------
other = ReadScope(os.path.abspath(os.path.join(os.sep, "srv", "readable")))
check(other.contains("index.html"), "a second root allows its own contents")
check(denied(other, os.path.join(ROOT, "notes.md")),
      "the second root refuses the first root's files")

print(f"\n===== READ SCOPE: {passed} passed, {failed} failed =====")
raise SystemExit(1 if failed else 0)
