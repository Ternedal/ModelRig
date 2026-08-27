#!/usr/bin/env python3
"""Flyt ankeret og genfrys kandidaten — i ét trin, i den rigtige raekkefoelge.

Efter hver landing skal fire ting ske, i praecis denne orden:

  1. anker-grenen flyttes til den nye main
  2. alle fire exact-SHA software-gates skal eksistere paa main-headen
  3. ci, codeql, agent3-diagnostics og agent3-full-diagnostics skal vaere GROENNE
  4. kandidaten genfryses

CI, CodeQL og begge Agent 3-workflows koerer automatisk paa push til main.
workflow_dispatch beholdes kun som fail-closed fallback, hvis en Agent 3-run
mod forventning slet ikke findes for den allerede eksisterende exact SHA.

Det her maa ikke bero paa operatoerens hukommelse: manglende eller igangvaerende
workflow-evidence er NOT FROZEN, og en fejlet automatisk run bliver ikke skjult
ved automatisk rerun.

Run: GITHUB_TOKEN=... python3 scripts/anchor_and_freeze.py --branch physical-proof/2.0.13
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
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
REPO = "Ternedal/ModelRig"
VENTER_PAA = (
    "ci",
    "codeql",
    "agent3-diagnostics",
    "agent3-full-diagnostics",
)
DISPATCH_FALLBACKS = {
    "agent3-diagnostics": "agent3-diagnostics.yml",
    "agent3-full-diagnostics": "agent3-full-diagnostics.yml",
}


def git(*args: str) -> str:
    r = subprocess.run(
        ["git", "-C", str(ROOT), *args],
        capture_output=True,
        text=True,
        check=False,
    )
    if r.returncode != 0:
        raise SystemExit(f"git {' '.join(args)} fejlede:\n{r.stderr.strip()}")
    return r.stdout.strip()


def api(path: str, token: str, method: str = "GET", body: dict | None = None):
    req = urllib.request.Request(
        f"https://api.github.com/repos/{REPO}{path}",
        method=method,
        data=json.dumps(body).encode() if body else None,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req) as resp:
            raw = resp.read()
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        raise SystemExit(
            f"GitHub API {method} {path} -> {exc.code}: "
            f"{exc.read().decode()[:200]}"
        ) from exc


def _exact_main_runs(sha: str, token: str) -> list[dict[str, Any]]:
    payload = api("/actions/runs?branch=main&per_page=50", token)
    runs = payload.get("workflow_runs", []) if isinstance(payload, dict) else []
    if not isinstance(runs, list):
        raise SystemExit("GitHub workflow response er malformed")
    return [
        run
        for run in runs
        if isinstance(run, dict)
        and run.get("head_sha") == sha
        and run.get("name") in VENTER_PAA
    ]


def _latest_by_name(runs: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    # GitHub returnerer runs newest-first. Bevar derfor foerste match pr. navn;
    # et aeldre success-run maa ikke overskrive en nyere failed/in-progress run.
    latest: dict[str, dict[str, Any]] = {}
    for run in runs:
        name = run.get("name")
        if isinstance(name, str) and name in VENTER_PAA and name not in latest:
            latest[name] = run
    return latest


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--branch", required=True, help="anker-gren, fx physical-proof/2.0.13"
    )
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
        print(f"  ville kraeve exact-SHA gates: {', '.join(VENTER_PAA)}")
        print("  ville kun dispatch'e manglende Agent 3-runs som fallback")
        print("  ville vente paa groent og derefter genfryse")
        return 0

    # 1) ankeret
    git("branch", "-f", args.branch, "origin/main")
    remote = git("remote", "get-url", "origin")
    push = (
        remote
        if remote.startswith("http") and "@" in remote
        else remote.replace("https://", f"https://x-access-token:{token}@")
    )
    subprocess.run(
        ["git", "-C", str(ROOT), "push", "-q", "-f", push, args.branch],
        check=True,
        capture_output=True,
    )
    print(f"anker: {args.branch} -> {sha[:8]}")

    # 2) Main-pushet skal normalt allerede have skabt alle fire runs. Dispatch
    # kun en Agent 3-run hvis den SLET ikke findes paa exact SHA. En eksisterende
    # failed/in-progress run bliver bevidst ikke erstattet eller skjult.
    existing = _latest_by_name(_exact_main_runs(sha, token))
    dispatched: list[str] = []
    for name, workflow_file in DISPATCH_FALLBACKS.items():
        if name in existing:
            continue
        api(
            f"/actions/workflows/{workflow_file}/dispatches",
            token,
            "POST",
            {"ref": "main"},
        )
        dispatched.append(name)
    if dispatched:
        print("fallback udloest: " + ", ".join(dispatched))
    else:
        print("alle Agent 3 exact-SHA runs findes allerede fra main-push")

    # 3) Vent paa ALLE fire gates, inklusive CodeQL. candidate_freeze_check
    # kraever samme saet; helperen maa aldrig starte freeze mens en af dem stadig
    # er queued/in_progress.
    frist = time.time() + args.timeout_minutes * 60
    while time.time() < frist:
        time.sleep(20)
        mine = _latest_by_name(_exact_main_runs(sha, token))
        if len(mine) >= len(VENTER_PAA) and all(
            run.get("status") == "completed" for run in mine.values()
        ):
            fejl = [
                name
                for name, run in mine.items()
                if run.get("conclusion") != "success"
            ]
            if fejl:
                raise SystemExit(
                    f"workflows fejlede: {fejl} -- genfryser IKKE"
                )
            print(f"alle {len(VENTER_PAA)} groenne")
            break
        faerdige = sum(
            1 for run in mine.values() if run.get("status") == "completed"
        )
        print(f"  venter ... {faerdige}/{len(VENTER_PAA)} faerdige")
    else:
        raise SystemExit("workflows blev ikke faerdige i tide -- genfryser IKKE")

    # 4) genfrys
    for p in ROOT.rglob("__pycache__"):
        if ".git" not in p.parts:
            subprocess.run(["rm", "-rf", str(p)], check=False)
    subprocess.run(["rm", "-rf", str(ROOT / "validation")], check=False)
    r = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "candidate_freeze_check.py"),
            "--expected-sha",
            sha,
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "GITHUB_TOKEN": token,
            "PYTHONDONTWRITEBYTECODE": "1",
        },
    )
    print(r.stdout.strip()[-400:] or r.stderr.strip()[-400:])
    if r.returncode != 0:
        return r.returncode
    print(f"\nFAERDIG. main, anker og freeze staar alle paa {sha[:8]}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
