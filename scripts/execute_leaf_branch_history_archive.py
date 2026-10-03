#!/usr/bin/env python3
import json, os, subprocess, time

BASE = os.environ.get("BASE_BRANCH", "main")
MIN_AGE_DAYS = int(os.environ.get("MIN_AGE_DAYS", "7"))
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
leafs = []
protected_count = 0
too_new = 0
covered = 0

for name in sorted(branches):
    if name == BASE:
        continue
    if protected(name):
        protected_count += 1
        continue

    age_days = (now - branches[name]["ts"]) // 86400
    if age_days < MIN_AGE_DAYS:
        too_new += 1
        continue

    sha = branches[name]["sha"]
    out = subprocess.check_output(
        ["git", "branch", "-r", "--contains", sha, "--format=%(refname:strip=3)"],
        text=True,
    ).splitlines()
    covering = [b.strip() for b in out if b.strip() and b.strip() not in (name, "HEAD")]

    if covering:
        covered += 1
        continue

    leafs.append((name, sha, age_days))

print(f"LEAF_COUNT\t{len(leafs)}")
for name, sha, age in leafs:
    print(f"ARCHIVE_CANDIDATE\t{name}\t{sha}\t{age}d")

# Build a synthetic local archive commit only; do not push it.
tree = subprocess.check_output(["git", "rev-parse", f"origin/{BASE}^{{tree}}"], text=True).strip()
parents = [subprocess.check_output(["git", "rev-parse", f"origin/{BASE}"], text=True).strip()]
seen = set(parents)
for _, sha, _ in leafs:
    if sha not in seen:
        parents.append(sha)
        seen.add(sha)

cmd = ["git", "commit-tree", tree]
for p in parents:
    cmd += ["-p", p]
env = os.environ.copy()
env.update({
    "GIT_AUTHOR_NAME":"ModelRig Branch Archive",
    "GIT_AUTHOR_EMAIL":"noreply@localhost",
    "GIT_COMMITTER_NAME":"ModelRig Branch Archive",
    "GIT_COMMITTER_EMAIL":"noreply@localhost",
})
proc = subprocess.run(
    cmd,
    input=f"Archive stale leaf branch history ({len(leafs)} refs)\n",
    text=True,
    capture_output=True,
    check=True,
    env=env,
)
archive_commit = proc.stdout.strip()

# Verify every candidate is reachable from the synthetic archive commit.
failed = []
for name, sha, _ in leafs:
    rc = subprocess.run(["git", "merge-base", "--is-ancestor", sha, archive_commit]).returncode
    if rc != 0:
        failed.append(name)

print(f"ARCHIVE_COMMIT_LOCAL\t{archive_commit}")
print(f"ARCHIVE_PARENT_COUNT\t{len(parents)}")
print(f"VERIFY_FAILED\t{len(failed)}")
for name in failed:
    print(f"VERIFY_FAIL_BRANCH\t{name}")

print(
    f"SUMMARY leaf_candidates={len(leafs)} unique_archive_parents={len(parents)} "
    f"verify_failed={len(failed)} protected={protected_count} too_new={too_new} "
    f"covered={covered} min_age_days={MIN_AGE_DAYS}"
)


# Execution section: push one archive ref, re-fetch it, verify all candidates,
# then delete only the candidate refs whose tips are reachable from the archive.
if os.environ.get("EXECUTE", "false").lower() == "true":
    archive_branch = os.environ.get("ARCHIVE_BRANCH", "archive/leaf-history-20261003")

    # Push the already-verified synthetic commit under one protected archive ref.
    subprocess.run(
        ["git", "push", "origin", f"{archive_commit}:refs/heads/{archive_branch}"],
        check=True,
    )
    subprocess.run(
        ["git", "fetch", "origin", f"refs/heads/{archive_branch}:refs/remotes/origin/{archive_branch}"],
        check=True,
    )
    remote_archive = subprocess.check_output(
        ["git", "rev-parse", f"origin/{archive_branch}"], text=True
    ).strip()
    print(f"REMOTE_ARCHIVE_COMMIT\t{remote_archive}")

    remote_failed = []
    for name, sha, _ in leafs:
        rc = subprocess.run(
            ["git", "merge-base", "--is-ancestor", sha, remote_archive]
        ).returncode
        if rc != 0:
            remote_failed.append(name)

    print(f"REMOTE_VERIFY_FAILED\t{len(remote_failed)}")
    for name in remote_failed:
        print(f"REMOTE_VERIFY_FAIL_BRANCH\t{name}")

    if remote_failed:
        raise SystemExit("remote archive verification failed; refusing deletion")

    deleted = 0
    for name, sha, age in leafs:
        # Re-check that this exact tip is still the branch tip before deletion.
        current = subprocess.check_output(
            ["git", "rev-parse", f"origin/{name}"], text=True
        ).strip()
        if current != sha:
            print(f"TIP_MOVED_SKIP\t{name}\tplanned={sha}\tcurrent={current}")
            continue
        subprocess.run(["git", "push", "origin", "--delete", name], check=True)
        print(f"DELETED\t{name}\t{sha}\t{age}d")
        deleted += 1

    print(
        f"EXECUTION_SUMMARY archive_branch={archive_branch} "
        f"archive_commit={remote_archive} deleted={deleted} "
        f"candidate_count={len(leafs)} remote_verify_failed={len(remote_failed)}"
    )
