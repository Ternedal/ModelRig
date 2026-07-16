"""Contract test: every GitHub Action is pinned to a SHA.

A tag is a moving target. `actions/checkout@v4` means "whatever that tag points
at when CI next runs", and whoever can move the tag can run code with a token
that has write access to this repo. Pinning to a commit SHA is the difference
between "we trust this code" and "we trust these people, forever, silently".

This exists because the invariant broke the moment it depended on memory: the
Agent 3 merge brought in an unpinned actions/upload-artifact@v4 and nothing
said a word -- CI was green, review saw a useful feature, and main quietly lost
a property it had held since 1.58.42. That is how supply-chain hardening dies:
not by argument, but by riding in on something good.

Run: python3 tests/workflow_action_pins.py
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = sorted((ROOT / ".github" / "workflows").glob("*.yml"))

# `uses: owner/repo@ref` -- but not local (./) or docker:// references.
USES = re.compile(r"^\s*-?\s*uses:\s*([^\s#]+)")
SHA = re.compile(r"^[0-9a-f]{40}$")

passed = failed = 0


def check(cond, msg):
    global passed, failed
    if cond:
        passed += 1
        print(f"  PASS: {msg}")
    else:
        failed += 1
        print(f"  FAIL: {msg}")


check(len(WORKFLOWS) >= 3, f"{len(WORKFLOWS)} workflow files found")

unpinned: list[str] = []
pinned = 0
for wf in WORKFLOWS:
    for i, line in enumerate(wf.read_text(encoding="utf-8").splitlines(), 1):
        m = USES.match(line)
        if not m:
            continue
        ref = m.group(1)
        if ref.startswith("./") or ref.startswith("docker://"):
            continue
        if "@" not in ref:
            unpinned.append(f"{wf.name}:{i} {ref} (no ref at all)")
            continue
        _, at = ref.rsplit("@", 1)
        if SHA.match(at):
            pinned += 1
        else:
            unpinned.append(f"{wf.name}:{i} {ref}")

check(pinned > 0, f"{pinned} action references are SHA-pinned")
check(
    not unpinned,
    "every action is pinned to a SHA"
    if not unpinned
    else "UNPINNED ACTIONS (a tag can be moved under you): " + "; ".join(unpinned),
)

# Pins are worthless if the comment lies about which version it is, so at least
# require that a pinned line still says which version it MEANT -- that is what
# makes a Dependabot bump reviewable instead of an opaque hex swap.
missing_comment = []
for wf in WORKFLOWS:
    for i, line in enumerate(wf.read_text(encoding="utf-8").splitlines(), 1):
        m = USES.match(line)
        if not m or "@" not in m.group(1):
            continue
        _, at = m.group(1).rsplit("@", 1)
        if SHA.match(at) and "#" not in line:
            missing_comment.append(f"{wf.name}:{i}")
check(not missing_comment,
      "each pin says which version it is, in a comment"
      if not missing_comment
      else f"pinned but unlabelled: {', '.join(missing_comment)}")

# The detector must be able to fail, or it is decoration.
fake = "      - uses: actions/checkout@v4"
m = USES.match(fake)
check(m is not None and not SHA.match(m.group(1).rsplit("@", 1)[1]),
      "self-test: a tag-pinned action IS detected as unpinned")

print(f"\n===== ACTION PINS: {passed} passed, {failed} failed =====")
raise SystemExit(1 if failed else 0)
