#!/usr/bin/env python3
"""Hvilke flader har fysisk bevis — og hvilke har ingenting?

Rig-dagen 18-19/8 afslørede at kampagnen brugte timerne på de modne flader
(voice, RAG, Agent 3) mens Agent 4's komplette bevissuite lå i repoet uden at
blive kaldt af noget som helst. Defekterne i den var derfor latente.

Det hul blev fundet ved at kigge. Denne fil kigger systematisk, så resten
findes i én omgang i stedet for én rig-dag ad gangen.

For hver flade svarer den på tre ting:
  1. findes fladen i koden?
  2. findes der et FYSISK bevis for den (et script under scripts/)?
  3. bliver det bevis KALDT af beviskampagnen?

Trin 3 er det afgørende. Et bevis der ikke kaldes er ikke dækning — det er en
fil. Agent 4 stod i præcis den tilstand.

Skriver intet, ændrer intet.

Run: python3 scripts/coverage_map.py
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
KAMPAGNE = SCRIPTS / "run-proof-campaign.ps1"

#: Flade -> (kodemarkør, søgeord der udpeger et fysisk bevis for den).
#:
#: Kodemarkøren er en fil eller et flag der beviser at fladen findes. Uden den
#: er fladen ikke bygget endnu, og så er manglende dækning ikke et hul.
#: Flader der med VILJE ikke koeres i en source-only kampagne. De er ikke
#: huller -- de er graenser. Stage B kraever en publiceret kandidat og en rig
#: der starter paa forrige release; kampagnen skriver det selv i sin summary.
#: At koble dem paa ville vaere den falske groenne repoet er bygget imod.
RELEASE_BUNDNE = {"Updater / appliance-livscyklus"}

FLADER: dict[str, tuple[str, tuple[str, ...]]] = {
    "Agent 3 (planer, memory, godkendelser)": ("worker/app/agent3", ("agent3_rig_validation", "agent3_readonly_pilot")),
    "Agent 3 — termination-UI (T-023)": ("worker/app/agent3", ("proof_t023", "termination_ui")),
    "Agent 3 — memory-beskyttelse (T-033)": ("backend/internal/httpapi/agent3_memory_grants.go", ("proof_t033", "memory_protected_backup")),
    "Agent 4 (operator-reads, snapshots)": ("agent4", ("a4_25f_physical_operator",)),
    "Computer Use (skærm, markør, handlinger)": ("worker/app/desktop_capture.py", ("computer_use", "desktop_action", "desktop_screenshot")),
    "Web research": ("worker/app/web_research_tool.py", ("web_research", "browser-peer")),
    "Scheduler": ("worker/app/agent3", ("scheduler_pilot",)),
    "Voice (ASR/TTS, barge-in)": ("worker/app/voice_pipeline.py", ("voice-test", "voice_observations", "voice-baseline")),
    "RAG (ingest, søgning, per-kilde)": ("worker/app/rag_pdf.py", ("rag_benchmark", "rag-benchmark")),
    "Værktøjslaget (ToolGate)": ("worker/app/tools.py", ("tool_isolation", "workflow_baseline")),
    "Updater / appliance-livscyklus": ("backend/cmd/modelrig-updater", ("stage_b", "appliance_lifecycle")),
    "DevControl": ("devcontrol", ("devcontrol",)),
    "Parring og enhedsgrants": ("backend/internal/pairing", ("phone-test", "pairing")),
}


def findes(mark: str) -> bool:
    return (ROOT / mark).exists()


def beviser(noegler: tuple[str, ...]) -> list[str]:
    fundet: list[str] = []
    for p in sorted(SCRIPTS.glob("*")):
        if p.suffix not in {".py", ".ps1"}:
            continue
        if any(n.lower() in p.name.lower() for n in noegler):
            fundet.append(p.name)
    return fundet


def kaldes_af_kampagnen(navne: list[str], kampagnetekst: str, kaede: str) -> list[str]:
    return [n for n in navne if n in kampagnetekst or n in kaede]


def main() -> int:
    kampagne = KAMPAGNE.read_text(encoding="utf-8") if KAMPAGNE.exists() else ""
    # Kampagnen kalder faa scripts direkte; de kalder videre. Saml eet niveau ned.
    kaede = ""
    for navn in re.findall(r"scripts[\\/]([a-z0-9_-]+\.(?:py|ps1))", kampagne):
        p = SCRIPTS / navn
        if p.exists():
            kaede += p.read_text(encoding="utf-8", errors="replace")
    # Foelg kaeden til den ikke vokser mere. Foerste udgave gik to niveauer og
    # meldte parring som et hul, selv om stage-a-voice-test.ps1 kalder
    # telefon-testen. Et daekningskort der lyver er vaerre end ingen kort.
    for _ in range(6):
        foer = len(kaede)
        for navn in set(re.findall(r"([a-z0-9_-]+\.(?:py|ps1))", kaede)):
            q = SCRIPTS / navn
            if q.exists() and q.name not in set():
                tekst = q.read_text(encoding="utf-8", errors="replace")
                if tekst not in kaede:
                    kaede += tekst
        if len(kaede) == foer:
            break
    for p in SCRIPTS.glob("*.retained"):
        kaede += p.read_text(encoding="utf-8", errors="replace")

    huller: list[str] = []
    print("DAEKNINGSKORT — fysisk bevis pr. flade")
    print("=" * 74)
    for flade, (mark, noegler) in FLADER.items():
        if not findes(mark):
            print(f"\n  {flade}")
            print(f"    fladen findes ikke i koden ({mark}) — intet hul")
            continue
        fundne = beviser(noegler)
        kaldt = kaldes_af_kampagnen(fundne, kampagne, kaede)
        if not fundne:
            status, note = "INTET FYSISK BEVIS", "skal skrives"
            huller.append(f"{flade}: intet bevis")
        elif flade in RELEASE_BUNDNE:
            status, note = "release-bundet (ikke et hul)", "koeres foerst naar kandidaten er udsendt"
        elif not kaldt:
            status, note = "BEVIS FINDES, KALDES IKKE", f"{len(fundne)} scripts, ingen kaldt"
            huller.append(f"{flade}: bevis ikke koblet paa")
        else:
            status, note = "daekket", f"{len(kaldt)}/{len(fundne)} kaldt"
        print(f"\n  {flade}")
        print(f"    {status}  ({note})")
        if fundne:
            print(f"    scripts: {', '.join(fundne[:4])}{' ...' if len(fundne) > 4 else ''}")

    print("\n" + "=" * 74)
    if huller:
        print(f"{len(huller)} HULLER:")
        for h in huller:
            print(f"  - {h}")
    else:
        print("Ingen huller.")
    print("\nEt bevis der ikke kaldes er ikke daekning. Agent 4 stod praecis saadan")
    print("indtil 19/8: komplet suite i repoet, kaldt af ingenting, defekter latente.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
