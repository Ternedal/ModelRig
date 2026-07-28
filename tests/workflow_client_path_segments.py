#!/usr/bin/env python3
"""Ingen klient maa interpolere en vaerdi raat ind i en sti.

Maalt 27/07-2026 paa Android: runId = "../../healthz" gav stien
/api/v1/experimental/healthz/confirm. Traversalen oploeses foer requesten
sendes, saa et misdannet id aendrede HVILKET endpoint der blev ramt -- paa
bekraeftelsesstien, hvor et menneske godkender noget.

Den blev rettet paa Android, og DESKTOP blev overset. Det er praecis den fejl
fundet selv handlede om: en konvention der fandtes eet sted og ikke var
generaliseret. Derfor en gate der daekker BEGGE platforme frem for endnu et
sted der skal huskes.

Testen scanner kilden, saa den ogsaa faelder en NY klient der glemmer det --
hvor en per-klient-test kun daekker de filer nogen huskede at skrive en test
for.

Run: python3 tests/workflow_client_path_segments.py
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ROOTS = (
    ROOT / "android" / "app" / "src" / "main" / "java",
    ROOT / "desktop" / "composeApp" / "src" / "main" / "kotlin",
)

#: En STI-interpolation der ikke gaar gennem en encoder. Alt efter '?' er
#: undtaget: en query-vaerdi kan ikke aendre hvilket endpoint der rammes,
#: og ToolsClient's ?limit=$limit er et heltal. Det er stien der afgoer
#: ruten, og det er ruten det handler om.
RAW = re.compile(r'"(/api/v1/[^"?]*?)\$(?!\{seg\()(\w+)')

passed = failed = 0


def check(condition: bool, message: str) -> None:
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS: {message}")
    else:
        failed += 1
        print(f"  FAIL: {message}")


def scan(text: str) -> list[str]:
    out = []
    for prefix, var in RAW.findall(text):
        # "...memory$suffix" er en query, ikke et segment: den staar sidst og
        # foelges ikke af en skraastreg.
        if var.lower().endswith("suffix"):
            continue
        out.append(f"{prefix}${var}")
    return out


files = [p for r in ROOTS for p in r.rglob("*.kt")]
check(len(files) > 40, f"scanneren finder kildefiler ({len(files)})")

offenders: dict[str, list[str]] = {}
for f in files:
    hits = scan(f.read_text(encoding="utf-8"))
    if hits:
        offenders[f.name] = hits

check(not offenders,
      f"ingen raa sti-interpolation i nogen klient ({offenders or 'ingen'})")

# Kontrolpunkt: kan moenstret overhovedet finde noget? Uden det ville en
# oedelagt regex give en evigt groen gate.
sample = '''val root = post("/api/v1/experimental/agent3/runs/$runId/confirm", payload)'''
check(scan(sample) == ["/api/v1/experimental/agent3/runs/$runId"],
      "kontrol: moenstret fanger en kendt raa interpolation")

encoded = '''val root = post("/api/v1/experimental/agent3/runs/${seg(runId)}/confirm", payload)'''
check(scan(encoded) == [],
      "kontrol: en encodet interpolation er ikke en overtraedelse")

print(f"\nclient path segments: {passed} passed, {failed} failed")
if failed:
    raise SystemExit(1)
