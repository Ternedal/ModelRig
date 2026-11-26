#!/usr/bin/env python3
"""Gate for scripts/stage_b_verdict.sh — the required queue check `stage-b-verdict`
(ADR-SYS-003 D3). The campaign freeze (D7) is deliberately not here: see
tests/workflow_freeze_guard.py.

The script is a pure function of five environment variables, so every branch is
exercised here without GitHub. Fail-closed is the standard: anything that is not
an explicitly allowed outcome exits 1.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "stage_b_verdict.sh"
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


def verdict(**env: str) -> tuple[int, str]:
    base = {k: v for k, v in os.environ.items() if k not in ("RESULT", "DOCS_ONLY", "EVENT", "DRAFT", "FREEZE")}
    base.update(env)
    proc = subprocess.run(["bash", str(SCRIPT)], env=base, capture_output=True, text=True, check=False)
    return proc.returncode, proc.stdout + proc.stderr


# --- D3: Stage B result ------------------------------------------------------
rc, out = verdict(RESULT="success", EVENT="merge_group")
check(rc == 0 and "Stage B passed" in out, "queue candidate with Stage B success passes")
rc, out = verdict(RESULT="success", EVENT="pull_request", DRAFT="false")
check(rc == 0, "pull request with Stage B success passes")
rc, out = verdict(RESULT="skipped", DOCS_ONLY="true", EVENT="merge_group")
check(rc == 0 and "documentation-only" in out, "docs-only queue candidate may skip Stage B")
rc, out = verdict(RESULT="skipped", DOCS_ONLY="false", EVENT="pull_request", DRAFT="true")
check(rc == 0 and "draft" in out, "a draft PR may skip Stage B (deferred to ready_for_review)")
rc, out = verdict(RESULT="skipped", DOCS_ONLY="false", EVENT="merge_group")
check(rc == 1 and "skipped without an allowed reason" in out, "a code queue candidate whose Stage B was skipped is refused")
rc, out = verdict(RESULT="skipped", DOCS_ONLY="", EVENT="pull_request", DRAFT="false")
check(rc == 1, "an unclassified (docs_only empty) non-draft PR whose Stage B was skipped is refused")
rc, out = verdict(RESULT="skipped", DOCS_ONLY="true", EVENT="merge_group", DRAFT="true")
check(rc == 0, "draft flag is irrelevant in a merge group; docs-only decides")
rc, out = verdict(RESULT="skipped", DOCS_ONLY="false", EVENT="merge_group", DRAFT="true")
check(rc == 1, "a stale draft flag cannot excuse a skipped Stage B in a merge group")
for bad in ("failure", "cancelled", "", "SUCCESS", "succes"):
    rc, out = verdict(RESULT=bad, DOCS_ONLY="true", EVENT="merge_group")
    check(rc == 1 and "did not pass" in out, f"Stage B result {bad!r} is refused even for a docs-only candidate")

# --- D7 is NOT judged here (ChatGPT P1 on #2436): this script runs from the
# candidate's checkout. The freeze lives in scripts/freeze_guard.sh behind
# .github/workflows/freeze-guard.yml (tests/workflow_freeze_guard.py).
rc, out = verdict(RESULT="success", DOCS_ONLY="false", EVENT="merge_group", FREEZE="1")
check(rc == 0, "a FREEZE variable has no effect here — the freeze is enforced by freeze-guard.yml, not by a candidate-controlled script")

# --- the workflow uses the script, with the five inputs ---------------------
wf = (ROOT / ".github" / "workflows" / "exact-head-qualification.yml").read_text(encoding="utf-8")
job = wf.split("  stage-b-verdict:", 1)[1].split("\n  legacy-merge-tree-equivalence:", 1)[0]
check("run: bash scripts/stage_b_verdict.sh" in job, "stage-b-verdict runs the script, not inline shell")
for line in (
    "RESULT: ${{ needs.stage-b-slices.result }}",
    "DOCS_ONLY: ${{ needs.release-class.outputs.docs_only }}",
    "EVENT: ${{ github.event_name }}",
    "DRAFT: ${{ github.event.pull_request.draft }}",
):
    check(line in job, f"stage-b-verdict passes {line.split(':')[0].strip()} from the right source")
check("ref: ${{ github.event.pull_request.head.sha || github.sha }}" in job, "the script is taken from the exact head being judged")
src = code_of(SCRIPT)
check("exit 0" not in src.split("case \"$RESULT\" in", 1)[0].replace("exit 1", ""), "no early success exit before the Stage B judgement")

print(f"===== STAGE B VERDICT: {PASSED} passed, {FAILED} failed =====")
sys.exit(1 if FAILED else 0)
