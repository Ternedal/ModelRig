# Staged physical promotion — kandidat først, release bagefter

Denne fil er autoritativ for den fysiske promotion. Den gamle rækkefølge “alle otte beviser før release” er umulig: `freeze_check.py` kræver et publiceret tag, mens updaterens lifecycle-bevis kræver en nyere offentlig release. Derfor bruges samme immutable SHA i to schema-adskilte trin.

## Invariants

- Kandidatversionen er `1.58.141`; riggens tidligere release er `1.58.140`.
- Samme 40-tegns SHA bruges til Stage A, exact fast-forward, tag og release.
- Efter Stage A: ingen squash, rebase, mergecommit eller rettelsescommit.
- SHA-skift ugyldiggør Stage A og kræver ny fysisk evidens.
- Stage A kan kun give `candidate_ready_for_fast_forward=true`.
- Kun Stage B kan give `all_physical_evidence_complete=true`.
- Begge trin bevarer `production_activation=false`.
- Intet merge, tag, release eller aktivering sker uden en særskilt eksplicit beslutning.

# Stage A — pre-release, syv beviser

Stage A styres af `scripts/run-stage-a-physical-validation.ps1`. Launcheren accepterer kun `Prepare`, `Verify` og `Complete`, kræver den eksakte kandidat-SHA og delegerer til den testbare, Windows-only operatør `scripts/stage_a_physical_operator.py`. Operatøren afviser CI, ikke-interaktive terminaler, forkert branch, forkert version, dirty tree og main-drift. Den indeholder ingen repository-, release- eller aktiveringsoperationer.

## A0. Lås checkout

```powershell
cd C:\Users\Anders\Desktop\ModelRig
git fetch origin
git switch agent/t032-integration-candidate
git pull --ff-only origin agent/t032-integration-candidate
$CandidateSha = "<CANDIDATE_SHA>"
if ((git rev-parse HEAD).Trim() -ne $CandidateSha) { throw "Forkert SHA" }
if (git status --short) { throw "Working tree er ikke ren" }
if ((Get-Content VERSION -Raw).Trim() -ne "1.58.141") { throw "Forkert version" }
```

Brug SHA'en fra draft-PR #125; gæt den aldrig.

## A1. Freeze og forbered checklisten

Sæt `GITHUB_TOKEN` eller `GH_TOKEN` i miljøet, og kør:

```powershell
powershell -ExecutionPolicy Bypass -File `
  .\scripts\run-stage-a-physical-validation.ps1 `
  -Action Prepare `
  -ExpectedSha $CandidateSha
```

`Prepare` kører først `candidate_freeze_check.py` og derefter `physical_validation_candidate_campaign.py --mode prepare`. Gaten kræver exact HEAD, ren tree, versionskonsistens, ingen Python-bytecode, seneste `origin/main` som ancestor og grønne `ci`, `agent3-diagnostics`, `agent3-full-diagnostics` og `codeql` på præcis SHA'en. Resultatet bevarer `release_validation_pending=true`, `release_complete=false` og `production_activation=false`.

Kør derefter de seks fysiske kandidatbeviser:

1. T-004 preflight — `PHYSICAL_VALIDATION_CAMPAIGN.md` sektion 1.
2. T-005 Agent 3 — `AGENT3_RIG_VALIDATION.md`.
3. T-007 model-eval — kampagnens sektion 3.
4. T-040 voice — `VOICE_BASELINE.md`, inklusive Pixel-matrix.
5. T-043 RAG — `RAG_BENCHMARK.md`, 1.000 og 10.000 chunks.
6. T-019 scheduler — `DEVICE_TEST.md` sektion 1.6 og `scheduler_pilot_report.py`.

Kør ikke lifecycle endnu; manuel kopiering af binaries er ikke updater-bevis.

## A2. Verificér de seks beviser

```powershell
powershell -ExecutionPolicy Bypass -File `
  .\scripts\run-stage-a-physical-validation.ps1 `
  -Action Verify `
  -ExpectedSha $CandidateSha `
  -MaxAgeHours 168 `
  -MinModelExact 1.0
```

