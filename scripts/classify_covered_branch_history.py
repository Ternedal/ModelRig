#!/usr/bin/env python3
import json, os, subprocess, time

BASE = os.environ.get("BASE_BRANCH", "main")
MIN_AGE_DAYS = int(os.environ.get("MIN_AGE_DAYS", "7"))
EXECUTE = os.environ.get("EXECUTE", "false").lower() == "true"
repo = os.environ["GITHUB_REPOSITORY"]

subprocess.run(
    ["git", "fetch", "origin", "--prune", "--no-tags", "+refs/heads/*:refs/remotes/origin/*"],
    check=True,
)

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
    ["git", "for-each-ref", "--format=%(objectname)\t%(committerdate:unix)\t%(refname:strip=3)", "refs/remotes/origin/"],
    text=True,
).splitlines()

branches = {}
for row in rows:
    if not row.strip():
        continue
    sha, ts, name = row.split("\t", 2)
    if name == "HEAD":
        continue
    branches[name] = {"sha": sha, "ts": int(ts)}

now = int(time.time())
covered = 0
deleted = 0
leaf = 0
protected_count = 0
too_new = 0

for name in sorted(branches):
    if name == BASE:
        continue

    if protected(name):
        print(f"PROTECTED\t{name}")
        protected_count += 1
        continue

    age_days = (now - branches[name]["ts"]) // 86400
    if age_days < MIN_AGE_DAYS:
        print(f"TOO_NEW\t{name}\t{age_days}d")
        too_new += 1
        continue

    sha = branches[name]["sha"]
    out = subprocess.check_output(
        ["git", "branch", "-r", "--contains", sha, "--format=%(refname:strip=3)"],
        text=True,
    ).splitlines()

    covering = [
        b.strip() for b in out
        if b.strip() and b.strip() != name and b.strip() != "HEAD"
    ]

    if not covering:
        print(f"LEAF\t{name}\t{age_days}d")
        leaf += 1
        continue

    def keeper_score(b: str):
        # Prefer protected/open-PR descendants, then the newest tip, then stable short names.
        p = 0 if protected(b) else 1
        ts = branches.get(b, {}).get("ts", 0)
        noisy = 1 if any(tok in b for tok in ("tmp", "temp", "scratch", "shadow", "rebase", "work")) else 0
        return (p, -ts, noisy, len(b), b)

    keeper = sorted(covering, key=keeper_score)[0]
    print(f"COVERED_BY_BRANCH\t{name}\tKEEP={keeper}\t{age_days}d\tcovering={len(covering)}")
    covered += 1
    if EXECUTE:
        subprocess.run(["git", "push", "origin", "--delete", name], check=True)
        print(f"DELETED\t{name}\tKEEP={keeper}")
        deleted += 1

print(
    f"SUMMARY covered={covered} leaf={leaf} protected={protected_count} "
    f"too_new={too_new} deleted={deleted} execute={str(EXECUTE).lower()} min_age_days={MIN_AGE_DAYS}"
)
