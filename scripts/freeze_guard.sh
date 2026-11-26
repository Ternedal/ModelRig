#!/usr/bin/env bash
# Campaign freeze guard (ADR-SYS-003 D7), run by .github/workflows/freeze-guard.yml
# FROM THE BASE CHECKOUT. Usage: freeze_guard.sh <base-sha> <head-sha>
#
#   FREEZE   repository variable KALIV_FREEZE ('1' = on; anything else = off)
#
# The working tree must be the base (HEAD == base-sha); the candidate head is
# only an object in the repository. The classification runs the BASE's
# release_fingerprint.py over merge-base(base, head)..head, so neither the
# classifier nor this script can be altered by the candidate being judged.
#
# Exit 0: no freeze, or a documentation-only candidate during a freeze.
# Exit 1: freeze on and the candidate is not documentation-only, or the class
#         could not be determined (unknown is refused while frozen), or the
#         preconditions above do not hold.
set -euo pipefail
base_sha="${1:?base sha}"
head_sha="${2:?head sha}"
FREEZE="${FREEZE:-}"
root="$(git rev-parse --show-toplevel)"
cd "$root"
test "$(git rev-parse HEAD)" = "$base_sha" || { echo "freeze_guard: the checkout must be the base $base_sha (it is $(git rev-parse HEAD))" >&2; exit 1; }
git cat-file -e "$head_sha^{commit}" 2>/dev/null || { echo "freeze_guard: candidate head $head_sha is not available" >&2; exit 1; }
test -f scripts/release_fingerprint.py || { echo "freeze_guard: the base has no scripts/release_fingerprint.py" >&2; exit 1; }

echo "freeze: '${FREEZE}'; base: ${base_sha}; head: ${head_sha}"
if [ "$FREEZE" != "1" ]; then
  echo "no campaign freeze (KALIV_FREEZE != '1'); nothing to enforce"
  exit 0
fi

merge_base="$(git merge-base "$base_sha" "$head_sha")" || { echo "freeze_guard: no merge-base; refusing while frozen" >&2; exit 1; }
rc=0
result="$(python3 -B scripts/release_fingerprint.py --repository-root "$root" changed "$merge_base" "$head_sha")" || rc=$?
echo "$result"
case "$rc" in
  0) echo "KALIV_FREEZE=1: documentation-only candidate; allowed (ADR-SYS-003 D7)" ; exit 0 ;;
  1) echo "KALIV_FREEZE=1: a campaign freeze is on and this candidate is not documentation-only; it may not land (ADR-SYS-003 D7)" >&2; exit 1 ;;
  *) echo "KALIV_FREEZE=1: the candidate could not be classified (classifier exit $rc); refusing while frozen" >&2; exit 1 ;;
esac
