#!/usr/bin/env python3
"""Stale-tjek foer merge: hvilke filer er branchen bagud paa, og betyder det noget?

HANDOFF lektie 35 og 36 i koerbar form. Koert i haanden seks gange 30/7 --
paa #250, #251, #229/#234/#236/#237, #238/#240, #230/#231/#233 og t023-stakken
-- og hver gang fandt det noget. Det hoerer ikke til i hukommelsen paa en
kommandolinje.

DET DER GOER FORSKELLEN er ikke listen over bagudliggende filer, men
diskriminatoren bagefter:

  Er filen BLOT GAMMEL (branchen har ikke roert den siden merge-base)?
      -> git tager main's udgave rent. Sikkert.

  AENDRER BRANCHEN DEN SELV?
      -> saa er branchens aendring en REVERT af main's nyere arbejde, og git
         anvender den uden konflikt og uden et ord. Kraever review.

Det er praecis forskellen mellem #246 (revert, skulle rettes i haanden) og
#250/#251 (blot gamle, gik rigtigt af sig selv) -- paa noejagtig de samme syv
filer. Og #235 viser hvorfor optaellingen alene lyver: et versionsbump til en
eksisterende fil har "nul nye filer" og ligner en tom skal.

Brug:
    python3 scripts/stale_check.py origin/agent/min-branch
    python3 scripts/stale_check.py origin/agent/min-branch --base origin/main

Exit 0 hvis intet kraever review, 1 hvis noget goer. Ingen netvaerksadgang,
ingen skrivning -- den laeser kun git.
"""
from __future__ import annotations

import argparse
import subprocess
import sys

# Genererede filer: de regenereres ved landing, saa en afvigelse i dem er stoej.
GENERATED = {
    "CURRENT_STATE.md",
    "ROUTE_INVENTORY.md",
    "ACTIVATION_READINESS.md",
}


def git(*args: str) -> str:
    result = subprocess.run(
        ["git", *args], capture_output=True, text=True, check=False
    )
    return result.stdout.strip()


def blob(ref: str, path: str) -> str | None:
    """Blob-sha for en fil paa en ref, eller None hvis den ikke findes der."""
    out = subprocess.run(
        ["git", "rev-parse", f"{ref}:{path}"], capture_output=True, text=True
    )
    return out.stdout.strip() if out.returncode == 0 else None


def is_ancestor(commit: str, ref: str) -> bool:
    return (
        subprocess.run(
            ["git", "merge-base", "--is-ancestor", commit, ref],
            capture_output=True,
        ).returncode
        == 0
    )


def classify(head: str, base: str) -> tuple[list, list, list, list]:
    """Returnér (nye, blot_gamle, vil_overskrive, main_ogsaa_flyttet).

    Kriteriet er INDHOLD, ikke ancestry. Ancestry alene lyver: en branch der
    har merget main med ``-X ours`` fremstaar ajour, mens den stadig baerer sin
    egen aeldre udgave af filen. Det er praecis den situation git anvender uden
    konflikt og uden et ord (lektie 35).

    - nye:            findes ikke paa base
    - blot_gamle:     base har flyttet sig, branchen har ikke roert filen
                      -> git tager base's udgave rent. Sikkert.
    - vil_overskrive: branchen har roert filen OG dens udgave afviger fra base
                      -> landingen overskriver base's indhold. Diff HELE filen.
    - main_ogsaa_flyttet: delmaengde af vil_overskrive hvor base ogsaa har
                      flyttet sig siden merge-base. Mest mistaenkelige -- men
                      BEST EFFORT: har branchen merget base, er merge-base lig
                      base's tip, og sub-flaget kan ikke fyre. Derfor bygger
                      hovedflaget paa indhold og ikke paa dette.
    """
    merge_base = git("merge-base", base, head)
    if not merge_base:
        raise SystemExit(f"kan ikke finde merge-base mellem {base} og {head}")

    new_files: list[str] = []
    merely_old: list[tuple[str, str]] = []
    will_overwrite: list[tuple[str, str]] = []
    base_moved_too: list[str] = []

    for path in [p for p in git("diff", "--name-only", merge_base, head).split("\n") if p]:
        if path in GENERATED:
            continue
        on_base = blob(base, path)
        if on_base is None:
            new_files.append(path)
            continue

        on_head = blob(head, path)
        at_merge_base = blob(merge_base, path)
        branch_touched = on_head != at_merge_base
        base_moved = on_base != at_merge_base
        last = git("log", "-1", "--format=%H", base, "--", path)
        subject = git("log", "-1", "--format=%h %s", last) if last else "?"

        if not branch_touched:
            if base_moved or (last and not is_ancestor(last, head)):
                merely_old.append((path, subject))
            continue

        if on_head != on_base:
            will_overwrite.append((path, subject))
            if base_moved or (last and not is_ancestor(last, head)):
                base_moved_too.append(path)

    return new_files, merely_old, will_overwrite, base_moved_too


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("head", help="branch der skal merges, fx origin/agent/min-branch")
    parser.add_argument("--base", default="origin/main", help="default: origin/main")
    args = parser.parse_args()

    new_files, merely_old, will_overwrite, base_moved_too = classify(args.head, args.base)

    print(f"{args.head}  ->  {args.base}")
    print(f"  nye filer:                     {len(new_files)}")
    print(f"  bagud, men blot gamle:         {len(merely_old)}")
    print(f"  vil OVERSKRIVE {args.base}'s udgave: {len(will_overwrite)}"
          f"  (heraf {len(base_moved_too)} hvor {args.base} ogsaa har flyttet sig)")

    if merely_old:
        print("\n  Blot gamle -- git tager main's udgave rent:")
        for path, subject in merely_old:
            print(f"    {path}")
            print(f"        main's seneste: {subject}")

    if will_overwrite:
        print(f"\n  VIL OVERSKRIVE -- diff HELE filen mod {args.base}, ikke kun din hunk:")
        for path, subject in will_overwrite:
            mark = "  <-- ogsaa flyttet paa base" if path in base_moved_too else ""
            print(f"    {path}{mark}")
            print(f"        base's seneste: {subject}")
        print("\n  Lektie 35: 'ingen konflikter' betyder at git kunne kombinere")
        print("  aendringerne, ikke at kombinationen er rigtig.")
        return 1

    print("\n  Branchen overskriver ingen eksisterende fil.")
    print("  BEMAERK: dette svarer kun paa hvad landingen overskriver. Det siger")
    print("  intet om aendringen er rigtig.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
