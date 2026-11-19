#!/usr/bin/env bash
# Verdict for the required queue check `stage-b-verdict` (ADR-SYS-003 D3).
# Pure function of its environment so the gate can test every branch without
# GitHub. (The campaign freeze, D7, is NOT judged here: this script runs from
# the candidate's checkout and could be edited by it; the freeze is enforced
# by .github/workflows/freeze-guard.yml, required via the ruleset and run from
# main, with scripts/freeze_guard.sh from the base.)
#
#   RESULT     needs.stage-b-slices.result      success | skipped | failure | cancelled
#   DOCS_ONLY  needs.release-class.outputs.docs_only   true | false | ''
#   EVENT      github.event_name                 pull_request | merge_group | push | workflow_dispatch
#   DRAFT      github.event.pull_request.draft   true | false | ''
#
# Exit 0 = the candidate may land as far as Stage B is concerned.
# Exit 1 = it may not. Every message says why.
set -euo pipefail
RESULT="${RESULT:-}"; DOCS_ONLY="${DOCS_ONLY:-}"; EVENT="${EVENT:-}"; DRAFT="${DRAFT:-}"
echo "stage-b-slices result: '${RESULT}'; docs_only: '${DOCS_ONLY}'; event: '${EVENT}'; draft: '${DRAFT}'"

case "$RESULT" in
  success) echo "Stage B passed on this exact head" ;;
  skipped)
    if [ "$DOCS_ONLY" = "true" ]; then
      echo "documentation-only candidate: Stage B is not required (ADR-SYS-002 D1)"
    elif [ "$EVENT" = "pull_request" ] && [ "$DRAFT" = "true" ]; then
      echo "draft pull request: Stage B is deferred to ready_for_review (#2413)"
    else
      echo "Stage B was skipped without an allowed reason" >&2; exit 1
    fi ;;
  *) echo "Stage B did not pass (result: '${RESULT}')" >&2; exit 1 ;;
esac
