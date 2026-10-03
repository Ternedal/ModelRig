#!/usr/bin/env python3
import json, os, subprocess, time
from collections import defaultdict

BASE = os.environ.get("BASE_BRANCH", "main")
MIN_AGE_DAYS = int(os.environ.get("MIN_AGE_DAYS", "7"))

subprocess.run(
    ["git", "fetch", "origin", "--prune", "--no-tags", "+refs/heads/*:refs/remotes/origin/*"],
    check=True,
)

repo = os.environ["GITHUB_REPOSITORY"]
prs = subprocess.check_output(
    ["gh", "api", "--paginate", f"repos/{repo}/pulls?state=open&per_page=100"],
    text=True,
)
open_heads = {pr["head"]["ref"] for pr in json.loads(prs)}

def protected(name: str) -> bool:
    return (
        name == BASE
        or name in open_heads
        or name.startswith(("release/", "physical-proof/", "archive/", "brand/"))
    )

rows = subprocess.check_output(
    ["git", "for-each-ref", "--format=%(objectname)\t%(refname:strip=3)", "refs/remotes/origin/"],
    text=True,
).splitlines()

groups = defaultdict(list)
for row in rows:
    if not row.strip():
        continue
    sha, name = row.split("\t", 1)
    if name == "HEAD":
        continue
    groups[sha].append(name)

now = int(time.time())
candidate_count = 0
group_count = 0
protected_count = 0
too_new_count = 0

for sha, names in sorted(groups.items()):
    if len(names) < 2:
        continue

    group_count += 1
    protected_names = [n for n in names if protected(n)]

    def score(n: str):
        noisy = (
            n.startswith(("tmp/", "scratch/", "ignore/", "__delete_me__"))
            or "temp" in n
            or "shadow" in n
            or "work" in n
            or "rebase" in n
        )
        return (1 if noisy else 0, len(n), n)

    keeper = protected_names[0] if protected_names else sorted(names, key=score)[0]
    print(f"GROUP\t{sha}\tKEEP\t{keeper}\tALIASES\t{len(names)}")

    for name in sorted(names):
        if name == keeper:
            continue
        if protected(name):
            print(f"PROTECTED_ALIAS\t{name}\t{sha}")
            protected_count += 1
            continue

        tip_epoch = int(subprocess.check_output(
            ["git", "show", "-s", "--format=%ct", f"origin/{name}"], text=True
        ).strip())
        age_days = (now - tip_epoch) // 86400

        if age_days < MIN_AGE_DAYS:
            print(f"TOO_NEW_ALIAS\t{name}\t{sha}\t{age_days}d")
            too_new_count += 1
            continue

        print(f"DUPLICATE_ALIAS\t{name}\t{sha}\tKEEP={keeper}\t{age_days}d")
        candidate_count += 1

print(
    f"SUMMARY duplicate_groups={group_count} duplicate_alias_candidates={candidate_count} "
    f"protected_aliases={protected_count} too_new_aliases={too_new_count} "
    f"min_age_days={MIN_AGE_DAYS}"
)
