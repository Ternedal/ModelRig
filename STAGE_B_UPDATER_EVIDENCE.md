# Stage B updater-evidens — release 1.58.151

Denne runbook bruges først efter, at den beståede Stage A-SHA er fast-forwardet
til `main`, tagget som `v1.58.151` på præcis samme SHA og publiceret som et
komplet signeret release-sæt. Ingen kommando her merger, tagger, releaser eller
aktiverer produktion.

## Hvad 1.58.151 kan og ikke kan bevise

`1.58.151` er den første release, der er tiltænkt updater self-update-support.
Den tidligere `1.58.150`-updater indeholder ikke denne kode og kan derfor ikke
automatisk opgradere sig selv.

Stage B for 1.58.151 bruger derfor denne ærlige grænse:

- source appliance: signeret `1.58.150`;
- target appliance: signeret `1.58.151`;
- updateren fra `v1.58.151` installeres én gang manuelt som bootstrap;
- bootstrap-binarien verificeres mod samme releases `SHA256SUMS.txt` og GitHub
  build provenance;
- server, supervisor og worker opdateres derefter gennem updateren;
- automatisk signed-release-to-signed-release self-update er deferred til issue
  #401 og kræver 1.58.151 som source samt en senere signeret target-version.

Issue #401 er ikke en promotion blocker for 1.58.151. Bootstrap, same-version og
interruption/recovery må aldrig beskrives som det fremtidige automatiske bevis.

## Anbefalet indgang

Dobbeltklik:

```text
START_STAGE_B_TEST.cmd
```

Wizard'en (`scripts/stage_b_one_click.py`) måler og checkpoint'er:

- kandidatens version, Git-SHA og worker-fingerprint;
- host og UTC-timestamps;
- source release-SHA fra `v1.58.150`;
- updater-bootstrapens filhash og releasebinding;
- god appliance-update til 1.58.151;
- reboot og supervisor-restarts på target-versionen;
- ugyldig update og dens pre-swap refusal eller rollback;
- data- og schedule-bevarelse;
- logstier og SHA-256 for alle evidensfiler.

Fremdriften ligger i `validation/stage-b-easy-state.json`, så sikre stop kan
genoptages. Wizard'en må ikke pushe, merge, tagge, release eller aktivere.

Sæt testdepotet til den ugyldige kørsel før start:

```powershell
$env:KALIV_STAGE_B_BAD_REPO = "Ternedal/ModelRig-updater-negative"
```

## 0. Lås release-checkouten

```powershell
cd C:\Users\Anders\Desktop\ModelRig
git fetch --tags origin
git switch --detach v1.58.151
if ((git rev-parse HEAD).Trim().Length -ne 40) { throw "Ugyldig release-SHA" }
if (git status --short) { throw "Working tree er ikke ren" }
if ((Get-Content VERSION -Raw).Trim() -ne "1.58.151") { throw "Forkert version" }
```

Den publicerede tag-SHA skal være identisk med den Stage A-kandidat, der blev
godkendt. Ellers er Stage A ugyldig.

## 1. Bootstrap updateren én gang

Stop enhver kørende updater. Hent
`modelrig-updater-windows-x64.exe` fra den publicerede `v1.58.151`-release,
verificér SHA-256 mod samme releases `SHA256SUMS.txt`, verificér provenance og
gem målingen i:

```text
validation/appliance-lifecycle-evidence/updater_binary_check.log
```

Erstat kun updater-værktøjet. Server, supervisor og worker må ikke kopieres
manuelt.

Bootstrap-checket skal registrere mindst:

- release tag og release Git-SHA;
- assetnavn;
- forventet og faktisk SHA-256;
- provenance-resultat;
- UTC-timestamp;
- operator/host.

## 2. God appliance-update: 1.58.150 → 1.58.151

Riggen skal starte på 1.58.150 for at bevise en reel transition. Updateren
installerer kun en nyere release og skal stoppe, hvis backend/worker allerede
rapporterer 1.58.151.

Kør elevated og gem hele stdout/stderr:

```powershell
.\modelrig-updater-windows-x64.exe 2>&1 | `
  Tee-Object validation\appliance-lifecycle-evidence\good_update.log
```

Loggen skal semantisk bevise:

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

Efter success skal backend og worker rapportere 1.58.151, appliance-journalen
skal være arkiveret som `committed`, og den live updater skal stadig matche den
verificerede 1.58.151-bootstrap.

Automatisk post-commit self-update kan køre, men der findes ingen nyere release
at installere i denne kampagne. Et no-op/current-resultat er derfor ikke #401's
signed-to-signed bevis.

## 3. Reboot og supervisor-restarts

Efter den gode update måles:

1. normal reboot til ready;
2. backend process-kill og supervisor recovery;
3. worker process-kill og supervisor recovery.

Alle tre trials skal observere 1.58.151, target worker-fingerprint og et
supervisor-heartbeat, der faktisk avancerer.

## 4. Ugyldig update

Brug det eksplicitte negative depot:

```powershell
.\modelrig-updater-windows-x64.exe `
  -repo Ternedal/ModelRig-updater-negative 2>&1 | `
  Tee-Object validation\appliance-lifecycle-evidence\bad_update.log
```

Det accepterede udfald er enten:

- checksum/provenance/release-integritetsafvisning før
  `stopping supervisor + processes`; eller
- fuld rollback, hvor backend, worker og supervisor igen er sunde på 1.58.151.

`ROLLBACK FAILED`, `manual_recovery`, manglende live executable, en stående
`update-transaction.json` eller mismatchende aktiv version blokerer.

## 5. Interruption/recovery

Kør de dokumenterede interruption-punkter omkring appliance-swap og Windows
replacement helper. Efter hver interruption skal næste updater-run enten
færdiggøre eller rulle hele sættet tilbage uden at efterlade et manglende live
executable-navn.

Hvis `.pending` efterlades bevidst under helper-testen, skal den gamle live
updater fortsat være intakt og runnable. Den efterfølgende sikre rerun skal
rydde eller konsumere pending-state deterministisk.

Dette er replacement-safety, ikke automatisk signed-to-signed self-update.

## 6. Forbudte bypasses

Følgende må aldrig forekomme i kommandoer eller logs:

```text
-insecure-skip-verify
-skip-attestation
-no-heartbeat-check
```

Den semantiske gate afviser dem, selv hvis manuelle booleans er sat til `true`.

## 7. Verificér hele Stage B-bundlen

Sæt token til release-freeze-kontrollen:

```powershell
$env:GH_TOKEN = gh auth token
```

Dobbeltklik:

```text
VERIFY_STAGE_B_EVIDENCE.cmd
```

Launcheren kører fail-closed:

1. `freeze_check.py`;
2. `appliance_lifecycle_updater_chain.py`;
3. `physical_validation_campaign.py --mode verify`;
4. `physical_validation_final_gate.py`;
5. `stage_b_physical_gate.py`.

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

Review hashes for updater-chain-, campaign- og component-final-rapporterne.
Stop derefter. Aktivering kræver stadig en separat eksplicit beslutning.
