# Stage B updater-evidens — release 1.58.151

Denne runbook bruges først efter, at den beståede Stage A-SHA er fast-forwardet
til `main`, tagget som `v1.58.151` på præcis samme SHA og publiceret som et
komplet signeret release-sæt. Ingen kommando her merger, tagger, releaser eller
aktiverer produktion.

## Ærlig releasegrænse

`1.58.151` er den første release med updater self-update-support. Den tidligere
`1.58.150`-updater kan derfor ikke automatisk erstatte sig selv.

Stage B håndhæver denne præcise transition:

- source appliance: signeret `1.58.150`;
- target appliance: signeret `1.58.151`;
- updateren fra `v1.58.151` installeres én gang som bootstrap;
- bootstrap-binarien verificeres mod samme releases `SHA256SUMS.txt` og GitHub
  build provenance;
- server, supervisor og worker flyttes derefter kun gennem updateren.

Det ægte automatiske signed-release-to-signed-release self-update-bevis er
udsat til issue #401. Det kræver signeret 1.58.151 som source og en senere
signeret target-version større end 1.58.151. #401 blokerer ikke promotion af
1.58.151.

## Autoritativ indgang

Dobbeltklik:

```text
START_STAGE_B_TEST.cmd
```

Launcheren kører `scripts/stage_b_one_click_v2.py`. Den gamle
`stage_b_one_click.py` er kun den indre fem-trins lifecycle-motor og kan ikke
alene certificere Stage B.

Strict-wrapperen:

1. kræver backend og worker på præcis `1.58.150`;
2. måler live-updaterens SHA-256 mod `v1.58.151/SHA256SUMS.txt`;
3. kører `gh attestation verify ... --repo Ternedal/ModelRig` mod updateren;
4. hashbinder `updater_binary_check.log` i lifecycle-observationerne;
5. starter updateren og afbryder den først, når journalen viser
   `state=swapping` og mindst ét live swap er registreret;
6. kører updateren med `-recover`;
7. kræver backend og worker tilbage på 1.58.150, alle fire live executables
   til stede og ingen aktiv journal;
8. kører derefter den normale gode update, reboot, supervisor-restarts og den
   ugyldige update.

Fremdriften checkpointes i `validation/stage-b-easy-state.json`. Hvis en god
update allerede er gennemført uden interruption-beviset, stopper wrapperen og
kræver source 1.58.150 gendannet før en ny kampagne.

## Release-checkout

```powershell
cd C:\Users\Anders\Desktop\ModelRig
git fetch --tags origin
git switch --detach v1.58.151
if ((git rev-parse HEAD).Trim().Length -ne 40) { throw "Ugyldig release-SHA" }
if (git status --short) { throw "Working tree er ikke ren" }
if ((Get-Content VERSION -Raw).Trim() -ne "1.58.151") { throw "Forkert version" }
$env:GH_TOKEN = gh auth token
$env:KALIV_STAGE_B_BAD_REPO = "Ternedal/ModelRig-updater-negative"
```

Tag-SHA'en skal være identisk med den Stage A-SHA, der blev godkendt.

## Bindende strict evidens

### Updater-bootstrap

Den målte fil er:

```text
validation/appliance-lifecycle-evidence/updater_binary_check.log
```

Lifecycle-feltet `trials.updater_bootstrap` skal indeholde:

- `performed=true`;
- release-version og release-SHA for 1.58.151;
- assetnavnet `modelrig-updater-windows-x64.exe`;
- ens forventet og faktisk SHA-256;
- `provenance_verified=true`;
- repository-relativ logsti og hash over loggens faktiske bytes.

### Kontrolleret appliance interruption

Før den normale gode update starter strict-wrapperen updateren og overvåger
`update-transaction.json` samt `.tmp`. Den må først terminere updater-processen,
når højeste journalrevision viser:

```text
state=swapping
swapped_count>=1
```

Derefter kører wrapperen `modelrig-updater-windows-x64.exe -recover` og kræver:

```text
recovery_exit_code=0
backend_version=1.58.150
worker_version=1.58.150
live_executables_present=true
journal_absent=true
```

Evidensen ligger i:

```text
validation/appliance-lifecycle-evidence/appliance_interruption.log
```

Det er det gennemførlige appliance-swap-bevis for 1.58.151. Interruption af den
detached updater-replacement-helper kræver en senere signeret updater-target og
er derfor en del af #401, ikke en promotion blocker for 1.58.151.

## Normal lifecycle efter recovery

Når interruption-recovery er grøn, gennemføres:

1. god appliance-update 1.58.150 → 1.58.151;
2. reboot til ready på 1.58.151;
3. backend supervisor-restart;
4. worker supervisor-restart;
5. ugyldig update, der enten afvises før swap eller rulles helt tilbage;
6. bevarede data, credentials og schedules.

Den gode updater-log skal blandt andet indeholde:

```text
update available: 1.58.150 -> v1.58.151
downloading modelrig-server-windows-x64.exe
downloading modelrig-supervisor-windows-x64.exe
downloading modelrig-worker-windows-x64.exe
checksums verified for 3 exe(s)
build provenance verified for 3 exe(s)
stopping supervisor + processes so the exes unlock
supervisor heartbeat advanced past the restart
update OK: backend + worker report 1.58.151 and the supervisor is looping
```

`ROLLBACK FAILED`, `manual_recovery`, manglende live executable, aktiv journal
eller mismatchende version blokerer.

## Forbudte bypasses

Følgende må aldrig forekomme i kommandoer eller logs:

```text
-insecure-skip-verify
-skip-attestation
-no-heartbeat-check
```

## Fail-closed slutverifikation

Dobbeltklik:

```text
VERIFY_STAGE_B_EVIDENCE.cmd
```

Den kalder `scripts/stage_b_physical_gate_v2.py`, som først kører
`stage_b_strict_evidence.py`. Kun hvis strict-gaten er grøn, køres den
eksisterende release-freeze, updater-chain, syv-bevis-kampagne og
otte-bevis-slutgate. Den endelige kvittering hashbinder strict-rapporten.

Kræv i `validation/stage-b-physical-final-latest.json`:

```text
schema=kaliv-stage-b-physical-final/v1
gate.passed=true
release_freeze_complete=true
updater_chain_complete=true
strict_evidence_complete=true
physical_campaign_complete=true
browser_peer_physical_complete=true
all_physical_evidence_complete=true
production_activation=false
summary.total=8
```

Review hashes for strict-, updater-chain-, campaign- og component-final-
rapporterne. Stop derefter. Aktivering kræver fortsat en separat eksplicit
beslutning.
