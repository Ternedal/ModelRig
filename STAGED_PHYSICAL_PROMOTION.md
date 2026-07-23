# Staged physical promotion — kandidat først, release bagefter

Denne fil er autoritativ for den fysiske promotion. Den gamle rækkefølge “alle otte beviser før release” er umulig: `freeze_check.py` kræver et publiceret tag, mens updaterens lifecycle-bevis kræver en nyere offentlig release. Derfor bruges samme immutable SHA i to schema-adskilte trin.

## Invariants

- Kandidatversionen er `1.58.145`; riggens tidligere release er `1.58.144`.
- Samme 40-tegns SHA bruges til Stage A, exact fast-forward, tag og release.
- Efter Stage A: ingen squash, rebase, mergecommit eller rettelsescommit.
- SHA-skift ugyldiggør Stage A og kræver ny fysisk evidens.
- Stage A kan kun give `candidate_ready_for_fast_forward=true`.
- Kun Stage B kan give `all_physical_evidence_complete=true`.
- Begge trin bevarer `production_activation=false`.
- Intet merge, tag, release eller aktivering sker uden en særskilt eksplicit beslutning.

# Stage A — pre-release, syv beviser

## Nemmeste vej — anbefalet

På Windows-riggen skal du normalt kun dobbeltklikke:

```text
START_STAGE_A_TEST.cmd
```

One-click-wizard'en:

- henter og fast-forwarder automatisk den rigtige kandidatbranch;
- finder kandidatens eksakte SHA og nægter at gætte den;
- bruger eksisterende GitHub CLI-login eller åbner engangs-login i browseren;
- finder Ollama-modeller og tilbyder at hente manglende planner-/embeddingmodel;
- læser device-token skjult og gemmer det aldrig;
- arkiverer gamle eller fejlede rolling reports, så testen kan genoptages uden tab;
- starter backend og worker direkte fra kandidatens checkout, når den eksisterende stack ikke kan bestå preflight;
- kører preflight, Agent 3, model-eval og RAG automatisk;
- åbner de nødvendige filer og mapper ved voice/Pixel-pausepunktet;
- opretter schedulerens read-plan, gemmer ID'er lokalt og udfører pausekaldet;
- genstarter exact-head worker ved ægte voice cold-start og scheduler crash-recovery;
- kører `Prepare`, `Verify` og `Complete` gennem den eksisterende strikse Stage A-operatør.

Du skal fortsat selv udføre de observationer, som software ikke sandfærdigt kan opfinde: optage de 20 voice-fraser, gennemføre fem Pixel-trials, godkende den kanoniske write-plan i appen, time schedulerens pause/crash og bekræfte det ene offentlige browserkald. Wizard'en kan genoptages ved næste dobbeltklik. Den kan ikke merge, pushe, tagge, release eller aktivere produktion.

## Manuel fallback

Stage A kan fortsat styres direkte af `scripts/run-stage-a-physical-validation.ps1`. Launcheren accepterer kun `Prepare`, `Verify` og `Complete`, kræver den eksakte kandidat-SHA og delegerer til den testbare, Windows-only operatør `scripts/stage_a_physical_operator.py`. Operatøren afviser CI, ikke-interaktive terminaler, forkert branch, forkert version, dirty tree og main-drift. Den indeholder ingen repository-, release- eller aktiveringsoperationer.

## A0. Lås checkout

```powershell
cd C:\Users\Anders\Desktop\ModelRig
git fetch origin
git switch agent/unified-candidate-1.58.145
git pull --ff-only origin agent/unified-candidate-1.58.145
$CandidateSha = "<CANDIDATE_SHA>"
if ((git rev-parse HEAD).Trim() -ne $CandidateSha) { throw "Forkert SHA" }
if (git status --short) { throw "Working tree er ikke ren" }
if ((Get-Content VERSION -Raw).Trim() -ne "1.58.145") { throw "Forkert version" }
```

Brug SHA'en fra draft-PR #161; gæt den aldrig.

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

Kun efter eksplicit godkendelse må `main` fast-forwardes til præcis Stage A-SHA'en. Ingen squash, rebase eller mergecommit. Verificér `origin/main`, tag samme SHA som `v1.58.145`, og publicér det komplette release-sæt. Ændres SHA'en, skal Stage A køres om. Valideringsværktøjerne udfører ingen repository-operationer.

# Stage B — release, otte beviser

## B0. Autoritativ updater-/lifecycle-evidens

Stage B må først begynde efter den separate exact-SHA fast-forward, tag og release. Følg den detaljerede operatorrunbook:

```text
STAGE_B_UPDATER_EVIDENCE.md
```

Updateren opdaterer ikke sig selv. Riggen skal derfor først bruge updater-binarien fra den publicerede `v1.58.145`-release, verificeret mod samme releases `SHA256SUMS.txt`. Server, worker og supervisor må ikke kopieres manuelt; deres transition skal ske gennem updateren.

Dokumentér T-006:

1. normal reboot;
2. backend supervisor-restart;
3. worker supervisor-restart;
4. gyldig updater-update fra 1.58.144 til 1.58.145;
5. ugyldig update, afvist før swap eller fuldt rullet tilbage til 1.58.145.

Den gode updater-log skal maskinelt bevise download af alle tre binaries, checksum, GitHub build provenance, process stop/swap, backend+worker health og et supervisor-heartbeat, der avancerer efter restart. Den ugyldige update skal enten afvises før process-stop/swap eller afslutte en sund rollback. Vilkårlige ikke-tomme hashbundne logs tæller ikke længere som lifecycle-bevis.

Disse bypasses er forbudt og blokeres af `appliance_lifecycle_updater_chain.py`:

```text
-insecure-skip-verify
-skip-attestation
-no-heartbeat-check
```

`ROLLBACK FAILED`, `manual_recovery`, en tilbageværende `update-transaction.json`, manglende updater-markører eller log-hashdrift blokerer ligeledes Stage B.

## B1. Én fail-closed Stage B-slutgate

Sæt `GH_TOKEN`/`GITHUB_TOKEN`, og dobbeltklik:

```text
VERIFY_STAGE_B_EVIDENCE.cmd
```

Launcheren kører i fast rækkefølge:

1. `freeze_check.py` — publiceret `v1.58.145`, exact SHA på `origin/main`, release-tree og softwaregates;
2. `appliance_lifecycle_updater_chain.py` — updaterloggenes semantiske kæde;
3. `physical_validation_campaign.py --mode verify` — syv releasebeviser;
4. `physical_validation_final_gate.py` — browserattestation og otte-bevis component gate;
5. `stage_b_physical_gate.py` — binder komponenternes version, SHA, worker-fingerprint, schemaer, hashes og exitkoder til én slutkvittering.

Den autoritative Stage B-kvittering er:

```text
validation/stage-b-physical-final-latest.json
```

Kræv:

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

Review også de hashbundne komponenter:

```text
validation/appliance-lifecycle-updater-chain-latest.json
validation/physical-validation-campaign-latest.json
validation/physical-validation-final-latest.json
```

Kun denne schema-distinkte otte-bevis Stage B-kvittering kan indgå i en senere separat aktiveringsbeslutning. Den aktiverer stadig intet af sig selv.
