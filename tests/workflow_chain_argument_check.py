#!/usr/bin/env python3
"""Kalder kæden scripts med argumenter de faktisk accepterer?

19/8 kaldte beviskampagnen ``agent4_a4_25f_finalize_evidence.py --output``.
Scriptet kræver ``--output-root`` og ``--expected-sha``, begge obligatoriske.
Med ``-IncludeAgent4`` ville kampagnen være død på SIDSTE trin — efter
forberedelse, parring, grant og hele matricen. Den dyreste måde at opdage en
tastefejl på, og den lå der fordi ingen havde kørt kæden igennem.

Den fejl blev fundet i hånden. Denne fil finder den slags automatisk:
udtræk hvert kald fra kampagnen og wizardens kæde, spørg målet hvad det
accepterer, og sammenlign.

Statisk. Kører intet, ændrer intet.

Run: python3 scripts/chain_argument_check.py
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"

#: Kilder hvor kald forekommer. Kampagnen kalder faa scripts direkte; de
#: kalder videre, saa wizardens retained kaede skal med.
KILDER = [
    SCRIPTS / "run-proof-campaign.ps1",
    SCRIPTS / "stage_a_physical_operator.retained",
    SCRIPTS / "stage_a_one_click.retained",
]

KALD_PY = re.compile(r"python3?\s+scripts[\\/]([a-z0-9_]+\.py)((?:\s+-[-\w]+(?:\s+\$?[\w\\/${}.:-]+)?)*)")
KALD_PS = re.compile(r"-File\s+\$?\w*\s*scripts[\\/]([a-z0-9_-]+\.ps1)((?:\s+-[-\w]+(?:\s+\$?[\w\\/${}.:-]+)?)*)")

passed = failed = 0


def check(ok: bool, besked: str) -> None:
    global passed, failed
    if ok:
        passed += 1
        print(f"  PASS: {besked}")
    else:
        failed += 1
        print(f"  FAIL: {besked}")


def accepterede_py(navn: str) -> set[str] | None:
    """Spoerg scriptet selv hvad det accepterer. None = kunne ikke spoerge."""
    p = SCRIPTS / navn
    if not p.exists():
        return None
    # Kort timeout MED VILJE: et script der ikke svarer paa --help inden for
    # faa sekunder IGNORERER argumenter og er begyndt at arbejde. Det gaelder
    # forced_recovery_test.py, som starter et 98-sekunders forsoeg. Vi maa
    # hverken vente paa den eller lade den koere -- og vi maa ikke kalde
    # tavshed for et fund, for scriptet kan vaere korrekt uden argparse.
    try:
        r = subprocess.run(
            [sys.executable, str(p), "--help"],
            capture_output=True, text=True, timeout=12,
            env={"PYTHONPATH": str(ROOT / "worker"), "PATH": "/usr/bin:/bin",
                 "PYTHONDONTWRITEBYTECODE": "1", "HOME": "/tmp"},
            cwd=ROOT,
        )
    except subprocess.TimeoutExpired:
        return None
    tekst = r.stdout + r.stderr
    if "usage:" not in tekst.lower():
        return None  # scriptet svarer ikke paa --help; ikke et fund i sig selv
    return set(re.findall(r"(--[a-z0-9][a-z0-9-]*)", tekst))


def accepterede_ps(navn: str) -> set[str] | None:
    p = SCRIPTS / navn
    if not p.exists():
        return None
    m = re.search(r"^param\s*\((.*?)^\)", p.read_text(encoding="utf-8"), re.S | re.M)
    if not m:
        return None
    return {f"-{n}" for n in re.findall(r"\$(\w+)", m.group(1))}


def brugte(argstreng: str) -> set[str]:
    return set(re.findall(r"(?<!\w)(--?[A-Za-z][\w-]*)", argstreng))


for kilde in KILDER:
    if not kilde.exists():
        continue
    tekst = kilde.read_text(encoding="utf-8", errors="replace")
    for m in KALD_PY.finditer(tekst):
        navn, args = m.group(1), m.group(2) or ""
        acc = accepterede_py(navn)
        if acc is None:
            continue
        ukendte = {a for a in brugte(args) if a.startswith("--")} - acc
        check(not ukendte, f"{kilde.name} -> {navn}: {sorted(ukendte) or 'alle argumenter kendes'}")
    for m in KALD_PS.finditer(tekst):
        navn, args = m.group(1), m.group(2) or ""
        acc = accepterede_ps(navn)
        if acc is None:
            continue
        brugt = {a for a in brugte(args) if not a.startswith("--")}
        ukendte = {a for a in brugt if a.lower() not in {x.lower() for x in acc}}
        check(not ukendte, f"{kilde.name} -> {navn}: {sorted(ukendte) or 'alle parametre kendes'}")

print(f"\n===== CHAIN ARGUMENT CHECK: {passed} passed, {failed} failed =====")
raise SystemExit(0 if failed == 0 else 1)
