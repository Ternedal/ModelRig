# Physical validation campaign — 2.0.11

Denne runbook samler de fysiske Prove-opgaver for ModelRig 2.0.11. En
upubliceret kandidat starter i `STAGED_PHYSICAL_PROMOTION.md`. Releasefasens
updater- og lifecycle-operationer styres af `STAGE_B_UPDATER_EVIDENCE.md`.

`scripts/physical_validation_campaign.py` er read-only: den starter ikke
services, bruger ingen token, udfører ingen update eller reboot og ændrer ingen
featureflag. Den genvaliderer rapporterne mod én identitet og skriver en atomisk
kampagnerapport med `production_activation=false`.

## Fælles invariants

Alle rapporter skal binde til samme:

- version `2.0.11`;
- eksakte 40-tegns kandidat-/release-SHA;
- worker `code_sha256`, hvor runtime-koden måles;
- rene checkout og konsistente versionsstempler;
- friske timezone-aware timestamps;
- grønne gates og komplet cleanup.

Evidens fra 2.0.10 eller tidligere, og evidens fra en tidligere ugyldiggjort
2.0.11-head, må ikke genbruges. Flytter HEAD eller `origin/main` sig, skal den
relevante freeze køres igen før mere evidens samles eller accepteres.

## Stage A — kandidatbeviser

Kør normalt `START_STAGE_A_TEST.cmd`. Den manuelle operatør er
`scripts/run-stage-a-physical-validation.ps1` med `Prepare`, `Verify` og
`Complete` som beskrevet i `STAGED_PHYSICAL_PROMOTION.md`.

Stage A samler:

1. T-004 rig preflight;
2. T-005 Agent 3 appliance-validation;
3. T-007 plan-only model-eval;
4. T-040 voice-baseline;
5. T-043 RAG 1k/10k-baseline;
6. T-019 scheduler-pilot;
7. det interaktive browser-/peer-bevis.

Den afsluttende gate tæller alle syv fysiske beviser og består kun, når alle syv evidence statuses er grønne og bundet til samme kandidatidentitet.

Stage A kan højst give `candidate_ready_for_fast_forward=true`. Den må ikke
påstå `release_complete=true` eller fysisk updater-lifecycle completion.

## T-004 — rig preflight

```powershell
python scripts\rig_preflight.py `
  --base-url http://127.0.0.1:8080 `
  --report validation\rig-preflight-latest.json
```

Rapporten skal binde version, SHA og worker-fingerprint. Device-tokenet må aldrig
skrives. Failed checks accepteres ikke.

## T-005 — Agent 3 appliance-validation

Følg `AGENT3_RIG_VALIDATION.md`. Kræv blandt andet:

- `success=true`;
- backend/worker-version 2.0.11;
- worker `code_sha256` lig kandidatens fingerprint;
- fuld cleanup;
- eligibility kun for den dokumenterede developer preview;
- `production_activation=false`.

Rapport:

```text
validation/agent3-rig-validation-latest.json
```

## T-007 — plan-only model-eval

Den dokumenterede production creation path er `/plans/{id}/start`; evalueringen
må ikke genindføre eller antage en særskilt `/plan`-autoritet. Før smoke/eval
skal samme hemmelige `MODELRIG_TOKEN` være konfigureret på både backend og
worker, og `KALIV_AGENT3_ENABLED=true` skal være sat på både backend og worker.
Genstart begge services efter konfigurationsændringer og bekræft tokenparitet
uden at skrive tokenværdien i rapporter eller logs.

```powershell
python scripts\agent3_model_eval.py `
  --planner-model <MODEL> `
  --repetitions 1 `
  --fail-under 1.0 `
  --report validation\agent3-model-eval-latest.json
