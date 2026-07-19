#!/usr/bin/env python3
"""Confirm the validation candidate is frozen, coherent, and CI-green (F-919, F-922).

Physical evidence is code-bound: the validation report is bound to the running
worker's code_sha256, so validating version X and then shipping version X+1
silently invalidates the evidence you have not run yet. That is the hardening
treadmill the strategic analysis names. Before spending a rig session, this
answers three questions the run itself cannot:

  1. Is the working tree clean and are all version stamps consistent, so the
     candidate is a single coherent thing and not a half-applied state?
  2. Was CI actually GREEN on this exact commit -- not a previous one, not a
     "should be fine"? (F-922: an exact-head receipt, read live from the API.)
  3. What is the candidate's identity (version + SHA), recorded so the report
     can be tied back to it and drift past it is visible?

It changes nothing. It reads git, the version tool, and -- if a token is
available -- the GitHub Actions status for this exact SHA.

Usage (from the repo root):

    python scripts/freeze_check.py
    # CI check needs a GitHub token in the environment (not on the command line):
    #   $env:GITHUB_TOKEN = "<token>"    (PowerShell)

Exit 0 -- FROZEN -- only when the candidate is coherent AND ci+codeql are
verified green on this exact head (F-1005). No token, an unreadable API, a
missing or still-running workflow: all of it blocks. A freeze without the
exact-head evidence is the hollow FROZEN this gate exists to prevent
rather than failing, so the coherence checks still run offline.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
import urllib.error
import urllib.request

REPO = "Ternedal/ModelRig"


def _run(*args: str) -> tuple[int, str]:
    p = subprocess.run(args, capture_output=True, text=True)
    return p.returncode, (p.stdout or p.stderr).strip()


def _api(url: str, token: str):
    req = urllib.request.Request(url)
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Accept", "application/vnd.github+json")
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode("utf-8"))


def main() -> int:
    print()
    print("  Freeze check -- is the validation candidate coherent and CI-green?")
    print("  " + "-" * 62)

    blockers = 0
    warns = 0

    token = (os.environ.get("GITHUB_TOKEN")
             or os.environ.get("GH_TOKEN") or "").strip()
    version = ""
    try:
        version = open(os.path.join(os.path.dirname(__file__), "..", "VERSION")).read().strip()
    except OSError:
        pass

    # --- identity -----------------------------------------------------------
    # The rig is gitless (sources arrive as a ZIP), so identity has two
    # honest modes: git when available, otherwise the GitHub API resolves the
    # published tag v{VERSION} to its exact sha. Found by rehearsing the rig
    # flow: every step of the campaign toolchain assumed a clone and died on
    # "not a git repo" as the operator's very first command.
    gitless = False
    rc, sha = _run("git", "rev-parse", "HEAD")
    if rc != 0:
        gitless = True
        if not version:
            print("  FAIL  gitless tree and VERSION is unreadable -- identity")
            print("         cannot be established at all")
            return 1
        if not token:
            print("  FAIL  gitless identity needs the GitHub API -- no")
            print("         GITHUB_TOKEN/GH_TOKEN in the environment")
            print('         -> $env:GITHUB_TOKEN = "<token>"   (PowerShell)')
            return 1
        try:
            rel = _api(f"https://api.github.com/repos/{REPO}"
                       f"/releases/tags/v{version}", token)
        except urllib.error.HTTPError as exc:
            print(f"  FAIL  no published release found for tag v{version} "
                  f"(HTTP {exc.code})")
            print("         -> The candidate must BE a published release; this")
            print("            tree's VERSION does not match one.")
            return 1
        except urllib.error.URLError as exc:
            print(f"  FAIL  could not reach the GitHub API ({exc.reason})")
            return 1
        if rel.get("draft"):
            print(f"  FAIL  release v{version} is still a draft -- not a")
            print("         published candidate")
            return 1
        try:
            ref = _api(f"https://api.github.com/repos/{REPO}"
                       f"/git/ref/tags/v{version}", token)
            obj = ref.get("object") or {}
            sha = obj.get("sha") or ""
            if obj.get("type") == "tag" and sha:
                sha = (_api(f"https://api.github.com/repos/{REPO}"
                            f"/git/tags/{sha}", token)
                       .get("object", {}).get("sha") or "")
        except (urllib.error.URLError, urllib.error.HTTPError) as exc:
            reason = getattr(exc, "reason", None) or getattr(exc, "code", "?")
            print(f"  FAIL  could not resolve tag v{version} to a commit "
                  f"({reason})")
            return 1
        if not sha:
            print(f"  FAIL  tag v{version} did not resolve to a commit sha")
            return 1
        short = sha[:7]
        print(f"  candidate: {version}  @  {short}  (gitless -- identity via "
              f"published release v{version})")
    else:
        _, short = _run("git", "rev-parse", "--short", "HEAD")
        print(f"  candidate: {version or '?'}  @  {short}")
    print()

    # --- 1. clean working tree ----------------------------------------------
    if gitless:
        print("  NOTE  working-tree cleanliness cannot be verified without git")
        print("        -> gitless trust anchor: this tree is the officially")
        print("           downloaded ZIP for the tag, unmodified. Named and")
        print("           accepted, not silently greened.")
        warns += 1
    else:
        _, dirty = _run("git", "status", "--porcelain")
        if dirty:
            n = len(dirty.splitlines())
            print(f"  FAIL  working tree not clean ({n} uncommitted change(s))")
            print("         -> Commit or discard changes so the candidate is exactly")
            print("            what is on this commit, then re-run.")
            blockers += 1
        else:
            print("  OK    working tree clean")

    # --- 2. version stamps consistent ---------------------------------------
    vt = os.path.join(os.path.dirname(__file__), "version_tool.py")
    rc, out = _run(sys.executable, vt, "check")
    if rc == 0:
        print(f"  OK    version stamps consistent ({version})")
    else:
        print("  FAIL  version stamps disagree across the tree")
        for line in out.splitlines()[-4:]:
            print(f"         -> {line}")
        blockers += 1

    # --- 3. this exact commit is on origin/main -----------------------------
    if gitless:
        try:
            cmp_ = _api(f"https://api.github.com/repos/{REPO}"
                        f"/compare/main...{sha}", token)
            status = cmp_.get("status")
            if status in ("identical", "behind"):
                print("  OK    candidate is on main (verified via the API)")
            else:
                print(f"  FAIL  candidate commit is not on main "
                      f"(compare status: {status})")
                blockers += 1
        except (urllib.error.URLError, urllib.error.HTTPError) as exc:
            reason = getattr(exc, "reason", None) or getattr(exc, "code", "?")
            print(f"  FAIL  could not compare candidate against main ({reason})")
            blockers += 1
    else:
        _run("git", "fetch", "-q", "origin", "main")
        rc, _ = _run("git", "merge-base", "--is-ancestor", sha, "origin/main")
        if rc == 0:
            print("  OK    candidate is on origin/main (pushed, not a local-only state)")
        else:
            print("  FAIL  candidate commit is not on origin/main")
            print("         -> Push it first; validating a local-only commit means the")
            print("            evidence points at code nobody else can see.")
            blockers += 1

    # --- 4. CI was GREEN on this exact head (F-922) -------------------------
    if not token:
        print("  FAIL  CI status cannot be verified -- no GITHUB_TOKEN/GH_TOKEN")
        print("         -> FROZEN requires exact-head CI evidence (F-1005).")
        print("            Set a token in the env and re-run:")
        print('              $env:GITHUB_TOKEN = "<token>"   (PowerShell)')
        blockers += 1
    else:
        try:
            runs = _api(
                f"https://api.github.com/repos/{REPO}/actions/runs"
                f"?head_sha={sha}&per_page=20", token).get("workflow_runs", [])
            for wf in ("ci", "codeql"):
                mine = [r for r in runs if r.get("name") == wf]
                if not mine:
                    print(f"  FAIL  no {wf} run found for this exact commit yet")
                    print("         -> It may still be starting. Wait for it to")
                    print("            finish green, then re-run the freeze check.")
                    blockers += 1
                    continue
                latest = mine[0]
                status = latest.get("status")
                concl = latest.get("conclusion")
                if status == "completed" and concl == "success":
                    print(f"  OK    {wf} was GREEN on this exact commit")
                elif status != "completed":
                    print(f"  FAIL  {wf} is still running on this commit ({status})")
                    print("         -> Wait for it to finish green, then re-run.")
                    blockers += 1
                else:
                    print(f"  FAIL  {wf} on this commit did not pass "
                          f"(conclusion: {concl})")
                    print("         -> Do not validate a candidate whose checks are")
                    print("            not green; fix them first.")
                    blockers += 1
        except (urllib.error.URLError, urllib.error.HTTPError) as exc:
            reason = getattr(exc, "reason", None) or getattr(exc, "code", "?")
            print(f"  FAIL  could not read CI status ({reason})")
            print("         -> FROZEN requires exact-head CI evidence; fix the")
            print("            connection or token, then re-run.")
            blockers += 1

    print("  " + "-" * 62)
    if blockers:
        print(f"  NOT FROZEN -- {blockers} blocker(s) above. Fix them, then re-run.")
        print("  Nothing was changed.")
        return 1
    # FROZEN: write the attestation the gitless campaign toolchain consumes.
    # candidate_identity and rig_preflight read this file when git is absent,
    # so the chain of custody is explicit: this gate verified the identity
    # against the API; they inherit exactly that verdict, nothing looser.
    att_dir = os.path.join(os.path.dirname(__file__), "..", "validation")
    os.makedirs(att_dir, exist_ok=True)
    att_path = os.path.join(att_dir, "frozen-candidate.json")
    with open(att_path, "w", encoding="utf-8") as fh:
        json.dump({
            "schema": "kaliv-frozen-candidate/v1",
            "version": version,
            "git_sha": sha,
            "mode": "gitless-api" if gitless else "git",
            "checked_at": datetime.now(timezone.utc).isoformat(),
            "ci": "success",
            "codeql": "success",
        }, fh, indent=2)
    print(f"  attestation written: validation{os.sep}frozen-candidate.json")
    if warns:
        print(f"  FROZEN (with {warns} note(s) above) -- candidate {version} @ {short}")
        print("  The coherence checks passed. Resolve the notes if you can, then:")
        print("    python scripts\\rig_preflight.py")
        return 0
    print(f"  FROZEN -- candidate {version} @ {short} is coherent and CI-green.")
    print("  Next: python scripts\\rig_preflight.py, then run the validation.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
