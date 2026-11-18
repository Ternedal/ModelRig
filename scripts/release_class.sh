#!/usr/bin/env bash
# Release class of a pull request for CI tiering (ADR-SYS-002 D1 applied to CI).
#
# Usage: release_class.sh <base-sha> <head-sha> [<github-output-file>]
#
# Classifies merge-base(base, head)..head and writes `docs_only=true|false` to
# the output file (default: stdout). Exit 0 for either classification. Exit 1
# only when no classification could be made (bad SHAs, base without the
# classifier, classifier error); the caller must then treat docs_only as
# unknown and run the full chain.
#
# The classifier is taken FROM THE BASE COMMIT (`git show <base>:scripts/
# release_fingerprint.py`), never from the head: a PR must not decide with its
# own classifier whether its own Stage B runs (review P2 on #2422). The
# exclusion list is read from the head's working tree as before; a change to
# that list is itself code under the base classifier, so it cannot exempt
# itself either. The workflow extracts this script from the base the same way.
#
# HEAD of the checkout must be the head SHA, and the current directory must be
# inside the checkout.
set -euo pipefail
base_sha="${1:?base sha}"
head_sha="${2:?head sha}"
out="${3:-/dev/stdout}"
root="$(git rev-parse --show-toplevel)"
cd "$root"
test "$(git rev-parse HEAD)" = "$head_sha" || { echo "release_class: HEAD is not $head_sha" >&2; exit 1; }
merge_base="$(git merge-base "$base_sha" "$head_sha")" || { echo "release_class: no merge-base for $base_sha and $head_sha" >&2; exit 1; }
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
git show "$base_sha:scripts/release_fingerprint.py" > "$tmp/release_fingerprint.py" 2>/dev/null \
  || { echo "release_class: base $base_sha has no scripts/release_fingerprint.py" >&2; exit 1; }
rc=0
result="$(python3 -B "$tmp/release_fingerprint.py" --repository-root "$root" changed "$merge_base" "$head_sha")" || rc=$?
echo "$result" >&2
case "$rc" in
  0) docs_only=true ;;
  1) docs_only=false ;;
  *) echo "release_class: classifier exit $rc" >&2; exit 1 ;;
esac
printf 'docs_only=%s\n' "$docs_only" >> "$out"