```

Standardgaten kræver exact-match rate `1.0`, discipline rate `1.0`, nul request
errors, `starts_plans=false` og `executes_tools=false`.

## T-040 — voice-baseline

Følg `VOICE_BASELINE.md`. Kræv grøn top-level gate, nul errors, completed cold
probe, alle cancellation-prober og den typed Pixel stop/barge-in-matrix.

```text
validation/voice-baseline-latest.json
```

## T-043 — RAG-baseline

Følg `RAG_BENCHMARK.md`. Kræv præcis 1.000 og 10.000 chunks, grøn gate, nul
errors og clean source removal for begge skalaer.

```text
validation/rag-benchmark-latest.json
```

## T-019 — scheduler-pilot

Følg `DEVICE_TEST.md` sektion 1.6. Kør read-plan, den afgrænsede write-plan med
fuld approval, pause mid-flight og crash-recovery. Producer:

```cmd
python scripts\scheduler_pilot_report.py --read-schedule-id <ID> --write-schedule-id <ID> --manual-observations validation\scheduler-manual-observations.json --report validation\scheduler-pilot-latest.json
```

Pausens bevis skal være en konkret `released` occurrence bundet til et
`cancelled` job; aggregate tællere er ikke tilstrækkelige.

## Stage B — publiceret release og T-006

Stage B starter først efter exact-SHA fast-forward, tag `v2.0.11` og komplet
signeret release. Kildereleasen er 2.0.10; målreleasen er 2.0.11.

Følg `STAGE_B_UPDATER_EVIDENCE.md`. 2.0.11-updateren installeres én gang som
verificeret bootstrap, fordi 2.0.10-updateren ikke indeholder self-update.
Server, supervisor og worker må kun flyttes gennem updateren.

Gennemfør og dokumentér:

1. god appliance-update 2.0.10 → 2.0.11;
2. reboot til ready på 2.0.11;
3. backend supervisor-restart;
4. worker supervisor-restart;
5. ugyldig update afvist før swap eller fuld rollback til 2.0.11;
6. interruption/recovery omkring swap og Windows replacement;
7. bevarede data, credentials og schedules.

Det automatiske signed-release-to-signed-release self-update-bevis er deferred
til issue #401. Det kræver signeret 2.0.11 som source og en senere signeret
target-version større end 2.0.11 og er ikke en blocker for denne release.

### Lifecycle-observationer

Start fra:

```powershell
Copy-Item `
  eval\appliance_lifecycle_observations.example.json `
  validation\appliance-lifecycle-observations.json
New-Item -ItemType Directory `
  validation\appliance-lifecycle-evidence `
  -Force | Out-Null
```

Alle booleans skal være ægte JSON-booleans, tider skal være millisekundtal, og
hver trial skal referere en repository-relativ fil under:

```text
validation/appliance-lifecycle-evidence/
```

`evidence_sha256` skal matche filens bytes. Symlinks, path escape, tomme filer,
filer over 32 MiB og hashdrift afvises.

### Updaterens semantiske kæde

```powershell
python scripts\appliance_lifecycle_updater_chain.py `
  --lifecycle-report validation\appliance-lifecycle-observations.json `
  --report validation\appliance-lifecycle-updater-chain-latest.json
```

Den gode log skal bevise download af server/supervisor/worker, tre checksums,
tre provenance-attestationer, process-stop før swap, backend og worker på
2.0.11 samt avanceret supervisor-heartbeat.

Den ugyldige log accepteres kun som pre-swap refusal eller sund rollback til
2.0.11.

Disse bypasses blokerer altid:

```text
-insecure-skip-verify
-skip-attestation
-no-heartbeat-check
```

`ROLLBACK FAILED`, `manual_recovery`, manglende heartbeat, manglende live
executables eller en stående `update-transaction.json` blokerer også.

Kræv:

```text
schema=kaliv-appliance-lifecycle-updater-chain/v1
gate.passed=true
updater_chain_complete=true
production_activation=false
```

## Verificér hele Stage B

Den autoritative indgang er:

```text
VERIFY_STAGE_B_EVIDENCE.cmd
```

Den kører fail-closed:

1. `freeze_check.py`;
2. `appliance_lifecycle_updater_chain.py`;
3. `physical_validation_campaign.py --mode verify`;
4. `physical_validation_final_gate.py`;
5. `stage_b_physical_gate.py`.

Den samlede kvittering er:

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

Kun dateret, manuelt reviewet evidens må committes. Aktivering kræver fortsat en
separat eksplicit beslutning.
