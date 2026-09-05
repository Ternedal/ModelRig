#!/usr/bin/env python3
"""Klientens capability-gates maa ikke kunne omgaas i stilhed.

En Kotlin-test af `check()` beviser at REGLEN er rigtig. Den beviser ikke at
reglen bliver BRUGT: sletter man kaldet i AppUi.kt, forbliver den groen, og
filen sender igen PDF'er til en worker uden PyMuPDF.

Det er praecis den fejl AgentStartGuard blev bygget for at undgaa -- "en regel
man kan fjerne uden at noget bliver roedt, er ikke en regel" -- og den samme
lektie som per-kilde til/fra: test kaldestedet, ikke kun byggeklodsen.

VAGTEN ER IKKE EN NAVNELISTE. Gaten SCANNER begge klienttraeer for
dependency-baarne ingest-kald og for mikrofon-aabninger, og kraever at hvert
fund ligger inde i sin vagt. Havde den fulgt en haandholdt liste, skulle den
vedligeholdes af netop den person der glemte det sidste gang -- og en liste
ville have overset at stemme startes fire forskellige steder, hvilket
scanningen faktisk fangede 18/8.

Desktop har i dag hverken ingest eller stemme. Den scannes alligevel, saa en
fremtidig desktop-ingest ikke kan komme ind ugatet.

Run: python3 tests/workflow_client_capability_gates.py
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "support"))
from source_code import strip_comments  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
INGEST_GATE = ROOT / "android/app/src/main/java/dk/ternedal/modelrig/net/IngestCapability.kt"
VOICE_GATE = ROOT / "android/app/src/main/java/dk/ternedal/modelrig/net/VoiceCapability.kt"

TREES = (
    ROOT / "android/app/src/main/java",
    ROOT / "desktop/composeApp/src/main/kotlin",
)

# Kald der kraever en valgfri dependency paa riggen. ingestText og ingestHtml
# er med vilje IKKE her: ren tekst og html.parser kraever ingenting, og en gate
# der kunne spaerre for dem havde gjort klienten ringere end foer den fandtes.
INGEST_CALLS = re.compile(r"\.ingest(Pdf|Docx|Pptx)\s*\(")
MIC_CALLS = re.compile(r"voiceCapture\.start\s*\(")

passed = failed = 0


def check(condition: bool, message: str) -> None:
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS: {message}")
    else:
        failed += 1
        print(f"  FAIL: {message}")


def kode(text: str) -> str:
    """Kildelinjer uden kommentarer -- en omtale i en doc-kommentar er ikke et kald.

    Den gamle udgave strippede kun linjer der BEGYNDER med // eller *, saa en
    halv linje ("foo(); // vaek") slap igennem. Maalt 4/9: caps.supports(
    udkommenteret i VoiceCapability.kt lod gaten forblive groen.
    """
    return strip_comments(text, ".kt")


def kt_filer():
    for tree in TREES:
        if tree.exists():
            for p in sorted(tree.rglob("*.kt")):
                yield p


check(INGEST_GATE.exists(), "IngestCapability.kt findes")
check(VOICE_GATE.exists(), "VoiceCapability.kt findes")
ingest_src = kode(INGEST_GATE.read_text(encoding="utf-8")) if INGEST_GATE.exists() else ""
voice_raw = VOICE_GATE.read_text(encoding="utf-8") if VOICE_GATE.exists() else ""
voice_src = kode(voice_raw)

ingest_fund = []
mic_fund = []
for p in kt_filer():
    if "/test/" in p.as_posix():
        continue
    k = kode(p.read_text(encoding="utf-8"))
    if INGEST_CALLS.search(k):
        ingest_fund.append(p)
    if MIC_CALLS.search(k):
        mic_fund.append(p)

check(len(ingest_fund) > 0, f"fandt ingest-kaldesteder at gate -> {len(ingest_fund)}")
check(len(mic_fund) > 0, f"fandt mikrofon-kaldesteder at gate -> {len(mic_fund)}")

for p in ingest_fund:
    k = kode(p.read_text(encoding="utf-8"))
    navn = p.name
    har = "IngestCapability.check(" in k
    check(har, f"{navn}: kalder IngestCapability.check()")
    first_check = k.find("IngestCapability.check(")
    first_call = INGEST_CALLS.search(k).start()
    check(har and first_check < first_call, f"{navn}: ingest naas foerst EFTER check()")
    check("Verdict.Blocked" in k, f"{navn}: forholder sig til Verdict.Blocked")
    check(har and "throw" in k[first_check:first_check + 900],
          f"{navn}: et blokeret verdict afbryder ingesten")

# Mikrofonen blev tidligere aabnet fire uafhaengige steder. Kravet er derfor
# EEN vagtet indgang -- ikke at hvert sted husker at spoerge.
for p in mic_fund:
    k = kode(p.read_text(encoding="utf-8"))
    navn = p.name
    check(k.count("fun startVoiceCaptureGuarded(") == 1,
          f"{navn}: praecis een vagtet indgang til mikrofonen")
    check(k.count("voiceCapture.start()") == 1,
          f"{navn}: voiceCapture.start() staar kun eet sted -> fandt {k.count('voiceCapture.start()')}")
    vagt = k.find("fun startVoiceCaptureGuarded(")
    vagt_check = k.find("VoiceCapability.check(")
    start_rec = k.find("voiceCapture.start()")
    check(vagt != -1 and start_rec > vagt, f"{navn}: voiceCapture.start() ligger INDE i vagten")
    check(vagt != -1 and vagt_check != -1 and vagt < vagt_check < start_rec,
          f"{navn}: vagten spoerger VoiceCapability FOER mikrofonen aabnes")
    check(k.count("startVoiceCaptureGuarded()") >= 4,
          f"{navn}: alle kaldesteder gaar gennem vagten -> {k.count('startVoiceCaptureGuarded()')}")
    check("VoiceCapability.Verdict.Blocked" in k, f"{navn}: forholder sig til stemme-verdiktet")

check("caps.supports(" in ingest_src,
      "ingest-afgoerelsen gaar gennem WorkerCapabilities.supports (ukendt = tilladt)")
check("Format.TEXT" in ingest_src and "return Verdict.Allowed" in ingest_src,
      "ren tekst kan aldrig blokeres")
check("caps.supports(" in voice_src,
      "stemme-afgoerelsen gaar gennem WorkerCapabilities.supports (ukendt = tilladt)")
check("voiceUsesCloud" not in voice_src and "cloudModel" not in voice_src,
      "stemme-afgoerelsen ser IKKE paa cloud-tilstand (ASR/TTS kan ikke flyttes)")
check("Cloud hj" in voice_raw, "begrundelsen siger at cloud ikke redder det")

# DEN TILBAGEHOLDENDE DEFAULT er hele sikkerhedsmodellen, og den var IKKE
# bevogtet lokalt: en mutation fra "!= false" til "== true" -- som ville
# amputere enhver aeldre rig der ikke rapporterer en noegle -- lod denne gate
# groen 19/8. Kun Kotlin-testen fangede det, og den koerer kun i CI.
#
# Kildetekst-tjek, ikke adfaerdstjek: gaten kan ikke koere Kotlin. Men den kan
# kraeve at den ene linje der baerer modellen staar som den skal.
WC = ROOT / "android/app/src/main/java/dk/ternedal/modelrig/net/WorkerCapabilities.kt"
check(WC.exists(), "WorkerCapabilities.kt findes")
wc = kode(WC.read_text(encoding="utf-8")) if WC.exists() else ""
check("reported[capability] != false" in wc,
      "supports() blokerer KUN paa et udtrykkeligt false (ukendt = tilladt)")
check("== true" not in wc.split("fun supports")[-1].split("\n")[0] if "fun supports" in wc else False,
      "supports() kraever IKKE et udtrykkeligt true")

print(f"\n===== CLIENT CAPABILITY GATES: {passed} passed, {failed} failed =====")
raise SystemExit(0 if failed == 0 else 1)
