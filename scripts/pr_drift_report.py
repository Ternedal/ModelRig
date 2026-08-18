#!/usr/bin/env python3
"""Hvilke aabne PR'er ville REVERTERE main, hvis de blev merget?

`stale_check.py` svarer paa spoergsmaalet for EEN branch, naar man allerede har
den i haanden. Dette script svarer paa det for hele flaaden, foer nogen aabner
noget som helst.

Baggrunden er konkret: dependabot #359 stod 23 commits bagud og roerte
`desktop/composeApp/build.gradle.kts` -- samme fil som 2.0.9-bumpet aendrede.
Grenens udgave bar `packageVersion = "2.0.7"`. Et merge ville have rullet
desktop-versionen to bump tilbage i stilhed, og `version_tool check` ville
derefter staa roedt paa en aarsag ingen ville gaette paa. Den groenne CI paa
grenen gjaldt desuden en sha fra ti dage foer.

Lektie 36's afgoerende spoergsmaal, stillet for hver aaben PR:

  1. Er main's seneste commit paa hver beroert fil med i branchens historie?
     Hvis ja: branchen er ikke stale paa den fil.
  2. Hvis nej -- AENDRER BRANCHEN SELV FILEN? Er den blot gammel, tager git
     main's udgave rent. Har branchen aendret den, er aendringen en revert af
     main's nyere arbejde, og git anvender den uden at spoerge.

Det er hele forskellen mellem #246 (revert, fanget i haanden) og #250/#251
(blot gamle, gik rigtigt af sig selv).

STACKED PR'ER MAALES MOD DERES EGEN BASE, ikke mod main. Foerste udgave af
dette script gjorde det forkert og flagede 39 af 50 -- Sols T-037/T-038-slices
er stablede med hinanden som base, og maalt mod main saa hver slice ud til at
"aendre" alle forgaengernes filer. En rapport der fyrer 39 gange er ikke et
fund; den er stoej, og den traener folk i at ignorere den. Samme fejlform som
en gate der ikke kan faelde noget: den beviser intet.

For en stacked PR er spoergsmaalet i stedet, om dens BASE er efterslaebende --
det rapporteres separat og som information, ikke som risiko.

Kraever et token med read-adgang. Skriver ingenting og aendrer ingenting.

Run: GITHUB_TOKEN=... python3 scripts/pr_drift_report.py [--limit N]
     python3 scripts/pr_drift_report.py --ref <sha-eller-branch>   (uden token)

--ref maaler EEN reference mod main. Den findes dels for en session der
allerede har en gren i haanden, dels for at scriptet kan proeves mod et
BEKRAEFTET tilfaelde: #359's head giver REVERT-RISIKO paa
desktop/composeApp/build.gradle.kts, hvilket blev verificeret i haanden
18/8 foer PR'en blev lukket uden merge.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request

REPO = "Ternedal/ModelRig"


def api(path: str, token: str):
    req = urllib.request.Request(f"https://api.github.com/repos/{REPO}{path}")
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Accept", "application/vnd.github+json")
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        print(f"  API-fejl {e.code} paa {path}", file=sys.stderr)
        return None


def git(*args: str) -> str:
    return subprocess.run(["git", *args], capture_output=True, text=True).stdout.strip()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=50)
    ap.add_argument("--base", default="origin/main")
    ap.add_argument("--ref", help="maal EEN reference mod base i stedet for alle aabne PRer")
    args = ap.parse_args()

    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if not token and not args.ref:
        print("Saet GITHUB_TOKEN (read-adgang er nok).", file=sys.stderr)
        return 2

    subprocess.run(["git", "fetch", "-q", "origin", "main"], check=False)
    base = git("rev-parse", args.base)
    if not base:
        print(f"Kunne ikke slaa {args.base} op.", file=sys.stderr)
        return 2

    if args.ref:
        head = git("rev-parse", args.ref)
        if not head:
            print(f"Kunne ikke slaa {args.ref} op.", file=sys.stderr)
            return 2
        prs = [{"number": 0, "head": {"sha": head}, "title": args.ref,
                "draft": False, "base": {"ref": "main"}}]
    else:
        prs = api(f"/pulls?state=open&per_page={args.limit}", token)
        if prs is None:
            return 2

    print(f"main = {base[:12]}   aabne PR'er: {len(prs)}\n")

    revert_risiko: list[str] = []
    kun_gamle: list[str] = []
    friske: list[str] = []

    for pr in prs:
        nr = pr["number"]
        head = pr["head"]["sha"]
        titel = pr["title"][:44]
        draft = " [draft]" if pr["draft"] else ""
        base_ref = pr["base"]["ref"]
        stacked = base_ref != "main"

        # Hent PR-headet lokalt. Uden det kan intet af nedenstaaende maales.
        if nr:
            r = subprocess.run(["git", "fetch", "-q", "origin", f"refs/pull/{nr}/head"],
                               capture_output=True, text=True)
            if r.returncode != 0:
                print(f"#{nr:<5} {titel:46} kunne ikke hentes")
                continue

        # Maal mod PR'ens EGEN base. En stacked slice er ikke stale, fordi den
        # ikke indeholder main -- den skal indeholde sin forgaenger.
        if stacked:
            subprocess.run(["git", "fetch", "-q", "origin", base_ref],
                           capture_output=True)
            maal = git("rev-parse", "FETCH_HEAD") or base
        else:
            maal = base

        bagud = git("rev-list", "--count", f"{head}..{maal}")
        foran = git("rev-list", "--count", f"{maal}..{head}")
        filer = [f for f in git("diff", "--name-only", f"{maal}...{head}").splitlines() if f]

        stale_og_aendret: list[str] = []
        stale_men_gammel: list[str] = []
        for f in filer:
            sidste = git("log", "-1", "--format=%H", maal, "--", f)
            if not sidste:
                continue
            er_med = subprocess.run(
                ["git", "merge-base", "--is-ancestor", sidste, head],
                capture_output=True).returncode == 0
            if er_med:
                continue
            # Branchen er gammel paa filen. Aendrer den den SELV?
            mb = git("merge-base", maal, head)
            aendret = git("diff", "--name-only", f"{mb}..{head}", "--", f)
            (stale_og_aendret if aendret else stale_men_gammel).append(f)

        if stale_og_aendret:
            mark = "REVERT-RISIKO"
            revert_risiko.append(f"#{nr}")
        elif stale_men_gammel:
            mark = "kun gammel"
            kun_gamle.append(f"#{nr}")
        else:
            mark = "frisk"
            friske.append(f"#{nr}")

        hvor = f" (base: {base_ref[:38]})" if stacked else ""
        print(f"#{nr:<5} {titel:46}{draft}{hvor}")
        print(f"       {bagud:>4} bagud, {foran:>3} foran, {len(filer):>3} filer   -> {mark}")
        if stacked:
            bag_main = git("rev-list", "--count", f"{maal}..{base}")
            if bag_main and bag_main != "0":
                print(f"         i  basen selv er {bag_main} commits bagud main")
        for f in stale_og_aendret:
            print(f"         ! {f}")
            print(f"           basens seneste: {git('log','-1','--format=%h %s',maal,'--',f)[:70]}")
        for f in stale_men_gammel[:3]:
            print(f"         - {f} (blot gammel; git tager basens udgave)")
        print()

    print("=" * 68)
    print(f"REVERT-RISIKO ({len(revert_risiko)}): {' '.join(revert_risiko) or 'ingen'}")
    print(f"kun gamle    ({len(kun_gamle)}): {' '.join(kun_gamle) or 'ingen'}")
    print(f"friske       ({len(friske)}): {' '.join(friske) or 'ingen'}")
    print()
    print("REVERT-RISIKO betyder ikke 'konflikt'. Det betyder at git kan flette")
    print("rent OG resultatet er forkert -- branchen skriver sin gamle udgave af")
    print("en fil basen har flyttet siden. Diff HELE filen foer merge (lektie 35).")
    print()
    print("Stacked PR'er er maalt mod deres EGEN base. 'i' markerer at basen selv")
    print("er efterslaebende -- information, ikke risiko, foer stakken rebases.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
