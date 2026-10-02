#!/usr/bin/env bash
set -euo pipefail

BASE_BRANCH="${BASE_BRANCH:-main}"
EXECUTE="${EXECUTE:-false}"
MIN_AGE_DAYS="${MIN_AGE_DAYS:-7}"

git fetch origin --prune --no-tags '+refs/heads/*:refs/remotes/origin/*'

mapfile -t OPEN_PR_HEADS < <(
  gh api --paginate "repos/${GITHUB_REPOSITORY}/pulls?state=open&per_page=100"     --jq '.[].head.ref'
)

declare -A PROTECTED=()
PROTECTED["${BASE_BRANCH}"]=1
for h in "${OPEN_PR_HEADS[@]}"; do PROTECTED["$h"]=1; done

is_protected_pattern() {
  case "$1" in
    release/*|physical-proof/*|archive/*|brand/*) return 0 ;;
    *) return 1 ;;
  esac
}

now_epoch="$(date +%s)"
deleted=0
eligible=0
skipped=0

while IFS= read -r ref; do
  branch="${ref#refs/remotes/origin/}"
  [[ "$branch" == "HEAD" ]] && continue
  [[ "$branch" == "$BASE_BRANCH" ]] && continue

  if [[ -n "${PROTECTED[$branch]:-}" ]] || is_protected_pattern "$branch"; then
    printf 'PROTECTED\t%s\n' "$branch"
    ((skipped+=1))
    continue
  fi

  if ! git merge-base --is-ancestor "origin/$branch" "origin/$BASE_BRANCH"; then
    printf 'UNMERGED\t%s\n' "$branch"
    ((skipped+=1))
    continue
  fi

  tip_epoch="$(git show -s --format=%ct "origin/$branch")"
  age_days="$(( (now_epoch - tip_epoch) / 86400 ))"
  if (( age_days < MIN_AGE_DAYS )); then
    printf 'TOO_NEW\t%s\t%sd\n' "$branch" "$age_days"
    ((skipped+=1))
    continue
  fi

  ((eligible+=1))
  if [[ "$EXECUTE" == "true" ]]; then
    git push origin --delete "$branch"
    printf 'DELETED\t%s\t%sd\n' "$branch" "$age_days"
    ((deleted+=1))
  else
    printf 'DRY_RUN_DELETE\t%s\t%sd\n' "$branch" "$age_days"
  fi
done < <(git for-each-ref --format='%(refname)' refs/remotes/origin/)

printf '\nSUMMARY eligible=%s deleted=%s skipped=%s execute=%s min_age_days=%s\n'   "$eligible" "$deleted" "$skipped" "$EXECUTE" "$MIN_AGE_DAYS"
