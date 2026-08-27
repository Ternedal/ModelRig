# Staged physical promotion — 2.0.13

Denne fil er den autoritative rækkefølge for fysisk promotion af ModelRig
`2.0.13`. Kandidaten ligger på `physical-proof/2.0.13`; den eksakte SHA skal
altid læses fra den fetch'ede `origin/physical-proof/2.0.13`, matches mod lokal
HEAD og bevises med `candidate_freeze_check.py`. Den må aldrig gættes eller
kopieres fra ældre evidens.

## Ufravigelige grænser

- Stage A kører mod én upubliceret, kvalificeret kandidat-SHA.
- Samme SHA bruges senere til fast-forward, tag `v2.0.13` og release.
- Efter fysisk evidens er begyndt, er squash, rebase, mergecommit, amend og
  enhver anden SHA-ændring forbudt.
- Enhver bevægelse af kandidatbranch eller `origin/main` kræver ny freeze og ny
  evidens.
- Alle receipts og rapporter skal bevare `production_activation=false`.
- Ingen launcher i dette flow merger, pusher, tagger, releaser eller aktiverer.

## Stage A — upubliceret kandidat

### A0. Lås checkouten

```powershell
cd C:\Users\admin\Desktop\ModelRig-git
git fetch origin
git switch physical-proof/2.0.13
git pull --ff-only origin physical-proof/2.0.13
$CandidateSha = (git rev-parse HEAD).Trim()
$RemoteCandidateSha = (git rev-parse origin/physical-proof/2.0.13).Trim()
if ($CandidateSha.Length -ne 40) { throw "Ugyldig kandidat-SHA" }
if ($CandidateSha -ne $RemoteCandidateSha) { throw "Lokal candidate matcher ikke origin/physical-proof/2.0.13: local=$CandidateSha remote=$RemoteCandidateSha" }
if (git status --short) { throw "Working tree er ikke ren" }
if ((Get-Content VERSION -Raw).Trim() -ne "2.0.13") { throw "Forkert version" }
python scripts/candidate_freeze_check.py --expected-sha $CandidateSha
if ($LASTEXITCODE -ne 0) { throw "Candidate er ikke frozen paa exact SHA $CandidateSha" }
```

`origin/physical-proof/2.0.13`, lokal exact HEAD og den grønne
`candidate_freeze_check.py` skal alle pege på samme kandidat-SHA. Stop ved
enhver forskel. Historiske freeze-PR'er og tidligere 2.0.13-heads er ikke
SHA-authority.

### A1. Opret en frisk freeze-receipt

Sæt `GH_TOKEN` eller `GITHUB_TOKEN`, og kør den anbefalede launcher:

```text
START_STAGE_A_TEST.cmd
```

Manuel fallback:

```powershell
powershell -ExecutionPolicy Bypass -File `
  .\scripts\run-stage-a-physical-validation.ps1 `
  -Action Prepare `
  -ExpectedSha $CandidateSha
```

`Prepare` kører `candidate_freeze_check.py` og
`physical_validation_candidate_campaign.py --mode prepare`. Freeze-kontrollen
kræver exact HEAD, ren tree, versionsparitet, current `origin/main` som ancestor
og grønne `ci`, `codeql`, `agent3-diagnostics` og
`agent3-full-diagnostics` på præcis SHA'en.

En freeze-receipt er ikke permanent tilladelse. Hver consumer refetcher
`origin/main`; fetch-fejl eller en flyttet main-anchor afviser receipt'en og
kræver komplet re-freeze.

### A2. Saml de seks kandidatbeviser

1. T-004 preflight — `PHYSICAL_VALIDATION_CAMPAIGN.md`.
2. T-005 Agent 3 appliance-validation — `AGENT3_RIG_VALIDATION.md`.
3. T-007 lokal model-eval.
4. T-040 voice-baseline inklusive Pixel-matrix.
5. T-043 RAG 1k/10k-baseline.
6. T-019 scheduler-pilot.

Kør derefter:

```powershell
powershell -ExecutionPolicy Bypass -File `
  .\scripts\run-stage-a-physical-validation.ps1 `
  -Action Verify `
  -ExpectedSha $CandidateSha `
  -MaxAgeHours 168 `
  -MinModelExact 1.0
```

`Verify` kræver den faste allowlist `preflight`, `agent3`, `model_eval`,
`voice`, `rag` og `scheduler_pilot` frisk, grøn og kandidatbundet.

### A3. Interaktivt browserbevis og kandidatgate

Vælg én på forhånd godkendt offentlig HTTPS/443-URL:

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

`Complete` genkører freeze og de seks beviser, kalder den interaktive
`run-browser-peer-public-validation.ps1` og afslutter med
`physical_validation_candidate_gate.py`.

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

Stop her. Stage A udfører ingen repository- eller releaseoperationer.

## Beslutningspunkt

Kun efter en særskilt eksplicit beslutning må `main` fast-forwardes til præcis
Stage A-SHA'en, samme SHA tagges som `v2.0.13`, og det komplette signerede
release-sæt publiceres. Ændres SHA'en, er Stage A ugyldig.

## Stage B — publiceret 2.0.13

Følg den operative autoritet i `STAGE_B_UPDATER_EVIDENCE.md`.

Kildereleasen for appliance-transitionen er den signerede `2.0.12`, og målet er
`2.0.13`. Target-updaterens checksum og provenance verificeres før swap som den
aktuelle bootstrap-grænse. Server, supervisor og worker må ikke kopieres
manuelt; deres transition skal ske gennem updateren.

Versionsbumpet ændrer ikke automatisk #401's claim. Et særskilt automatisk
signed-release-to-signed-release self-update-bevis må kun hævdes, hvis #401's
egen gate faktisk er gennemført. Det blokerer ikke promotion af 2.0.13, medmindre
den authority ændres særskilt.

Stage B skal dokumentere:

1. normal update fra 2.0.12 til 2.0.13;
2. reboot på 2.0.13;
3. backend supervisor-restart;
4. worker supervisor-restart;
5. ugyldig update afvist før swap eller sund rollback til 2.0.13;
6. interruption/recovery uden manglende live executables;
7. bevarede data, credentials og schedules.

Følgende bypasses er forbudt:

```text
-insecure-skip-verify
-skip-attestation
-no-heartbeat-check
```

`ROLLBACK FAILED`, `manual_recovery`, en stående `update-transaction.json`,
manglende updater-markører eller hashdrift blokerer.

### Én fail-closed Stage B-indgang

```text
VERIFY_STAGE_B_EVIDENCE.cmd
```

Launcheren kører i denne rækkefølge:

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

Kun denne schema-distinkte kvittering kan indgå i en senere separat
aktiveringsbeslutning. Den aktiverer stadig intet af sig selv.
