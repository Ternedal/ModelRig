#!/usr/bin/env python3
"""Keep latest PR-head qualification prompt without weakening main checks."""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "support"))
from source_code import code_of  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = code_of(ROOT / ".github" / "workflows" / "exact-head-qualification.yml")

assert "push:\n    branches: [main]" in WORKFLOW
# CI-tiering (#2413): ready_for_review must be a trigger, because a draft that
# becomes ready has to be re-qualified WITH Stage-B on the same head.
assert "pull_request:\n    types: [opened, synchronize, reopened, ready_for_review, closed]" in WORKFLOW
assert "workflow_dispatch:" in WORKFLOW

# Only the top-level exact-head workflow group may supersede previous PR heads.
# PR runs share their PR-number key to supersede old heads. Main and dispatch
# use per-run IDs to avoid GitHub evicting a pending run within a shared group.
match = re.search(
    r"(?ms)^concurrency:\n(?P<body>.*?)(?=^permissions:)", WORKFLOW
)
assert match is not None, "top-level exact-head concurrency must exist"
group = match.group("body")
assert (
    "group: ${{ github.workflow }}-${{ github.event_name == 'pull_request' && github.event.pull_request.number || github.run_id }}"
    in group
), "PRs must be grouped by number while main/dispatch are unique by run ID"
assert (
    "cancel-in-progress: ${{ github.event_name == 'pull_request' }}" in group
), "obsolete PR runs must be superseded; main/dispatch must be preserved"
assert "cancel-in-progress: false" not in group
assert "github.run_id" in group, "main/dispatch queues need independent groups"
assert "github.ref }}" not in group, "shared main ref would evict pending gates"

# A canceled obsolete head has no authority over the new head. Retain exact
# source checkout, all Stage-B shards, and merge-tree equivalence requirement.
assert 'ref: ${{ github.event_name == \'pull_request\' && github.event.pull_request.head.sha || github.sha }}' in WORKFLOW
assert "test \"$actual\" = \"$EXPECTED_SHA\"" in WORKFLOW
assert "uses: ./.github/workflows/_stage_b_slices.yml" in WORKFLOW
assert "head_sha: ${{ github.event_name == 'pull_request' && github.event.pull_request.head.sha || github.sha }}" in WORKFLOW

# CI-tiering (#2413): Stage-B runs on main pushes, on dispatch, and on PRs that
# are not drafts. The draft condition must sit on the stage-b-slices job ONLY:
# exact-head-core and merge-tree equivalence still run on every draft push, and
# nothing may run Stage-B on a closed PR.
stage_b = re.search(r"(?ms)^  stage-b-slices:\n(?P<body>.*?)(?=^  [a-z-]+:\n)", WORKFLOW)
assert stage_b is not None, "stage-b-slices job must exist"
stage_b_if = stage_b.group("body")
assert "github.event.pull_request.draft != true" in stage_b_if, "Stage-B must be skipped on draft PRs (#2413)"
assert "github.event.action != 'closed'" in stage_b_if, "Stage-B must still skip closed PRs"
assert "(github.event_name != 'pull_request' && github.event_name != 'merge_group') ||" in stage_b_if, "main pushes and dispatch must still run Stage-B unconditionally"
# Docs-only tiering (ADR-SYS-002 D1 applied to CI): a release-class job runs
# scripts/release_fingerprint.py on merge-base..head and Stage-B is skipped when
# the PR is documentation-only. Fail-closed: the job exists only for PRs, Stage-B
# consults it through needs.* with !cancelled() (never always(), which would run
# Stage-B in a cancelled run), and an empty/failed classification runs Stage-B.
rc = re.search(r"(?ms)^  release-class:\n(?P<body>.*?)(?=^  [a-z-]+:\n)", WORKFLOW)
assert rc is not None, "release-class job must exist"
rc_body = rc.group("body")
assert "(github.event_name == 'pull_request' && github.event.action != 'closed') ||" in rc_body and "github.event_name == 'merge_group'" in rc_body, "release-class runs only for open PRs and merge groups"
assert "github.event_name == 'push'" not in rc_body, "release-class never runs on pushes to main"
assert "fetch-depth: 0" in rc_body, "release-class needs history to find the merge-base"
assert 'ref: ${{ github.event.pull_request.head.sha || github.sha }}' in rc_body, "release-class checks out the exact PR head (or the queue's merge commit)"
assert 'git show "$BASE_SHA:scripts/release_class.sh" > "$RUNNER_TEMP/release_class.sh"' in rc_body, "release-class takes the script from the BASE commit, never from the PR head (P2 on #2422)"
assert 'bash "$RUNNER_TEMP/release_class.sh" "$BASE_SHA" "$HEAD_SHA" "$GITHUB_OUTPUT"' in rc_body, "release-class runs the base's script with base, head and the output file"
assert "bash scripts/release_class.sh" not in rc_body, "release-class must never run the head's copy of the script"
assert 'echo "docs_only=false" >> "$GITHUB_OUTPUT"' in rc_body and 'git cat-file -e "$BASE_SHA:scripts/release_class.sh"' in rc_body, "a base without the script classifies the PR as code"
assert "docs_only: ${{ steps.classify.outputs.docs_only }}" in rc_body, "release-class exposes docs_only as a job output"
assert "needs: [release-class]" in stage_b_if, "Stage-B must depend on release-class"
assert "needs.release-class.outputs.docs_only != 'true'" in stage_b_if, "Stage-B must be skipped on docs-only PRs"
assert "!cancelled() &&" in stage_b_if and "always()" not in stage_b_if, "Stage-B must use !cancelled(), never always()"
assert "(github.event_name != 'pull_request' && github.event_name != 'merge_group') ||" in stage_b_if.split("!cancelled()", 1)[1], "pushes to main and dispatch bypass the release class entirely"

