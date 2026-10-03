#!/usr/bin/env bash
set -euo pipefail

BASE_BRANCH="${BASE_BRANCH:-main}"
MIN_AGE_DAYS="${MIN_AGE_DAYS:-7}"
EXECUTE="${EXECUTE:-false}"

git fetch origin --prune --no-tags '+refs/heads/*:refs/remotes/origin/*'

mapfile -t OPEN_PR_HEADS < <(
  gh api --paginate "repos/${GITHUB_REPOSITORY}/pulls?state=open&per_page=100" --jq '.[].head.ref'
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
main_tree="$(git rev-parse "origin/${BASE_BRANCH}^{tree}")"

ancestor_merged=0
superseded=0
contributes=0
conflicts=0
protected=0
too_new=0
deleted=0

delete_branch() {
  local branch="$1"
  if [[ "$EXECUTE" == "true" ]]; then
    git push origin --delete "$branch"
    printf 'DELETED\t%s\n' "$branch"
    ((deleted+=1))
  fi
}

while IFS= read -r ref; do
  branch="${ref#refs/remotes/origin/}"
  [[ "$branch" == "HEAD" || "$branch" == "$BASE_BRANCH" ]] && continue

  if [[ -n "${PROTECTED[$branch]:-}" ]] || is_protected_pattern "$branch"; then
    printf 'PROTECTED\t%s\n' "$branch"
    ((protected+=1))
    continue
  fi

  tip_epoch="$(git show -s --format=%ct "origin/$branch")"
  age_days="$(( (now_epoch - tip_epoch) / 86400 ))"
  if (( age_days < MIN_AGE_DAYS )); then
    printf 'TOO_NEW\t%s\t%sd\n' "$branch" "$age_days"
    ((too_new+=1))
    continue
  fi

  if git merge-base --is-ancestor "origin/$branch" "origin/$BASE_BRANCH"; then
    printf 'ANCESTOR_MERGED\t%s\t%sd\n' "$branch" "$age_days"
    ((ancestor_merged+=1))
    delete_branch "$branch"
    continue
  fi

  if merge_output="$(git merge-tree --write-tree "origin/$BASE_BRANCH" "origin/$branch" 2>/dev/null)"; then
    merged_tree="$(printf '%s\n' "$merge_output" | head -n1)"
    if [[ "$merged_tree" == "$main_tree" ]]; then
      printf 'SUPERSEDED\t%s\t%sd\n' "$branch" "$age_days"
      ((superseded+=1))
      delete_branch "$branch"
    else
      printf 'CONTRIBUTES\t%s\t%sd\t%s\n' "$branch" "$age_days" "$merged_tree"
      ((contributes+=1))
    fi
  else
    printf 'CONFLICT\t%s\t%sd\n' "$branch" "$age_days"
    ((conflicts+=1))
  fi
done < <(git for-each-ref --format='%(refname)' refs/remotes/origin/)

printf '\nSUMMARY ancestor_merged=%s superseded=%s contributes=%s conflicts=%s protected=%s too_new=%s deleted=%s execute=%s min_age_days=%s\n'   "$ancestor_merged" "$superseded" "$contributes" "$conflicts" "$protected" "$too_new" "$deleted" "$EXECUTE" "$MIN_AGE_DAYS"
