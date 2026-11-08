#!/usr/bin/env python3
"""build-and-release.yml runs only on a release tag (vX.Y.Z), so a branch can never be published.

Anders, 8 Nov 2026 (#2275): the workflow also has a workflow_dispatch trigger. Before this guard,
a dispatch on a BRANCH passed version-check (it skipped the tag assertion off a tag),
ensure-draft-release made a draft named after the branch, and the release job published it with
`--latest`. The rig's updater and the phone's in-app updater both read releases/latest, so an
untagged build would have reached both.

This test runs the guard's own shell script against branch and tag refs. It also checks that every
job inherits the guard through `needs`, and that the publishing job checks the ref again.

Run: python3 tests/workflow_release_tag_guard.py
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests" / "support"))
from source_code import code_of  # noqa: E402

WORKFLOW = ROOT / ".github" / "workflows" / "build-and-release.yml"
GUARD_STEP = "- name: Refuse anything but a release tag"

passed = failed = 0


def check(ok: bool, message: str) -> None:
    global passed, failed
    print(f"  {'PASS' if ok else 'FAIL'}: {message}")
    if ok:
        passed += 1
    else:
        failed += 1


# Read as code, not raw text: a commented-out guard must not satisfy these (workflow_gates_read_code).
code = code_of(WORKFLOW)
lines = code.splitlines()


def jobs() -> dict[str, list[str]]:
    """Job name -> its body lines (indentation kept)."""
    start = lines.index("jobs:")
    found: dict[str, list[str]] = {}
    name = None
    for line in lines[start + 1:]:
        m = re.match(r"^  ([A-Za-z0-9_-]+):\s*$", line)
        if m:
            name = m.group(1)
            found[name] = []
        elif line and not line.startswith(" "):
            break
        elif name:
            found[name].append(line)
    return found


def needs_of(body: list[str]) -> list[str]:
    for line in body:
        m = re.match(r"^    needs:\s*(.+)$", line)
        if m:
            return [n.strip() for n in m.group(1).strip("[] ").split(",") if n.strip()]
    return []


def run_block(body: list[str], step: str) -> str:
    """The `run: |` script of the named step, dedented; "exit 0" when the step is missing, so every
    refusal case below fails by name instead of the test crashing."""
    i = next((k for k, line in enumerate(body) if line.strip() == step), None)
    j = None if i is None else next((k for k in range(i + 1, len(body)) if body[k].strip().startswith("run: |")), None)
    if j is None:
        return "exit 0\n"
    indent = len(body[j]) - len(body[j].lstrip())
    block = []
    for line in body[j + 1:]:
        if line.strip() and len(line) - len(line.lstrip()) <= indent:
            break
        block.append(line)
    return textwrap.dedent("\n".join(block)) + "\n"


all_jobs = jobs()
version_check = all_jobs.get("version-check", [])

# 1. The guard is the first step of version-check: nothing is checked out or built before it.
steps = [line.strip() for line in version_check if line.strip().startswith("- ")]
check(bool(steps) and steps[0] == GUARD_STEP, f"version-check starts with '{GUARD_STEP[8:]}'")

# 2. The guard's own script, run as the runner runs it (bash -e), on branch and tag refs.
script = run_block(version_check, GUARD_STEP)
check("${{" not in script, "the guard reads the ref from env, not from an inline ${{ }} expression")


def guard(ref_type: str, ref_name: str) -> tuple[int, str]:
    env = dict(os.environ, REF_TYPE=ref_type, REF_NAME=ref_name)
    result = subprocess.run(["bash", "-e", "-c", script], env=env, capture_output=True, text=True)
    return result.returncode, result.stdout + result.stderr


cases = [
    ("branch", "main", 1, "a dispatch on main"),
    ("branch", "release/kaliv-v2.0.19-prep-20261108", 1, "a dispatch on the release-prep branch"),
    ("branch", "v2.0.19", 1, "a BRANCH named like a tag"),
    ("tag", "v2.0.19", 0, "the release tag v2.0.19"),
    ("tag", "v10.20.300", 0, "a release tag with multi-digit parts"),
    ("tag", "2.0.19", 1, "a tag without the v"),
    ("tag", "V2.0.14", 1, "an upper-case V tag (an empty V2.0.14 release exists from 8 Oct)"),
    ("tag", "v2.0.19-rc1", 1, "a tag with a suffix"),
    ("tag", "v2.0", 1, "a tag with two parts"),
    ("tag", "v2.0.19\nv2.0.19", 1, "a name spanning two lines"),
]
for ref_type, ref_name, want, label in cases:
    code_rc, out = guard(ref_type, ref_name)
    verdict = "runs" if want == 0 else "is refused"
    ok = code_rc == want and (want == 0 or "Nothing was built or published" in out)
    check(ok, f"{label} ({ref_type} {ref_name!r}) {verdict} (exit {code_rc})")

with tempfile.TemporaryDirectory() as tmp:
    marker = Path(tmp) / "injected"
    code_rc, _ = guard("tag", f"v1.2.3$(touch {marker})")
    check(code_rc == 1 and not marker.exists(), "a ref name with $(...) is refused as data, never executed")

# 3. No version check without the tag assertion (the old off-tag branch is gone).
check(re.search(r"version_tool\.py check(?! --tag)", code) is None,
      "version_tool.py check always asserts the tag")

# 4. Every job inherits the guard: version-check is an ancestor of all of them through `needs`.
graph = {name: needs_of(body) for name, body in all_jobs.items()}


def ancestors(name: str, seen: set[str] | None = None) -> set[str]:
    seen = set() if seen is None else seen
    for parent in graph.get(name, []):
        if parent not in seen:
            seen.add(parent)
            ancestors(parent, seen)
    return seen


unguarded = sorted(n for n in graph if n != "version-check" and "version-check" not in ancestors(n))
check(len(graph) >= 7 and not unguarded,
      f"all {len(graph) - 1} other jobs need version-check (unguarded: {unguarded or 'none'})")

# 5. The publishing job checks the ref again, independently of version-check.
release = all_jobs.get("release", [])
release_if = next((line.strip() for line in release if line.strip().startswith("if:")), "")
check("github.ref_type == 'tag'" in release_if and "!failure()" in release_if,
      f"the release job only runs on a tag and after no failure ({release_if})")
check(any("--draft=false --latest" in line for line in release), "publication with --latest is in that job")
check(sum("--draft=false --latest" in line for line in lines) == 1, "and nowhere else")

# 6. Rebuilding an existing tag by hand still works: dispatch stays, the tag check decides.
check("workflow_dispatch:" in code, "workflow_dispatch remains for rebuilding an existing tag")

print(f"\n===== RELEASE TAG GUARD: {passed} passed, {failed} failed =====")
sys.exit(1 if failed else 0)