`Verify` genkører exact-SHA freeze og kampagnens verify-mode. Den stopper, medmindre den faste allowlist `preflight`, `agent3`, `model_eval`, `voice`, `rag`, `scheduler_pilot` er frisk, kandidatbundet og grøn. Kræv `candidate_campaign_complete=true`, `release_validation_pending=true`, `release_complete=false` og `production_activation=false`.

## A3. Interaktiv T-032 og syv-bevis gate

Vælg én eksakt, på forhånd godkendt HTTPS/443-URL:

```powershell
$Url = "https://DEN-EKSAKTE-GODKENDTE-URL/"
powershell -ExecutionPolicy Bypass -File `
  .\scripts\run-stage-a-physical-validation.ps1 `
  -Action Complete `
  -ExpectedSha $CandidateSha `
  -Url $Url `
  -MaxAgeHours 168 `
  -MinModelExact 1.0
```

`Complete` genkører freeze og alle seks beviser **før** offentlig kontakt. Derefter kalder den den eksisterende interaktive one-use launcher `run-browser-peer-public-validation.ps1` og til sidst den schema-distinkte `physical_validation_candidate_gate.py`. Browsertrinnets manuelle bekræftelse kan ikke springes over.

Kræv i `validation/physical-validation-candidate-final-latest.json`:

```text
gate.passed=true
candidate_ready_for_fast_forward=true
release_validation_pending=true
release_complete=false
all_physical_evidence_complete=false
production_activation=false
summary.total=7
```

Review version, SHA, worker-fingerprint, seks beviser, DNS/connected peer, hashes og byteantal. Stop derefter; Stage A merger, releaser og aktiverer intet.

# Beslutningspunkt

Kun efter eksplicit godkendelse må `main` fast-forwardes til præcis Stage A-SHA'en. Ingen squash, rebase eller mergecommit. Verificér `origin/main`, tag samme SHA som `v1.58.141`, og publicér det komplette release-sæt. Ændres SHA'en, skal Stage A køres om. Valideringsværktøjerne udfører ingen repository-operationer.

# Stage B — release, otte beviser

## B0. Release-freeze og lifecycle

På samme SHA:

```powershell
if ((git rev-parse HEAD).Trim() -ne $CandidateSha) { throw "SHA flyttede sig" }
python scripts\freeze_check.py
```

Release-freeze kræver publiceret `v1.58.141`, samme SHA på `origin/main` og grøn exact-head CI/CodeQL.

Følg derefter `PHYSICAL_VALIDATION_CAMPAIGN.md` sektion 4 og dokumentér T-006:

1. normal reboot;
2. backend supervisor-restart;
3. worker supervisor-restart;
4. gyldig updater-update fra 1.58.140 til 1.58.141;
5. ugyldig update, afvist eller rullet tilbage til 1.58.141.

Den faktiske updater-kæde skal bevise download, checksum, provenance, swap, health og heartbeat. Manuel binærudskiftning tæller ikke.

## B1. Syv-bevis releasekampagne og otte-bevis slutgate

De seks Stage A-rapporter kan genbruges, når de er friske og binder til samme SHA/version/fingerprint. Lifecycle bliver bevis syv.

```powershell
python scripts\physical_validation_campaign.py `
  --mode verify `
  --max-age-hours 168 `
  --min-model-exact 1.0 `
  --report validation\physical-validation-campaign-latest.json

python scripts\physical_validation_final_gate.py `
  --campaign-report validation\physical-validation-campaign-latest.json `
  --browser-attestation validation\browser-peer-public-validation-physical-latest.json `
  --report validation\physical-validation-final-latest.json
```

Kræv:

```text
gate.passed=true
all_physical_evidence_complete=true
production_activation=false
summary.total=8
```

Kun denne schema-distinkte otte-bevis-kvittering kan indgå i en senere separat aktiveringsbeslutning. Den aktiverer stadig intet af sig selv.
