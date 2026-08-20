#!/usr/bin/env python3
"""Flyt ankeret og genfrys kandidaten — i ét trin, i den rigtige raekkefoelge.

Efter hver landing skal fire ting ske, i praecis denne orden:

  1. anker-grenen flyttes til den nye main
  2. agent3-diagnostics OG agent3-full-diagnostics udloeses paa main
  3. begge skal vaere GROENNE, ellers melder freeze-gaten NOT FROZEN
  4. kandidaten genfryses

Jeg har lavet det i haanden efter hver landing 19-20/8 og tabt et led FIRE
gange: glemt ankeret (kampagnen sagde "candidate does not contain current
origin/main"), glemt workflows (freeze sagde "no agent3-diagnostics run found
for this exact candidate SHA"), og en gang begge dele. Hver enkelt kostede
Anders en spildt koersel, fordi fejlen foerst viser sig naar HAN starter
kampagnen.

Det er fire trin i fast raekkefoelge. Det hoerer ikke til i nogens hukommelse.

Run: GITHUB_TOKEN=... python3 scripts/anchor_and_freeze.py --branch physical-proof/2.0.11
     tilfoej --dry-run for at se hvad der ville ske
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REPO = "Ternedal/ModelRig"
WORKFLOWS = ("agent3-diagnostics.yml", "agent3-full-diagnostics.yml")
#: Begge skal vaere groenne foer freeze. Gaten kraever et run for det EKSAKTE
#: sha, saa en koersel fra foer landingen taeller ikke.


def git(*args: str) -> str:
    r = subprocess.run(["git", "-C", str(ROOT), *args],
                       capture_output=True, text=True, check=False)
    if r.returncode != 0:
        raise SystemExit(f"git {' '.join(args)} fejlede:\n{r.stderr.strip()}")
    return r.stdout.strip()


def api(path: str, token: str, method: str = "GET", body: dict | None = None):
    req = urllib.request.Request(
        f"https://api.github.com/repos/{REPO}{path}",
        method=method,
        data=json.dumps(body).encode() if body else None,
        headers={"Authorization": f"Bearer {token}",
                 "Accept": "application/vnd.github+json",
                 "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req) as resp:
            raw = resp.read()
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        raise SystemExit(f"GitHub API {method} {path} -> {exc.code}: "
                         f"{exc.read().decode()[:200]}") from exc


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--branch", required=True, help="anker-gren, fx physical-proof/2.0.11")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--timeout-minutes", type=int, default=15)
    args = ap.parse_args(argv)

    token = os.environ.get("GITHUB_TOKEN", "").strip()
    if not token:
        raise SystemExit("GITHUB_TOKEN mangler.")

    git("fetch", "-q", "origin", "main")
    sha = git("rev-parse", "origin/main")
    print(f"main: {sha[:8]}")

    if args.dry_run:
        print(f"  ville flytte {args.branch} -> {sha[:8]}")
        print(f"  ville udloese: {', '.join(WORKFLOWS)}")
        print("  ville vente paa groent og derefter genfryse")
        return 0

    # 1) ankeret
    git("branch", "-f", args.branch, "origin/main")
    remote = git("remote", "get-url", "origin")
    push = remote if remote.startswith("http") and "@" in remote else \
        remote.replace("https://", f"https://x-access-token:{token}@")
    subprocess.run(["git", "-C", str(ROOT), "push", "-q", "-f", push, args.branch],
                   check=True, capture_output=True)
    print(f"anker: {args.branch} -> {sha[:8]}")

    # 2) workflows
    for wf in WORKFLOWS:
        api(f"/actions/workflows/{wf}/dispatches", token, "POST", {"ref": "main"})
    print(f"udloest: {', '.join(WORKFLOWS)}")

    # 3) vent paa at BEGGE er groenne paa det eksakte sha
    frist = time.time() + args.timeout_minutes * 60
    while time.time() < frist:
        time.sleep(20)
        runs = api(f"/actions/runs?branch=main&per_page=20", token).get("workflow_runs", [])
        mine = {r["name"]: r for r in runs
                if r["head_sha"] == sha and "agent3" in r["name"]}
        if len(mine) >= 2 and all(r["status"] == "completed" for r in mine.values()):
            fejl = [n for n, r in mine.items() if r.get("conclusion") != "success"]
            if fejl:
                raise SystemExit(f"workflows fejlede: {fejl} -- genfryser IKKE")
            print("workflows: begge groenne")
            break
        print(f"  venter ... {len(mine)}/2 fundet")
    else:
        raise SystemExit("workflows blev ikke faerdige i tide -- genfryser IKKE")

    # 4) genfrys
    for p in ROOT.rglob("__pycache__"):
        if ".git" not in p.parts:
            subprocess.run(["rm", "-rf", str(p)], check=False)
    subprocess.run(["rm", "-rf", str(ROOT / "validation")], check=False)
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "candidate_freeze_check.py"),
                        "--expected-sha", sha],
                       cwd=ROOT, capture_output=True, text=True,
                       env={**os.environ, "GITHUB_TOKEN": token,
                            "PYTHONDONTWRITEBYTECODE": "1"})
    print(r.stdout.strip()[-400:] or r.stderr.strip()[-400:])
    if r.returncode != 0:
        return r.returncode
    print(f"\nFAERDIG. main, anker og freeze staar alle paa {sha[:8]}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
