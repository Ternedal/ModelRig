# Stage B updater-evidens — release 1.58.145

Denne runbook bruges **først efter** en særskilt beslutning har fast-forwardet den
beståede Stage A-SHA til `main`, tagget præcis samme SHA som `v1.58.145` og
publiceret det komplette release-sæt. Ingen kommando her merger, tagger, releaser
eller aktiverer produktion.

## Hvad Stage B skal bevise

Den gode update skal være en rigtig updater-kørsel fra 1.58.144 til 1.58.145 og
bevise hele kæden:

1. alle tre Windows-binaries downloades;
2. `SHA256SUMS.txt` verificeres;
3. GitHub build provenance verificeres;
4. supervisor og processer stoppes før swap;
5. backend og worker starter på 1.58.145;
6. supervisor-heartbeat skriver efter restart og avancerer;
7. updateren afslutter som `update OK` uden rollback eller bypass.

Den ugyldige update skal enten afvises **før swap** eller afslutte en fuld rollback,
hvor backend, worker og supervisor igen er bevist sunde på 1.58.145.

Følgende må aldrig bruges i Stage B:

```text
-insecure-skip-verify
-skip-attestation
-no-heartbeat-check
```

Den semantiske gate afviser logs med disse bypass-markører, selv hvis de øvrige
booleans i lifecycle-JSON'en er sat til `true`.

## 0. Brug den aktuelle updater

Updateren opdaterer ikke sig selv. Hent derfor
`modelrig-updater-windows-x64.exe` fra den publicerede `v1.58.145` release og
erstat den gamle updater, mens den ikke kører. Verificér filens SHA-256 mod den
samme releases `SHA256SUMS.txt`, og gem outputtet under:

```text
validation/appliance-lifecycle-evidence/updater_binary_check.log
```

Dette er kun udskiftning af updater-værktøjet. Server, worker og supervisor må
ikke kopieres manuelt; deres transition skal ske gennem updateren.

## 1. Opret lifecycle-filerne

```powershell
cd C:\Users\Anders\Desktop\ModelRig
Copy-Item `
  eval\appliance_lifecycle_observations.example.json `
  validation\appliance-lifecycle-observations.json
New-Item -ItemType Directory `
  validation\appliance-lifecycle-evidence `
  -Force | Out-Null
```

Udfyld reboot- og supervisor-felterne som beskrevet i
`PHYSICAL_VALIDATION_CAMPAIGN.md`.

## 2. God update: 1.58.144 → 1.58.145

Riggen skal først køre 1.58.144. Kør updateren elevated og gem **hele** stdout og
stderr:

```powershell
.\modelrig-updater-windows-x64.exe 2>&1 | `
  Tee-Object `
    validation\appliance-lifecycle-evidence\good_update.log
```

Loggen skal blandt andet indeholde:

```text
update available: 1.58.144 -> v1.58.145
downloading modelrig-server-windows-x64.exe
downloading modelrig-supervisor-windows-x64.exe
downloading modelrig-worker-windows-x64.exe
checksums verified for 3 exe(s)
build provenance verified for 3 exe(s)
stopping supervisor + processes so the exes unlock
supervisor heartbeat advanced past the restart
update OK: backend + worker report 1.58.145 and the supervisor is looping
```

Udfyld `trials.good_update`, sæt `evidence_path` til loggen og beregn:

```powershell
(Get-FileHash `
  validation\appliance-lifecycle-evidence\good_update.log `
  -Algorithm SHA256).Hash.ToLowerInvariant()
```

## 3. Ugyldig update

Gem den komplette updater-log som:

```text
validation/appliance-lifecycle-evidence/bad_update.log
```

Gaten accepterer kun én af disse maskinelt synlige udfald:

- **pre-swap refusal:** checksum/provenance/release-integritet afvises, før loggen
  når `stopping supervisor + processes`;
- **healthy rollback:** loggen indeholder både `ROLLING BACK to 1.58.145` og
  `rolled back to 1.58.145: backend + worker healthy and the supervisor is looping`.

`ROLLBACK FAILED`, `manual_recovery`, bypass-flags eller en tilbageværende
`update-transaction.json` blokerer Stage B.

Udfyld `trials.bad_update`, sæt logsti/hash og bekræft fysisk, at data og schedules
er bevaret.

## 4. Verificér hele Stage B-bundlen

Sæt et GitHub-token i sessionen, så release-freeze kan kontrollere tag, publiceret
release og exact-head checks:

```powershell
$env:GH_TOKEN = gh auth token
```

Dobbeltklik derefter:

```text
VERIFY_STAGE_B_EVIDENCE.cmd
```

Launcheren udfører fail-closed i denne rækkefølge:

1. `freeze_check.py`;
2. `appliance_lifecycle_updater_chain.py`;
3. syv-bevis releasekampagnen;
4. den eksisterende otte-bevis browser-/slutgate;
5. den samlede `kaliv-stage-b-physical-final/v1`-kvittering.

Kræv i `validation/stage-b-physical-final-latest.json`:

```text
schema=kaliv-stage-b-physical-final/v1
gate.passed=true
release_freeze_complete=true
updater_chain_complete=true
physical_campaign_complete=true
browser_peer_physical_complete=true
all_physical_evidence_complete=true
production_activation=false
summary.total=8
```

Review også hashes for updater-chain-, campaign- og component-final-rapporterne.
Stop derefter. En eventuel aktivering er fortsat en særskilt eksplicit beslutning.
