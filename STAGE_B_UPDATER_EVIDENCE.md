# Stage B updater-evidens — release 1.58.148

Denne runbook bruges **først efter** at den beståede Stage A-SHA er fast-forwardet til
`main`, tagget præcis samme SHA som `v1.58.148` og publiceret som komplet release-sæt.
Ingen kommando her merger, tagger, releaser eller aktiverer produktion.

## Nemmeste vej — anbefalet

Dobbeltklik:

```text
START_STAGE_B_TEST.cmd
```

Wizard'en (`scripts/stage_b_one_click.py`) måler selv alt, der kan måles, og udfylder
`validation/appliance-lifecycle-observations.json` løbende:

- kandidatens version, Git-SHA og worker-fingerprint;
- vært og tidsstempler;
- reboot-tid og de versioner, der kom op bagefter;
- supervisorens genstartstid for backend og worker (stopper processen og måler, indtil
  supervisoren selv bringer den tilbage);
- den gode updater-kørsel, tee'et til `good_update.log`;
- den ugyldige kørsel og dens udfald;
- SHA-256 for hver logfil;
- om dokumenter og schedules overlevede (talt før og efter).

Den er resumérbar: fremdriften gemmes i `validation/stage-b-easy-state.json`, så et
sikkert stop kan genoptages med samme dobbeltklik.

**Du skal kun gøre to ting:** genstarte riggen når wizard'en beder om det, og godkende
den ugyldige opdatering med `JA`.

Sæt testdepotet for den ugyldige kørsel, før du starter, så trin 5 kan køre selv:

```powershell
$env:KALIV_STAGE_B_BAD_REPO = "Ternedal/ModelRig-updater-negative"
```

## Hvad Stage B skal bevise

Den gode update skal være en rigtig updater-kørsel fra 1.58.147 til 1.58.148 og bevise
hele kæden:

1. alle tre Windows-binaries downloades;
2. `SHA256SUMS.txt` verificeres;
3. GitHub build provenance verificeres;
4. supervisor og processer stoppes før swap;
5. backend og worker starter på 1.58.148;
6. supervisor-heartbeat skriver efter restart og avancerer;
7. updateren afslutter som `update OK` uden rollback eller bypass.

Den ugyldige update skal enten afvises **før swap** eller afslutte en fuld rollback,
hvor backend, worker og supervisor igen er bevist sunde på 1.58.148.

Følgende må aldrig bruges i Stage B:

```text
-insecure-skip-verify
-skip-attestation
-no-heartbeat-check
```

Den semantiske gate afviser logs med disse bypass-markører, selv hvis de øvrige
booleans i lifecycle-JSON'en er sat til `true`.

## Forudsætning: riggen skal starte på 1.58.147

Updateren opdaterer kun til en **nyere** version. Riggen skal derfor køre den forrige
publicerede release (1.58.147), før den gode kørsel giver mening — wizard'en stopper med
en tydelig fejl, hvis riggen allerede kører 1.58.148.

## 0. Brug den aktuelle updater

Updateren opdaterer ikke sig selv. Hent derfor `modelrig-updater-windows-x64.exe` fra
den publicerede `v1.58.148`-release og erstat den gamle updater, mens den ikke kører.
Verificér filens SHA-256 mod den samme releases `SHA256SUMS.txt`, og gem outputtet
under:

```text
validation/appliance-lifecycle-evidence/updater_binary_check.log
```

Dette er kun udskiftning af updater-værktøjet. Server, worker og supervisor må ikke
kopieres manuelt; deres transition skal ske gennem updateren.

## Den ugyldige opdatering — hvordan den fremkaldes

Runbooken beskrev tidligere kun det krævede udfald, ikke hvordan man når det. Updateren
læser `releases/latest` fra det depot, `-repo` peger på, og verificerer de tre binaries
mod releasens `SHA256SUMS.txt`. Et separat, offentligt testdepot med bevidst forkerte
digests giver derfor en ren afvisning før swap, uden at røre den rigtige release:

```text
Ternedal/ModelRig-updater-negative   (release v99.0.0)
```

Assets dér er korte tekstfiler, ikke binaries; de eksekveres aldrig, fordi updateren
stopper ved checksum-kontrollen. Depotet skal være **offentligt** — updateren sender
ingen GitHub-token.

Manuel kørsel, hvis du hellere vil styre den selv:

```powershell
.\modelrig-updater-windows-x64.exe -repo Ternedal/ModelRig-updater-negative 2>&1 | `
  Tee-Object validation\appliance-lifecycle-evidence\bad_update.log
```

Forventet i loggen: `update available: 1.58.148 -> v99.0.0`, `downloading …`, og
`checksum MISMATCH … refusing to install` — og **intet**
`stopping supervisor + processes`.

## Manuel fallback

Hele flowet kan stadig køres i hånden. Opret lifecycle-filerne:

```powershell
cd C:\Users\admin\Desktop\ModelRig-git
Copy-Item `
  eval\appliance_lifecycle_observations.example.json `
  validation\appliance-lifecycle-observations.json
New-Item -ItemType Directory `
  validation\appliance-lifecycle-evidence `
  -Force | Out-Null
```

Udfyld reboot- og supervisor-felterne som beskrevet i
`PHYSICAL_VALIDATION_CAMPAIGN.md`.

Kør den gode opdatering elevated og gem **hele** stdout og stderr:

```powershell
.\modelrig-updater-windows-x64.exe 2>&1 | `
  Tee-Object `
    validation\appliance-lifecycle-evidence\good_update.log
```

Loggen skal blandt andet indeholde:

```text
update available: 1.58.147 -> v1.58.148
downloading modelrig-server-windows-x64.exe
downloading modelrig-supervisor-windows-x64.exe
downloading modelrig-worker-windows-x64.exe
checksums verified for 3 exe(s)
build provenance verified for 3 exe(s)
stopping supervisor + processes so the exes unlock
supervisor heartbeat advanced past the restart
update OK: backend + worker report 1.58.148 and the supervisor is looping
```

Udfyld `trials.good_update`, sæt `evidence_path` til loggen og beregn:

```powershell
(Get-FileHash `
  validation\appliance-lifecycle-evidence\good_update.log `
  -Algorithm SHA256).Hash.ToLowerInvariant()
```

Gem den komplette log for den ugyldige kørsel som:

```text
validation/appliance-lifecycle-evidence/bad_update.log
```

Gaten accepterer kun én af disse maskinelt synlige udfald:

- **pre-swap refusal:** checksum/provenance/release-integritet afvises, før loggen når
  `stopping supervisor + processes`;
- **healthy rollback:** loggen indeholder både `ROLLING BACK to 1.58.148` og
  `rolled back to 1.58.148: backend + worker healthy and the supervisor is looping`.

`ROLLBACK FAILED`, `manual_recovery`, bypass-flags eller en tilbageværende
`update-transaction.json` blokerer Stage B.

Udfyld `trials.bad_update`, sæt logsti/hash og bekræft fysisk, at data og schedules er
bevaret.

## Verificér hele Stage B-bundlen

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