# Merge queue (ADR-SYS-003 D3/D4, contract test 2): the workflow fires on
# merge_group; release-class classifies the queue's merge commit (github.sha)
# against merge_group.base_sha with the base's script; Stage-B runs in the
# queue unless docs-only; concurrency keys non-PR runs by run_id, so a queue
# run can never cancel a PR run on the same SHA or be cancelled by one.
on_block = WORKFLOW.split("jobs:", 1)[0]
assert re.search(r"(?m)^  merge_group:\n    types: \[checks_requested\]", on_block), "exact-head must trigger on merge_group checks_requested"
assert "github.event_name == 'merge_group'" in rc_body, "release-class must also run for merge groups"
assert "HEAD_SHA: ${{ github.event.pull_request.head.sha || github.sha }}" in rc_body, "release-class head in a merge group is github.sha (the queue's merge commit)"
assert "BASE_SHA: ${{ github.event.pull_request.base.sha || github.event.merge_group.base_sha }}" in rc_body, "release-class base in a merge group is merge_group.base_sha"
assert "ref: ${{ github.event.pull_request.head.sha || github.sha }}" in rc_body, "release-class checks out the same head it classifies"
assert "(github.event_name == 'merge_group' && needs.release-class.outputs.docs_only != 'true')" in stage_b_if, "Stage-B runs in the merge queue unless the entry is docs-only"
assert "github.event_name == 'pull_request' && github.event.pull_request.number || github.run_id" in WORKFLOW.split("jobs:", 1)[0], "non-PR runs (push, dispatch, merge_group) keep per-run concurrency groups"

core = re.search(r"(?ms)^  exact-head-core:\n(?P<body>.*?)(?=^    steps:)", WORKFLOW)
assert core is not None and "draft" not in core.group("body"), "exact-head-core must run on drafts too"
legacy = re.search(r"(?ms)^  legacy-merge-tree-equivalence:\n(?P<body>.*?)(?=^    steps:)", WORKFLOW)
assert legacy is not None and "draft" not in legacy.group("body"), "merge-tree equivalence must run on drafts too"
assert "legacy-merge-tree-equivalence:" in WORKFLOW
assert "test \"$merge_tree\" = \"$head_tree\"" in WORKFLOW
assert "exact-head-core:" in WORKFLOW

# Stage-B admission (shared by every caller): one lane per caller workflow and
# SHA. A lane shared across callers lets GitHub evict a pending gate when a
# second workflow starts Stage-B for the same SHA (workflow_dispatch of ci or
# agent3-full-diagnostics next to exact-head-qualification; tags:
# build-and-release). Since 06/11-2026 PRs and pushes to main run Stage-B once,
# in exact-head-qualification.
SLICES = code_of(ROOT / ".github" / "workflows" / "_stage_b_slices.yml")
admission = re.search(
    r"(?ms)^  stage-b-admission:\n(?P<body>.*?)(?=^    steps:)", SLICES
)
assert admission is not None, "stage-b-admission job must exist"
admission_body = admission.group("body")
assert (
    "group: modelrig-stage-b-admission-${{ inputs.head_sha }}-${{ github.workflow }}"
    in admission_body
), "admission lanes must be per caller workflow and SHA"
assert "cancel-in-progress: false" in admission_body, "an admission is never cancelled"
callers = sorted(
    p.name for p in (ROOT / ".github" / "workflows").glob("*.yml")
    if "uses: ./.github/workflows/_stage_b_slices.yml" in code_of(p)
)
assert callers == ["_tests.yml", "agent3-full-diagnostics.yml", "exact-head-qualification.yml"], (
    f"Stage-B callers changed ({callers}); re-check that no two callers share an admission lane"
)
print("exact-head concurrency contract: PASS")
