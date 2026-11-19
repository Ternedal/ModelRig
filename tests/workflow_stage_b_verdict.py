#!/usr/bin/env python3
"""Gate for scripts/stage_b_verdict.sh — the required queue check `stage-b-verdict`
(ADR-SYS-003 D3) and the campaign freeze guard (ADR-SYS-003 D7, contract test 7).

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

# --- D7: campaign freeze -----------------------------------------------------
rc, out = verdict(RESULT="success", DOCS_ONLY="false", EVENT="merge_group", FREEZE="1")
check(rc == 1 and "KALIV_FREEZE=1" in out and "not documentation-only" in out, "freeze on + code queue candidate → refused even with Stage B green")
rc, out = verdict(RESULT="skipped", DOCS_ONLY="true", EVENT="merge_group", FREEZE="1")
check(rc == 0, "freeze on + docs-only queue candidate → allowed")
rc, out = verdict(RESULT="success", DOCS_ONLY="", EVENT="merge_group", FREEZE="1")
check(rc == 1, "freeze on + unclassified candidate → refused (fail-closed when the class is unknown)")
rc, out = verdict(RESULT="success", DOCS_ONLY="false", EVENT="pull_request", DRAFT="false", FREEZE="1")
check(rc == 1 and "ADR-SYS-003 D7" in out, "freeze on + code pull request → reported red so the author sees it before enqueueing")
rc, out = verdict(RESULT="success", DOCS_ONLY="false", EVENT="push", FREEZE="1")
check(rc == 0 and "not a candidate" in out, "freeze on + push to main → not a candidate, not refused")
rc, out = verdict(RESULT="success", DOCS_ONLY="false", EVENT="workflow_dispatch", FREEZE="1")
check(rc == 0, "freeze on + dispatch → not a candidate")
for off in ("", "0", "true", "yes", "on", " 1"):
    rc, out = verdict(RESULT="success", DOCS_ONLY="false", EVENT="merge_group", FREEZE=off)
    check(rc == 0, f"FREEZE={off!r} is not a freeze; only the literal '1' is")
rc, out = verdict(RESULT="failure", DOCS_ONLY="false", EVENT="merge_group", FREEZE="1")
check(rc == 1 and "KALIV_FREEZE=1" in out, "freeze is judged first: the message names the freeze, not only the Stage B failure")

# --- the workflow uses the script, with the five inputs ---------------------
wf = (ROOT / ".github" / "workflows" / "exact-head-qualification.yml").read_text(encoding="utf-8")
job = wf.split("  stage-b-verdict:", 1)[1].split("\n  legacy-merge-tree-equivalence:", 1)[0]
check("run: bash scripts/stage_b_verdict.sh" in job, "stage-b-verdict runs the script, not inline shell")
for line in (
    "RESULT: ${{ needs.stage-b-slices.result }}",
    "DOCS_ONLY: ${{ needs.release-class.outputs.docs_only }}",
    "EVENT: ${{ github.event_name }}",
    "DRAFT: ${{ github.event.pull_request.draft }}",
    "FREEZE: ${{ vars.KALIV_FREEZE }}",
):
    check(line in job, f"stage-b-verdict passes {line.split(':')[0].strip()} from the right source")
check("ref: ${{ github.event.pull_request.head.sha || github.sha }}" in job, "the script is taken from the exact head being judged")
src = code_of(SCRIPT)
check('if [ "$FREEZE" = "1" ] && [ "$DOCS_ONLY" != "true" ]; then' in src, "freeze guard: literal '1' and anything but docs_only=true")
check("exit 0" not in src.split("case \"$RESULT\" in", 1)[0].replace("exit 1", ""), "no early success exit before the Stage B judgement")

print(f"===== STAGE B VERDICT: {PASSED} passed, {FAILED} failed =====")
sys.exit(1 if FAILED else 0)
