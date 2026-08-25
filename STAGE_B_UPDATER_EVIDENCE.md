# Stage B updater-evidens — release 2.0.12

Denne runbook bruges først efter, at den beståede Stage A-SHA er fast-forwardet
til `main`, tagget som `v2.0.12` på præcis samme SHA og publiceret som et
komplet signeret release-sæt. Ingen kommando her merger, tagger, releaser eller
aktiverer produktion.

## Ærlig releasegrænse

Stage B håndhæver denne præcise transition:

- source appliance: signeret `2.0.11`;
- target appliance: signeret `2.0.12`;
- updateren fra `v2.0.12` installeres én gang som bootstrap;
- bootstrap-binarien verificeres mod samme releases `SHA256SUMS.txt`, target-
  commit, tagref og release-workflow;
- server, supervisor og worker flyttes derefter kun gennem updateren.

### Åbent punkt: #401's forudsætning ser ud til at være opfyldt nu

Da denne runbook blev skrevet, var `2.0.12` den første release med
updater self-update-support, og den tidligere `2.0.10`-updater kunne derfor
ikke erstatte sig selv. Det ægte automatiske
signed-release-to-signed-release-bevis blev udsat til issue **#401**, som
krævede signeret `2.0.12` som source og en senere signeret target.

Med `2.0.11` som source og `2.0.12` som target er den forudsætning opfyldt: begge
ligger efter `2.0.12`, så sourcens updater har allerede self-update-support.

**Det er ikke afgjort her, om bootstrap-trinnet dermed kan udelades for 2.0.12.**
Scripterne udfører det fortsat, og at fjerne det ændrer hvad evidensen beviser.
Det er en beslutning, ikke en oprydning — og den hører til i #401. Bootstrap
blokerer ikke promotion af `2.0.12`.

## Autoritativ indgang

Dobbeltklik:

```text
START_STAGE_B_TEST.cmd
```

Launcheren kører `scripts/stage_b_one_click_v2.py`. Den gamle
`stage_b_one_click.py` er kun den indre fem-trins lifecycle-motor og kan ikke
alene certificere Stage B.

Strict-wrapperen:

1. kræver backend og worker på præcis `2.0.11`;
2. måler live-updaterens SHA-256 mod `v2.0.12/SHA256SUMS.txt`;
3. kører `gh attestation verify` med repository, target-commit, tagref og
   signer-workflow bundet til samme release;
4. genmåler live-updateren og genkører provenance ved hvert resume;
5. hashbinder `updater_binary_check.log` i lifecycle-observationerne;
6. kræver både `update-transaction.json` og `.tmp` fraværende før launch;
7. starter updateren og følger én ny transaction-ID med monotont revisionstal;
8. afbryder først, når netop den transaktion viser `state=swapping` og mindst ét
   live swap er registreret;
9. kører updateren med `-recover`;
10. kræver backend og worker tilbage på 2.0.10, alle fire live executables
    til stede og ingen aktiv journal;
11. kører derefter den normale gode update, reboot, supervisor-restarts og den
    ugyldige update.

Fremdriften checkpointes i `validation/stage-b-easy-state.json`. Hvis en god
update allerede er gennemført uden interruption-beviset, stopper wrapperen og
kræver source 2.0.10 gendannet før en ny kampagne.

## Release-checkout

```powershell
cd C:\Users\admin\Desktop\ModelRig-git
git fetch --tags origin
git switch --detach v2.0.12
if ((git rev-parse HEAD).Trim().Length -ne 40) { throw "Ugyldig release-SHA" }
if (git status --short) { throw "Working tree er ikke ren" }
if ((Get-Content VERSION -Raw).Trim() -ne "2.0.12") { throw "Forkert version" }
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

Den faktiske provenance-kontrol svarer til:

```powershell
gh attestation verify <updater.exe> `
  --repo Ternedal/ModelRig `
  --source-digest <v2.0.12-git-sha> `
  --source-ref refs/tags/v2.0.12 `
  --signer-workflow Ternedal/ModelRig/.github/workflows/build-and-release.yml
```

Lifecycle-feltet `trials.updater_bootstrap` skal indeholde:

- `performed=true`;
- release-version og release-SHA for 2.0.12;
- assetnavnet `modelrig-updater-windows-x64.exe`;
- ens forventet og faktisk SHA-256;
- `source_digest`, `source_ref` og `signer_workflow` som ovenfor;
- `provenance_verified=true`;
- repository-relativ logsti og hash over loggens faktiske bytes.

Et tidligere `updater_bootstrap_done`-checkpoint er ikke tillid: den live fil og
provenance verificeres igen før kampagnen fortsætter.

### Kontrolleret appliance interruption

Før den normale gode update starter, kræver wrapperen begge aktive journalstier
fraværende. Derefter starter den updateren og overvåger
`update-transaction.json` samt `.tmp`. Main og `.tmp` skal beskrive samme
transaction-ID; højeste revision er autoritativ, og revisionen må aldrig gå
baglæns.

Wrapperen må først terminere den updaterproces, den selv startede, når samme nye
transaktion viser:

```text
from=2.0.10
to=v2.0.12
state=swapping
swapped_count>=1
transaction_id=<non-empty>
revision>=1
```

Derefter kører wrapperen `modelrig-updater-windows-x64.exe -recover` og kræver:

```text
recovery_exit_code=0
backend_version=2.0.10
worker_version=2.0.10
live_executables_present=true
journal_absent=true
```

Evidensen ligger i:

```text
validation/appliance-lifecycle-evidence/appliance_interruption.log
```

Log og observation binder transaction-ID, revision, journalens source/target,
den lancerede updater-PID, kill-resultat og recovery-resultat. En gammel eller
konfliktende `.tmp`, ID-skift eller faldende revision stopper kampagnen.

Det er det gennemførlige appliance-swap-bevis for 2.0.12. Interruption af den
detached updater-replacement-helper kræver en senere signeret updater-target og
er derfor en del af #401, ikke en promotion blocker for 2.0.12.

## Normal lifecycle efter recovery

Når interruption-recovery er grøn, gennemføres:

1. god appliance-update 2.0.10 → 2.0.12;
2. reboot til ready på 2.0.12;
3. backend supervisor-restart;
4. worker supervisor-restart;
5. ugyldig update, der enten afvises før swap eller rulles helt tilbage;
6. bevarede data, credentials og schedules.

Den gode updater-log skal blandt andet indeholde:

```text
update available: 2.0.10 -> v2.0.12
downloading modelrig-server-windows-x64.exe
downloading modelrig-supervisor-windows-x64.exe
downloading modelrig-worker-windows-x64.exe
checksums verified for 3 exe(s)
build provenance verified for 3 exe(s)
stopping supervisor + processes so the exes unlock
supervisor heartbeat advanced past the restart
update OK: backend + worker report 2.0.12 and the supervisor is looping
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

Den kalder `scripts/stage_b_physical_gate_v2.py`. Før første subprocess
overskrives den officielle slutkvittering atomisk med
`status=verification_in_progress` og alle gates false. Et kill, crash eller
strømsvigt kan derfor ikke efterlade en ældre grøn kvittering som aktuel.

Verifieren fjerner gamle intermediate strict/base-rapporter, kører derefter
`stage_b_strict_evidence.py`, og kun hvis strict-gaten er grøn, køres den
eksisterende release-freeze, updater-chain, syv-bevis-kampagne og
otte-bevis-slutgate. Den endelige kvittering hashbinder strict-rapporten.

Kræv i `validation/stage-b-physical-final-latest.json`:

```text
schema=kaliv-stage-b-physical-final/v1
status=complete
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
