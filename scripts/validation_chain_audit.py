#!/usr/bin/env python3
"""Gennemgå den fysiske valideringskæde for de fejlklasser rig-dagen 18/8 afslørede.

Fem defekter blev fundet ÉN AD GANGEN, hver efter en rig-kørsel:

1. `function Git` i PowerShell kaldte sig selv i stedet for `git.exe`;
2. gits fremdrift på stderr væltede scriptet under `$ErrorActionPreference='Stop'`;
3. hele Stage A/B-vejen var pinnet til en kandidat fra juli;
4. producent og forbruger af telefon-teststatus var uenige om schemaet
   (`/v2` skrevet, `/v1` krævet) i tre uger;
5. (operationelt) porte holdt af en manuelt startet stack.

Fælles for 1, 2, 4: **to halvdele der aldrig var kørt sammen.** Denne fil
leder efter den form frem for efter de enkelte fejl, så resten findes i én
omgang i stedet for én rig-kørsel ad gangen.

Skriver intet og ændrer intet.

Run: python3 scripts/validation_chain_audit.py
"""
from __future__ import annotations

import re
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS, TESTS = ROOT / "scripts", ROOT / "tests"

# Programmer der findes paa PATH og derfor kan skygges af en PowerShell-funktion.
NATIVE = {"git", "python", "python3", "go", "ollama", "gh", "adb", "curl", "dotnet"}

fund: list[tuple[str, str, str]] = []


def meld(klasse: str, hvor: str, hvad: str) -> None:
    fund.append((klasse, hvor, hvad))


def kildefiler(*suffikser: str):
    for base in (SCRIPTS, TESTS):
        if not base.exists():
            continue
        for p in sorted(base.rglob("*")):
            if p.suffix in suffikser and p.is_file():
                yield p


# --------------------------------------------------------- 1. schema-versioner
# Fejl 4: skriveren haevede /v1 -> /v2 og laeseren blev ikke rettet.
#
# Foerste udgave af dette tjek GAETTEDE paa hvem der var producent og hvem der
# var forbruger ud fra linjens form. Gaettet var forkert, og den kendte fejl
# landede i den svage klasse. Nu rapporteres KENDSGERNINGEN: hvert schemanavn
# der optraeder med mere end eet versionsnummer, og hvor hver forekomst staar.
# Det kan ikke tage fejl, og listen er kort nok til at laeses.
steder: dict[str, dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))
SCHEMA = re.compile(r'"([a-z0-9][a-z0-9-]*(?:/[a-z0-9-]+)*)/v(\d+)"')

for p in kildefiler(".py", ".ps1", ".retained"):
    for i, linje in enumerate(p.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
        for navn, ver in SCHEMA.findall(linje):
            steder[navn][ver].append(f"{p.name}:{i}")

for navn, pr_ver in sorted(steder.items()):
    if len(pr_ver) < 2:
        continue
    detalje = "; ".join(
        f"v{v} i {', '.join(sorted(set(x.split(':')[0] for x in loc))[:3])}"
        for v, loc in sorted(pr_ver.items())
    )
    meld("FLERE SCHEMA-VERSIONER", navn, detalje)

# ------------------------------------------- 2. PowerShell-funktion skygger program
# Fejl 1: PowerShell oploeser Alias -> Function -> Cmdlet -> Application.
for p in kildefiler(".ps1"):
    txt = p.read_text(encoding="utf-8", errors="replace")
    for m in re.finditer(r"^function\s+([A-Za-z][A-Za-z0-9_-]*)", txt, re.M):
        navn = m.group(1)
        if navn.lower() not in NATIVE:
            continue
        krop = txt[m.end():m.end() + 700]
        if re.search(rf"&\s+{re.escape(navn.lower())}\b(?!\.exe)", krop, re.I):
            meld("SKYGGET PROGRAM", f"{p.name}:{txt[:m.start()].count(chr(10)) + 1}",
                 f"function {navn} kalder '& {navn.lower()}' -> kalder sig selv")

# ------------------------------------ 3. native kommando + Stop + stderr-omdirigering
# Fejl 2: stderr-linjer bliver ErrorRecords og udloeser NativeCommandError.
for p in kildefiler(".ps1"):
    txt = p.read_text(encoding="utf-8", errors="replace")
    if "$ErrorActionPreference" not in txt or "'Stop'" not in txt.replace('"Stop"', "'Stop'"):
        continue
    for i, linje in enumerate(txt.splitlines(), 1):
        if "2>&1" not in linje:
            continue
        if "ErrorActionPreference" in txt[max(0, txt.find(linje) - 400):txt.find(linje)]:
            continue  # preferencen saenkes i naerheden
        if re.search(r"&\s+\$?\w+", linje):
            meld("STDERR UNDER STOP", f"{p.name}:{i}",
                 "native kommando med 2>&1 under ErrorActionPreference=Stop")

# ------------------------------------------------ 4. rester af den gamle kandidat
# Fejl 3: pinningen stod tretten steder og var tre uger bagud.
for p in kildefiler(".py", ".ps1"):
    txt = p.read_text(encoding="utf-8", errors="replace")
    for i, linje in enumerate(txt.splitlines(), 1):
        if linje.lstrip().startswith(("#", "//", "*")):
            continue
        if re.search(r'(EXPECTED_|CANDIDATE_|BRANCH|VERSION)\w*\s*=\s*"[^"]*1\.58\.', linje):
            meld("GAMMEL PIN", f"{p.name}:{i}", linje.strip()[:76])

# Et femte tjek -- "skrives de rapporter nogen laeser?" -- er FJERNET IGEN.
# Det gav 22 fund, og alle var falske: rapporterne skrives gennem hjaelpere som
# regexet ikke kunne se. Et tjek der raaber ulv 22 gange er vaerre end intet
# tjek; det laerer laeseren at ignorere output. Samme lektie som en gate der
# ikke kan faelde noget, bare med modsat fortegn.

# ------------------------------------------------------------------- rapport
print("GENNEMGANG AF DEN FYSISKE VALIDERINGSKAEDE")
print("=" * 74)
if not fund:
    print("\nIngen fund i de fem klasser.\n")
else:
    pr_klasse: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for k, hvor, hvad in fund:
        pr_klasse[k].append((hvor, hvad))
    for k in sorted(pr_klasse, key=lambda x: (not x.isupper(), x)):
        print(f"\n{k}  ({len(pr_klasse[k])})")
        for hvor, hvad in pr_klasse[k]:
            print(f"  {hvor}")
            print(f"    {hvad}")
print("\n" + "=" * 74)
print(f"{len(fund)} fund. VERSALER = samme form som en defekt fundet 18/8.")
