# T-022 final gate

**Status:** dormant, read-only slutgate for den fysiske Agent 3 write-pilot. Gaten skaber ikke fysisk evidens og ændrer ikke routing, tools, UI, release eller produktion.

## Start

Kør på Windows-riggen:

```text
START_AGENT3_WRITE_PILOT.cmd
```

Launcheren kalder `scripts/agent3_write_pilot_final_gate.py`. Hele den eksisterende positive, negative og forensic pipeline bindes til branchen:

```text
agent/t022-write-pilot-final-gate
```

Dermed skal manifest, 20 positive runs, syv negative cases, artifacts, journal, forensic rapport og slutgate matche samme endelige Git-SHA.

## Kontroller

Final-gaten arkiverer først en ældre rolling gate og kører derefter den samlede lokale pipeline. Bagefter læses `validation/agent3-write-pilot-latest.json` og kontrolleres for:

- schema `kaliv-agent3-write-pilot/v1`;
- `success=true` og tom blocker-liste;
- `production_activation=false` top-level og i summary;
- exact version, Git-SHA, code SHA-256 og Git-identitet;
- ren kandidat og konsistente version stamps;
- højst 24 timers alder og højst 12 timers pilotvindue;
- otte gyldige evidence-hashes;
- præcis 20 positive runs med ordinals 1–20;
- unikke run-, step- og markeridentiteter;
- én fælles godkendelsesenhed;
- præcis syv negative cases med de forventede statuskontrakter.

Den genudfører ikke ledger-forensics. Den eksisterende collector har allerede krydstjekket notesfil, run/event-ledger, approval-use, ToolGate audit og den hashkædede negative journal. Slutgaten kontrollerer collectorens sanitiserede resultat mod den aktuelle kandidat.

## Output

Forensic rapport:

```text
validation/agent3-write-pilot-latest.json
```

Final-gate-rapport:

```text
validation/agent3-write-pilot-final-gate-latest.json
```

Tidligere gates arkiveres under `validation/archive/`. Final-gate-rapporten kopierer ikke rå run-id’er, step-id’er, device-id eller markers.

En eksisterende lokal rapport kan kontrolleres uden at køre kampagnen igen:

```powershell
python scripts\agent3_write_pilot_final_gate.py --assess-only
```

Assess-only kan kun læse og afvise eller godkende en eksisterende rapport. Det kan ikke gøre en ikke-fysisk rapport fysisk.

## Dormant CI-kontrakt

`.github/workflows/agent3-write-pilot-final-gate.yml` har kun manuel `workflow_dispatch`. Den kører validatorens deterministiske kontrakttest og hævder ikke, at GitHub-hosted CI har udført den lokale kampagne.

En grøn final-gate er evidens for en frisk, exact-head-bundet 20+7-rapport. Det er ikke en merge-, release- eller produktionsbeslutning. PR’erne forbliver draft og unmerged.
