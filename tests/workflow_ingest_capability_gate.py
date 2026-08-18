#!/usr/bin/env python3
"""Ingest-dispatchen maa ikke kunne naas uden capability-tjekket.

En Kotlin-test af IngestCapability.check() beviser at REGLEN er rigtig. Den
beviser ikke at reglen bliver BRUGT: sletter man kaldet i AppUi.kt, forbliver
den groen, og filen sender igen PDF'er til en worker uden PyMuPDF.

Det er praecis den fejl AgentStartGuard blev bygget for at undgaa -- "en regel
man kan fjerne uden at noget bliver roedt, er ikke en regel" -- og den samme
lektie som per-kilde til/fra: test kaldestedet, ikke kun byggeklodsen.

Gaten er derfor STRUKTUREL: hvert ingest-kaldested i klienten skal have
IngestCapability.check() foran sig i samme fil.

Run: python3 tests/workflow_ingest_capability_gate.py
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APPUI = ROOT / "android/app/src/main/java/dk/ternedal/modelrig/ui/AppUi.kt"
GATE = ROOT / "android/app/src/main/java/dk/ternedal/modelrig/net/IngestCapability.kt"

# De ingest-veje der kraever en valgfri dependency paa riggen. ingestText er
# med vilje IKKE her: ren tekst kraever ingenting og maa aldrig kunne blokeres.
DEPENDENT_CALLS = ("client.ingestPdf(", "client.ingestDocx(", "client.ingestPptx(")

passed = failed = 0


def check(condition: bool, message: str) -> None:
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS: {message}")
    else:
        failed += 1
        print(f"  FAIL: {message}")


src = APPUI.read_text(encoding="utf-8")

check(GATE.exists(), "IngestCapability.kt findes")
check("IngestCapability.check(" in src,
      "AppUi kalder IngestCapability.check()")

first_check = src.find("IngestCapability.check(")
for call in DEPENDENT_CALLS:
    pos = src.find(call)
    check(pos != -1, f"kaldestedet {call} findes stadig (gaten maaler noget)")
    if pos != -1:
        check(first_check != -1 and first_check < pos,
              f"{call} naas foerst EFTER IngestCapability.check()")

# Verdict skal faktisk standse turen. Et check hvis resultat ikke bruges er
# dekoration -- den fejl er lavet foer i dette repo (#315's falske groenne).
check("Verdict.Blocked" in src,
      "AppUi forholder sig til Verdict.Blocked (resultatet bruges)")
check("throw" in src[first_check:first_check + 900] if first_check != -1 else False,
      "et blokeret verdict afbryder ingesten frem for at falde igennem")

# Tilbageholdenheden er hele sikkerhedsmodellen: blokér kun paa udtrykkeligt nej.
gate_src = GATE.read_text(encoding="utf-8") if GATE.exists() else ""
check("caps.supports(" in gate_src,
      "afgoerelsen gaar gennem WorkerCapabilities.supports (ukendt = tilladt)")
check("Format.TEXT" in gate_src and "return Verdict.Allowed" in gate_src,
      "ren tekst kan aldrig blokeres af gaten")

print(f"\n===== INGEST CAPABILITY GATE: {passed} passed, {failed} failed =====")
raise SystemExit(0 if failed == 0 else 1)
