#!/usr/bin/env bash
# Verdict for the required queue check `stage-b-verdict` (ADR-SYS-003 D3) and
# the freeze guard (ADR-SYS-003 D7). Pure function of its environment so the
# gate can test every branch without GitHub:
#
#   RESULT     needs.stage-b-slices.result      success | skipped | failure | cancelled
#   DOCS_ONLY  needs.release-class.outputs.docs_only   true | false | ''
#   EVENT      github.event_name                 pull_request | merge_group | push | workflow_dispatch
#   DRAFT      github.event.pull_request.draft   true | false | ''
#   FREEZE     vars.KALIV_FREEZE                 '1' = campaign freeze on (set by Anders), anything else = off
#
# Exit 0 = the candidate may land as far as Stage B and the freeze are concerned.
# Exit 1 = it may not. Every message says why.
set -euo pipefail
RESULT="${RESULT:-}"; DOCS_ONLY="${DOCS_ONLY:-}"; EVENT="${EVENT:-}"; DRAFT="${DRAFT:-}"; FREEZE="${FREEZE:-}"
echo "stage-b-slices result: '${RESULT}'; docs_only: '${DOCS_ONLY}'; event: '${EVENT}'; draft: '${DRAFT}'; freeze: '${FREEZE}'"

# D7: during a campaign freeze nothing outside the documentation class enters
# the queue. Judged first, so a frozen code candidate is refused even when its
# Stage B passed. Only merge groups are refused; on pull requests the same
# condition is reported as a failure of this (non-required, in classic mode)
# check so the author sees it before enqueueing.
if [ "$FREEZE" = "1" ] && [ "$DOCS_ONLY" != "true" ]; then
  case "$EVENT" in
    merge_group|pull_request)
      echo "KALIV_FREEZE=1: a campaign freeze is on and this candidate is not documentation-only (docs_only='${DOCS_ONLY}'); it may not land (ADR-SYS-003 D7)" >&2
      exit 1 ;;
    *) echo "freeze is on, but this is a ${EVENT} run, not a candidate" ;;
  esac
fi

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
