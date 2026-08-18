#!/usr/bin/env python3
"""Klientens capability-gates maa ikke kunne omgaas i stilhed.

En Kotlin-test af IngestCapability.check() beviser at REGLEN er rigtig. Den
beviser ikke at reglen bliver BRUGT: sletter man kaldet i AppUi.kt, forbliver
den groen, og filen sender igen PDF'er til en worker uden PyMuPDF.

Det er praecis den fejl AgentStartGuard blev bygget for at undgaa -- "en regel
man kan fjerne uden at noget bliver roedt, er ikke en regel" -- og den samme
lektie som per-kilde til/fra: test kaldestedet, ikke kun byggeklodsen.

Gaten er derfor STRUKTUREL: hvert kaldested skal have sit check() foran sig i
samme fil, og resultatet skal faktisk standse turen. Daekker begge gates --
ingest (IngestCapability) og stemme (VoiceCapability).

Run: python3 tests/workflow_client_capability_gates.py
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

# ---------------------------------------------------------------- stemme
VOICE = ROOT / "android/app/src/main/java/dk/ternedal/modelrig/net/VoiceCapability.kt"
check(VOICE.exists(), "VoiceCapability.kt findes")
voice_src = VOICE.read_text(encoding="utf-8") if VOICE.exists() else ""

check("VoiceCapability.check(" in src, "AppUi kalder VoiceCapability.check()")

# STRUKTUREL, ikke raekkefoelge-baseret: optagelsen blev tidligere startet fire
# uafhaengige steder (composerens mic-tap, overlayets knap, Kapaciteter-arket,
# permission-fortsaettelsen). En gate paa raekkefoelge daekkede kun det foerste.
# Derfor kraeves nu at der findes PRAECIS EEN vagtet indgang, og at
# voiceCapture.start() kun forekommer inde i den.
KODE = "\n".join(
    line for line in src.splitlines()
    if not line.lstrip().startswith(("*", "//", "/*"))
)
check(KODE.count("fun startVoiceCaptureGuarded(") == 1,
      "der findes praecis een vagtet indgang til mikrofonen")
check(KODE.count("voiceCapture.start()") == 1,
      f"voiceCapture.start() staar kun eet sted -> fandt {KODE.count('voiceCapture.start()')}")

vagt = KODE.find("fun startVoiceCaptureGuarded(")
start_rec = KODE.find("voiceCapture.start()")
vagt_check = KODE.find("VoiceCapability.check(")
check(vagt != -1 and start_rec > vagt,
      "voiceCapture.start() ligger INDE i den vagtede indgang")
check(vagt_check != -1 and vagt < vagt_check < start_rec,
      "vagten spoerger VoiceCapability FOER den aabner mikrofonen")
check(KODE.count("startVoiceCaptureGuarded()") >= 4,
      f"alle tidligere kaldesteder gaar gennem vagten -> fandt {KODE.count('startVoiceCaptureGuarded()')}")
check("VoiceCapability.Verdict.Blocked" in src,
      "vagten forholder sig til verdiktet (resultatet bruges)")

# Cloud maa ikke kunne bloedgoere stemme-gaten: voice_pipeline.converse siger
# selv at ASR/TTS ikke kan flyttes. En gate der saa paa cloud-noeglen ville
# lade brugeren tale faerdig og alligevel faa 501.
check("voiceUsesCloud" not in voice_src and "cloudModel" not in voice_src,
      "stemme-afgoerelsen ser IKKE paa cloud-tilstand (ASR/TTS kan ikke flyttes)")
check("caps.supports(" in voice_src,
      "stemme-afgoerelsen gaar gennem WorkerCapabilities.supports (ukendt = tilladt)")
check("Cloud hj" in voice_src,
      "begrundelsen siger at cloud ikke redder det")

print(f"\n===== CLIENT CAPABILITY GATES: {passed} passed, {failed} failed =====")
raise SystemExit(0 if failed == 0 else 1)
