"""The source fingerprint must identify the SOURCE, not the checkout (F-726).

The Windows appliance hashes its source tree and the code-identity gate compares
that hash to what a source checkout produces (F-607). The whole binding rests on
one assumption: byte-identical logical source produces an identical hash no
matter where it was checked out. Git breaks that assumption on its own -- with
core.autocrlf=true a file lands as CRLF on Windows and LF on the Linux CI runner
-- so without normalization the gate reports validated_code_mismatch on the rig
for a file nobody changed, and physical validation (F-701) cannot pass for a
spurious reason. That failure would look exactly like a real mismatch.

Nothing tested this mechanism before. It is the gate to the one thing that
matters, so it gets driven here.

Run: PYTHONPATH=worker python3 tests/worker_build_identity.py
"""
from __future__ import annotations

import hashlib
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "worker"))

from app.build_identity import _canonical_bytes  # noqa: E402

passed = failed = 0


def check(cond, msg):
    global passed, failed
    if cond:
        passed += 1
        print(f"  PASS: {msg}")
    else:
        failed += 1
        print(f"  FAIL: {msg}")


def _hash(path: Path) -> str:
    return hashlib.sha256(_canonical_bytes(path)).hexdigest()


# --- the same logical source hashes the same under any line ending ----------
_d = Path(tempfile.mkdtemp(prefix="kaliv-eol-"))
_lf = _d / "lf.py"
_lf.write_bytes(b"def f():\n    return 1\n")
_crlf = _d / "crlf.py"
_crlf.write_bytes(b"def f():\r\n    return 1\r\n")
_cr = _d / "cr.py"
_cr.write_bytes(b"def f():\r    return 1\r")

check(_hash(_lf) == _hash(_crlf),
      "LF and CRLF of identical source hash the same -- a Windows autocrlf "
      "checkout matches the CI checkout")
check(_hash(_lf) == _hash(_cr),
      "a lone CR (old-Mac style) normalizes too, so no checkout style leaks "
      "into the identity")

# --- normalization must not erase a REAL difference -------------------------
# The point is to ignore line endings, not content. A genuine code change must
# still change the hash, or the gate would wave through modified code.
_changed = _d / "changed.py"
_changed.write_bytes(b"def f():\n    return 2\n")  # 1 -> 2
check(_hash(_lf) != _hash(_changed),
      "a real content change still changes the hash -- normalization ignores "
      "line endings, not logic")

# A blank line added is a real change (the source is genuinely different) and
# must register, so normalization is not silently collapsing whitespace.
_blankline = _d / "blank.py"
_blankline.write_bytes(b"def f():\n\n    return 1\n")
check(_hash(_lf) != _hash(_blankline),
      "adding a blank line changes the hash -- only the CR/LF bytes are "
      "normalized, not the presence of lines")

# --- the bytes are actually normalized, not just compared -------------------
# Assert the canonical form contains no CR at all, so a downstream consumer that
# hashes _canonical_bytes for any reason gets a checkout-independent value.
check(b"\r" not in _canonical_bytes(_crlf),
      "the canonical bytes contain no CR, so anything hashing them is "
      "checkout-independent by construction")

# --- .gitattributes is the on-disk half, and must exist ---------------------
# The normalizer is the second line of defence; a committed .gitattributes is
# the first, keeping the working tree consistent so files arrive as LF in the
# first place. Both, because this is the gate to physical validation.
_root = Path(__file__).resolve().parents[1]
_ga = _root / ".gitattributes"
check(_ga.exists(), ".gitattributes exists -- the working tree is pinned to LF, "
                    "not left to each machine's autocrlf")
if _ga.exists():
    _text = _ga.read_text(encoding="utf-8")
    check("*.py    text eol=lf" in _text or "*.py text eol=lf" in _text,
          ".gitattributes pins *.py to LF -- the files the fingerprint reads "
          "cannot arrive as CRLF")
    for _ext in ("*.go", "*.kt", "*.json"):
        check(_ext in _text,
              f".gitattributes pins {_ext} too -- every source language the "
              "generators scan is covered")

print(f"\n===== BUILD IDENTITY: {passed} passed, {failed} failed =====")
raise SystemExit(1 if failed else 0)
