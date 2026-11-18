#!/usr/bin/env bash
# Release class of a pull request for CI tiering (ADR-SYS-002 D1 applied to CI).
#
# Usage: release_class.sh <base-sha> <head-sha> [<github-output-file>]
#
# Classifies merge-base(base, head)..head with scripts/release_fingerprint.py
# and writes `docs_only=true|false` to the output file (default: stdout).
# Exit 0 for either classification. Exit 1 only when the classification itself
# could not be made (bad SHAs, classifier error); the caller must then treat
# docs_only as unknown and run the full chain. HEAD of the checkout must be the
# head SHA: the classifier reads the exclusion list from the tree it classifies.
set -euo pipefail
base_sha="${1:?base sha}"
head_sha="${2:?head sha}"
out="${3:-/dev/stdout}"
root="$(cd "$(dirname "$0")/.." && pwd)"
cd "$root"
test "$(git rev-parse HEAD)" = "$head_sha" || { echo "release_class: HEAD is not $head_sha" >&2; exit 1; }
merge_base="$(git merge-base "$base_sha" "$head_sha")" || { echo "release_class: no merge-base for $base_sha and $head_sha" >&2; exit 1; }
rc=0
result="$(python3 -B scripts/release_fingerprint.py changed "$merge_base" "$head_sha")" || rc=$?
echo "$result" >&2
case "$rc" in
  0) docs_only=true ;;
  1) docs_only=false ;;
  *) echo "release_class: classifier exit $rc" >&2; exit 1 ;;
esac
printf 'docs_only=%s\n' "$docs_only" >> "$out"
