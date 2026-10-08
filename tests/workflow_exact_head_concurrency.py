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
assert "pull_request:\n    types: [opened, synchronize, reopened, closed]" in WORKFLOW
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
assert "legacy-merge-tree-equivalence:" in WORKFLOW
assert "test \"$merge_tree\" = \"$head_tree\"" in WORKFLOW
assert "exact-head-core:" in WORKFLOW
print("exact-head concurrency contract: PASS")
