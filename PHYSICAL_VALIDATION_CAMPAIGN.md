# Physical validation campaign — én release, ét samlet bevis

Denne runbook samler Stage B's syv fysiske **Prove**-opgaver T-004, T-005,
T-006, T-007, T-040, T-043 og T-019. Det interaktive T-032-browserbevis
samles bagefter i otte-bevis-slutgaten. Når alle syv fysiske beviser er grønne,
er releasekampagnen komplet; browserbeviset gør den efterfølgende slutgate til otte.

> **Scope:** Dette er releasefasen. En upubliceret kandidat starter i
> [`STAGED_PHYSICAL_PROMOTION.md`](STAGED_PHYSICAL_PROMOTION.md). T-006 kan først
> bevises, når præcis samme Stage A-SHA er fast-forwardet, tagget og publiceret
> som en nyere release. Den operative updater-runbook er
> [`STAGE_B_UPDATER_EVIDENCE.md`](STAGE_B_UPDATER_EVIDENCE.md).

`scripts/physical_validation_campaign.py` er read-only. Det starter ikke services,
bruger ingen token, udfører ingen update eller reboot og ændrer ingen featureflag.
Det genvaliderer rapporterne mod én candidate-identitet og skriver en atomisk
kampagnerapport med `production_activation=false`.

## Fælles invariants

Alle beviser skal beskrive samme:

- `VERSION`;
- 40-tegns Git-SHA, hvor rapporttypen understøtter den;
- worker `code_sha256`, hvor runtime-koden måles;
- rene checkout og konsistente versionsstempler;
- friske, timezone-aware timestamps;
- grønne individuelle gates og komplet cleanup.

Rolling reports, WAV-fixtures og manuelle observationer ligger under `validation/`
og må ikke gøre checkoutet dirty. Flytter HEAD sig, er kampagnen ugyldig.

## 0. Release-freeze

Stage A skal være bestået først. Fortsæt kun efter den separate exact-SHA
fast-forward, tag `v1.58.145` og publicerede release.

```powershell
cd C:\Users\Anders\Desktop\ModelRig
git status --short
git rev-parse HEAD
Get-Content VERSION
$env:GH_TOKEN = gh auth token
python scripts\freeze_check.py
python scripts\physical_validation_campaign.py `
  --mode prepare `
  --report validation\physical-validation-campaign-latest.json
```

`freeze_check.py` kræver publiceret release, exact tag/HEAD, SHA på `origin/main`,
release-tree-paritet og grøn exact-head `ci`/`codeql`. På en gitless release-ZIP
verificeres hvert committed blob mod release-committen. `prepare` må inventarisere
manglende fremtidige rapporter, men candidate-drift eller røde eksisterende
rapporter blokerer.

## 1. T-004 — rig preflight

```powershell
python scripts\rig_preflight.py `
  --base-url http://127.0.0.1:8080 `
  --report validation\rig-preflight-latest.json
```

Rapporten skal binde version, SHA og worker-fingerprint. Device-tokenet må aldrig
skrives. Warnings accepteres kun i den dokumenterede pre-validation-tilstand;
failed checks accepteres ikke.

## 2. T-005 — Agent 3 appliance-evidens

Følg `AGENT3_RIG_VALIDATION.md`. Kræv blandt andet:

- `success=true`;
- backend/worker-version lig releasen;
- worker `code_sha256` lig release-fingerprint;
- fuld cleanup;
- eligibility for developer preview;
- `production_activation=false`.

Forventet rapport:

```text
validation/agent3-rig-validation-latest.json
```

## 3. T-007 — plan-only model-eval

Forudsætninger:

- `MODELRIG_TOKEN` er et parret device-token;
- `KALIV_AGENT3_ENABLED=1` på både backend og worker;
- backend kører på den angivne `--base-url`;
- produceren bruger den dokumenterede sti `/plan` → `/plans/{id}/start`.

```powershell
python scripts\agent3_model_eval.py `
  --planner-model <MODEL> `
  --repetitions 1 `
  --fail-under 1.0 `
  --report validation\agent3-model-eval-latest.json
```

Standardgaten kræver exact-match rate `1.0`, discipline rate `1.0`, nul request
errors, `starts_plans=false` og `executes_tools=false`. En lavere eksplicit grænse
skal være begrundet; den må ikke sænkes for blot at få grøn status.

## 4. T-006 — reboot, supervisor, updater og rollback

Følg `STAGE_B_UPDATER_EVIDENCE.md`. Start fra den versionerede skabelon:

```powershell
Copy-Item `
  eval\appliance_lifecycle_observations.example.json `
  validation\appliance-lifecycle-observations.json
New-Item -ItemType Directory `
  validation\appliance-lifecycle-evidence `
  -Force | Out-Null
