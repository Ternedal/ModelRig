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
patch_equivalent=0
deleted=0
has_unique_patch=0
unique_merges=0
protected=0
too_new=0
ancestor_merged=0

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
    continue
  fi

  merge_count="$(git rev-list --count --merges "origin/$BASE_BRANCH..origin/$branch")"
  if (( merge_count > 0 )); then
    printf 'UNIQUE_MERGES\t%s\t%sd\t%s\n' "$branch" "$age_days" "$merge_count"
    ((unique_merges+=1))
    continue
  fi

  mapfile -t cherry_lines < <(git cherry "origin/$BASE_BRANCH" "origin/$branch")
  if (( ${#cherry_lines[@]} == 0 )); then
    printf 'NO_CHERRY_SIGNAL\t%s\t%sd\n' "$branch" "$age_days"
    ((has_unique_patch+=1))
    continue
  fi

  plus=0
  minus=0
  for line in "${cherry_lines[@]}"; do
    case "$line" in
      +*) ((plus+=1)) ;;
      -*) ((minus+=1)) ;;
    esac
  done

  if (( plus == 0 && minus > 0 )); then
    printf 'PATCH_EQUIVALENT\t%s\t%sd\t%s\n' "$branch" "$age_days" "$minus"
    ((patch_equivalent+=1))
    if [[ "$EXECUTE" == "true" ]]; then
      git push origin --delete "$branch"
      printf 'DELETED\t%s\n' "$branch"
      ((deleted+=1))
    fi
  else
    printf 'UNIQUE_PATCH\t%s\t%sd\tplus=%s\tminus=%s\n' "$branch" "$age_days" "$plus" "$minus"
    ((has_unique_patch+=1))
  fi
done < <(git for-each-ref --format='%(refname)' refs/remotes/origin/)

printf '\nSUMMARY patch_equivalent=%s unique_patch=%s unique_merges=%s ancestor_merged=%s protected=%s too_new=%s min_age_days=%s\n'   "$patch_equivalent" "$has_unique_patch" "$unique_merges" "$ancestor_merged" "$protected" "$too_new" "$MIN_AGE_DAYS"
