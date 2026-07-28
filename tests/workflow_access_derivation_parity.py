#!/usr/bin/env python3
"""Fire validatorer af een kontrakt maa ikke udlede bekraeftelse forskelligt.

Capability-skemaet v2 valideres af fire moduler: worker (Python), backend (Go),
desktop (Kotlin) og Android (Kotlin). Alle fire skal afgoere om en descriptor
kraever bekraeftelse -- og de gjorde det paa TO maader:

    Go      if Access == "write" || Access == "desktop"   -> required
    Kotlin  if (access == "read") "none" else "required"

Aekvivalente saa laenge access-maengden er praecis {read, write, desktop}, og
fail-OPEN i samme sekund nogen tilfoejer en klasse: en ny vaerdi ville hverken
vaere write eller desktop og dermed slippe uden kort, mens klienterne ville
kraeve det.

Maalt 27/07-2026 da `external` blev proevet som fjerde klasse. Go er nu bragt
paa den fail-closed form de tre andre allerede brugte. Testen scanner KILDEN,
saa en fremtidig validator -- eller en tilbagerulning -- ogsaa fanges.

Run: python3 tests/workflow_access_derivation_parity.py
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

SOURCES = {
    "go": ROOT / "backend/internal/capabilityschema/schema.go",
    "python": ROOT / "worker/app/capability_schema.py",
    "kotlin-android": ROOT / "android/app/src/main/java/dk/ternedal/modelrig/net/CapabilityDescriptorV2.kt",
    "kotlin-desktop": ROOT / "desktop/composeApp/src/main/kotlin/dk/ternedal/modelrig/desktop/net/CapabilityDescriptorV2.kt",
}

#: Den FORBUDTE form: en opremsning af de farlige klasser. Den er fail-open,
#: fordi enhver ny klasse falder udenfor opremsningen.
ENUMERATED = re.compile(
    r'(?:access|Access)\b.{0,30}"write".{0,30}"desktop"', re.I)

passed = failed = 0


def check(condition: bool, message: str) -> None:
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS: {message}")
    else:
        failed += 1
        print(f"  FAIL: {message}")


for name, path in SOURCES.items():
    check(path.is_file(), f"{name}: kilden findes")

offenders = []
for name, path in SOURCES.items():
    if not path.is_file():
        continue
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.lstrip().startswith(("//", "#", "*")):
            continue  # en kommentar der CITERER den gamle form er ikke koden
        if not ENUMERATED.search(line):
            continue
        # En enum-ERKLAERING opremser alle klasser og naevner derfor "read".
        # En fail-open UDLEDNING opremser kun de farlige. Det er forskellen.
        if '"read"' in line:
            continue
        offenders.append((name, line.strip()[:60]))

check(not offenders,
      f"ingen validator udleder bekraeftelse fra en opremsning af farlige "
      f"klasser ({offenders or 'ingen'})")

# Kontrolpunkt: kan moenstret overhovedet finde noget? En doed regex ville
# give en evigt groen gate.
check(bool(ENUMERATED.search('if d.Access == "write" || d.Access == "desktop" {')),
      "kontrol: moenstret fanger den kendte fail-open form")
check(not ENUMERATED.search('if d.Access != "read" {'),
      "kontrol: den fail-closed form er ikke en overtraedelse")

print(f"\naccess derivation parity: {passed} passed, {failed} failed")
if failed:
    raise SystemExit(1)