```

Gennemfør og dokumentér:

1. normal reboot → backend og worker ready;
2. backend supervisor-restart;
3. worker supervisor-restart;
4. gyldig updater-update fra `1.58.144` til `1.58.145`;
5. ugyldig update, som afvises før swap eller rulles helt tilbage til `1.58.145`.

### Lifecycle-JSON

Alle booleans skal være ægte JSON-booleans, og tider skal være tal i millisekunder.
`good_update.target_*`, reboot/supervisor identity og `bad_update.active_*` skal
matche releasen. Source- og attempted-SHA skal være forskellige fra release-SHA.
Data og schedules skal være bevaret.

Hver trial skal referere en almindelig repository-relativ fil under:

```text
validation/appliance-lifecycle-evidence/
```

`evidence_sha256` skal matche filens faktiske SHA-256. Symlinks, path escape,
tomme filer, filer over 32 MiB og hashdrift afvises.

### Updaterens semantiske kæde

En vilkårlig ikke-tom log er **ikke** updaterbevis. Kør:

```powershell
python scripts\appliance_lifecycle_updater_chain.py `
  --lifecycle-report validation\appliance-lifecycle-observations.json `
  --report validation\appliance-lifecycle-updater-chain-latest.json
```

Den gode updater-log skal bevise:

- download af server, supervisor og worker;
- `checksums verified for 3 exe(s)`;
- `build provenance verified for 3 exe(s)`;
- process-stop før swap;
- backend og worker på `1.58.145`;
- supervisor-heartbeat, der avancerer efter restart;
- afsluttende `update OK` uden rollback eller fatal tilstand.

Den ugyldige update accepteres kun som:

- en checksum/provenance/release-integritetsafvisning **før** process-stop/swap; eller
- en fuldført rollback med backend, worker og supervisor bevist sunde på
  `1.58.145`.

Disse bypasses blokerer altid:

```text
-insecure-skip-verify
-skip-attestation
-no-heartbeat-check
```

`ROLLBACK FAILED`, `manual_recovery`, manglende heartbeat-markør eller en
stående `update-transaction.json` blokerer også. Kræv i chain-rapporten:

```text
schema=kaliv-appliance-lifecycle-updater-chain/v1
gate.passed=true
updater_chain_complete=true
production_activation=false
```

## 5. T-040 — voice baseline

Følg `VOICE_BASELINE.md`. Kræv grøn top-level gate, nul errors, completed cold
probe, alle connection-cancellation-prober og den beståede typed Pixel
stop/barge-in-matrix.

```text
validation/voice-baseline-latest.json
```

## 6. T-043 — RAG baseline

Følg `RAG_BENCHMARK.md`. Kræv præcis 1.000 og 10.000 chunks, grøn benchmark-gate,
nul errors og clean source removal for begge skalaer.

```text
validation/rag-benchmark-latest.json
```

## 7. T-019 — scheduler-pilot

Følg `DEVICE_TEST.md` sektion 1.6. Kør read-plan via loopback, write-planen med
fuld godkendelsesceremoni, pause mid-flight og crash-recovery. Producer derefter:

```cmd
python scripts\scheduler_pilot_report.py --read-schedule-id <ID> --write-schedule-id <ID> --manual-observations validation\scheduler-manual-observations.json --report validation\scheduler-pilot-latest.json
```

Rapporten skal pinne konkrete occurrences, jobs, audit-sekvenser og receipts.
Pausens bevis er en `released` occurrence bundet til et `cancelled` job; aggregate
tællere alene er ikke promotion-evidens.

## 8. Verificér hele Stage B

Den anbefalede og autoritative indgang er:

```text
VERIFY_STAGE_B_EVIDENCE.cmd
```

Den kører fail-closed:

1. `freeze_check.py`;
2. `appliance_lifecycle_updater_chain.py`;
3. `physical_validation_campaign.py --mode verify`;
4. `physical_validation_final_gate.py`;
5. `stage_b_physical_gate.py`.

Den interne syv-bevis-kampagne kan fortsat køres manuelt:

```powershell
python scripts\physical_validation_campaign.py `
  --mode verify `
  --max-age-hours 168 `
  --min-model-exact 1.0 `
  --report validation\physical-validation-campaign-latest.json
```

Exit codes:

| Exit | Betydning |
|---:|---|
| `0` | Alle krævede beviser og semantic gates er friske, releasebundne og grønne. |
| `1` | Evidens mangler, er stale, mismatched, semantisk utilstrækkelig eller rød. |
| `2` | Identitet eller rapportskrivning kunne ikke bestemmes troværdigt. |

Den samlede autoritative kvittering er:

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

Kontrollér før en senere beslutning, at alle syv evidence statuses i kampagnerapporten
er `pass`, og review version, Git-SHA, worker-fingerprint, alle komponenthashes og
T-032-browserattestationen. Rolling-filer og rå fixtures forbliver lokale. Kun
dateret, manuelt reviewet evidens må committes. En senere aktivering kræver fortsat
en særskilt eksplicit beslutning.
