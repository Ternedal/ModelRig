# Physical validation campaign — én kandidat, ét samlet bevis

Denne runbook samler de syv fysiske **Prove**-opgaver T-004, T-005, T-006,
T-007, T-040, T-043 og T-019. De enkelte harnesses har fortsat deres egne
detaljerede
runbooks; denne kampagne sørger for, at deres rapporter faktisk beskriver den
samme version, Git-commit og worker-kode.

> **Scope:** Dette er Stage B's fulde releasekampagne. En upubliceret kandidat
> starter i [`STAGED_PHYSICAL_PROMOTION.md`](STAGED_PHYSICAL_PROMOTION.md), hvor
> seks ikke-releasebundne beviser og T-032-browserbeviset samles først. T-006
> lifecycle kan først bevises, når samme SHA er publiceret som en nyere release.

`scripts/physical_validation_campaign.py` er read-only. Det starter ikke
services, bruger ingen token, udfører ingen update/reboot og ændrer ingen
featureflag. Det læser lokale JSON-rapporter, validerer dem og skriver én atomisk
kampagnerapport med `production_activation=false`.

## Hvorfor aggregatoren er nødvendig

En grøn Agent 3-rapport fra commit A, en voice-baseline fra commit B og en
RAG-måling fra commit C er ikke en valideret kandidat. Kampagnen kræver:

- samme `VERSION`;
- samme 40-tegns Git-SHA, hvor rapporttypen understøtter den;
- samme worker `code_sha256`, hvor rapporten måler runtime-koden;
- friske, timezone-aware timestamps;
- grønne individuelle gates og cleanup-resultater;
- komplette typed observations for reboot, supervisor, update og rollback.

## Kandidat-checkout må ikke flytte sig under kampagnen

Kør alle faser fra den samme rene checkout af den valgte candidate. Før første
fase:

```powershell
git status --short
git rev-parse HEAD
Get-Content VERSION
```

`git status --short` skal være tom. Gem SHA’en, og skift ikke branch, pull ikke
nye commits og redigér ikke tracked filer mellem faserne. Rolling reports og WAV-
fixtures er ignorerede arbejdsfiler og gør ikke checkoutet dirty. Hvis HEAD
ændres, er den tidligere evidens ikke længere en samlet kampagne og skal køres
igen mod den nye kandidat.

## 0. Frys den publicerede release og opret releasechecklisten

Denne sektion er Stage B. Kør først Stage A i `STAGED_PHYSICAL_PROMOTION.md`,
og fortsæt kun efter exact-SHA fast-forward, tag og offentlig release.

```powershell
python scripts\freeze_check.py
python scripts\physical_validation_campaign.py `
  --mode prepare `
  --report validation\physical-validation-campaign-latest.json
```

`freeze_check.py` kræver, at HEAD er præcis det publicerede `v{VERSION}`-tag,
at releasen ikke er draft, at SHA'en er på `origin/main`, og at exact-head
`ci` samt `codeql` er grønne. På en gitless release-ZIP verificerer den det
lokale træ mod release-committen og skriver `validation\frozen-candidate.json`.

`prepare` accepterer manglende fremtidige rapporter, men stale, røde eller
candidate-mismatched rapporter blokerer.

## 1. T-004 — rig preflight

```powershell
python scripts\rig_preflight.py `
  --base-url http://127.0.0.1:8080 `
  --report validation\rig-preflight-latest.json
```

Rapporten indeholder kandidatens version, Git-SHA og worker-fingerprint samt
alle checks som typed `ok`/`warn`/`fail`. Device-tokenet bliver aldrig skrevet.
Kampagnen accepterer warnings i den normale “ingen validation report endnu”
tilstand, men ingen failed checks.

## 2. T-005 — Agent 3 appliance-evidens

Følg `AGENT3_RIG_VALIDATION.md` og kør wrapperen med et eksplicit lokalt
planner-modelnavn. Den forventede fil er:

```text
validation/agent3-rig-validation-latest.json
```

Kampagnen genbruger den eksisterende Agent 3 validation-gate og kræver:

- `success=true`;
- backend/worker-version lig kandidaten;
- worker `code_sha256` lig kandidatens fingerprint;
- fuld cleanup;
- eligibility for developer preview;
- `production_activation=false`.

## 3. T-007 — plan-only model-eval

Forudsætninger: `MODELRIG_TOKEN` (paired device-token) i miljøet,
`KALIV_AGENT3_ENABLED=1` på BÅDE backend og worker, og backend'en kørende —
produceren taler backend-dialekt (`/api/v1/...`) mod `--base-url`
(default `http://127.0.0.1:8080`).

```powershell
python scripts\agent3_model_eval.py `
  --planner-model <MODEL> `
  --repetitions 1 `
  --fail-under 1.0 `
  --report validation\agent3-model-eval-latest.json
```

Standardkampagnen kræver exact-match rate `1.0`, discipline rate `1.0`, ingen
request errors, `starts_plans=false` og `executes_tools=false`. En lavere,
bevidst accepteret modelgrænse kan kun bruges eksplicit ved kampagneverify:

```powershell
--min-model-exact 0.95
```

Grænsen skal være dokumenteret; den må ikke sænkes blot for at få en grøn fil.

## 4. T-006 — reboot, supervisor, updater og rollback

> **Kun Stage B:** updaterens gyldige update kræver, at kandidaten er den
> nyeste offentlige release og har en højere semver end den kørende rig. Kør
> aldrig denne del mod en upubliceret branch eller ved manuel binærkopiering.

Kopiér den versionerede skabelon:

```powershell
Copy-Item `
  eval\appliance_lifecycle_observations.example.json `
  validation\appliance-lifecycle-observations.json
New-Item -ItemType Directory `
  validation\appliance-lifecycle-evidence `
  -Force | Out-Null
```

Udfyld kandidat/host/timestamps og fem trials:

1. normal reboot → backend og worker ready;
2. backend supervisor-restart;
3. worker supervisor-restart;
4. gyldig update fra en tidligere build til kandidaten;
5. ugyldig update, som afvises eller rulles tilbage til kandidaten.

Hver trial skal have sin egen lokale evidensfil under:

```text
validation/appliance-lifecycle-evidence/
```

Gem eksempelvis konsoludskrift, health-tidslinje eller updater/supervisor-log i
filen. Udfyld trialens repository-relative `evidence_path`, og beregn den hash,
som skrives i `evidence_sha256`:

```powershell
(Get-FileHash `
  validation\appliance-lifecycle-evidence\reboot.log `
  -Algorithm SHA256).Hash.ToLowerInvariant()
```

Kampagnen genlæser hver fil, kræver en almindelig ikke-tom fil på højst 32 MiB,
forbyder symlinks og paths uden for den allowlistede mappe og sammenligner den
faktiske SHA-256 med JSON-feltet. En ændret log gør hele verify-gaten rød.
Artifactindholdet kopieres ikke ind i kampagnerapporten; den gemmer path, hash og
byteantal.

Alle boolske felter skal være ægte JSON-booleans. Tider skal være tal i
millisekunder. `good_update.target_*`, reboot/supervisor identity og
`bad_update.active_*` skal matche kandidaten. Den gyldige updates source-version
og source-SHA skal være anderledes end kandidatens. Den ugyldige updates attempted
Git-SHA skal også være anderledes end kandidatens. Data og schedules skal være
bevaret i begge update-trials.

Skabelonen er bevidst rød (`false`, `null`, `FILL_ME`) indtil de fysiske
observationer og deres artifact-hashes er gennemført.

## 5. T-040 — voice baseline

Følg `VOICE_BASELINE.md`. Den forventede fil er:

```text
validation/voice-baseline-latest.json
```

Kampagnen kræver grøn top-level gate, 0 errors, completed cold probe, alle
connection-cancellation-prober og en bestået typed Pixel stop/barge-in-matrix.

## 6. T-043 — RAG baseline

Følg `RAG_BENCHMARK.md`. Den forventede fil er:

```text
validation/rag-benchmark-latest.json
```

Kampagnen kræver præcis 1.000 og 10.000 chunks, grøn benchmark-gate, 0 errors og
clean source removal for begge skalaer.

> **Rettet 19/7 (blockeren var en fejldiagnose):** `/plan` →
> `/plans/{id}/start` ER den dokumenterede produktionssti; ruterne var
> orphanede på planner-routeren og er wiret fra 1.58.131. Produceren er
> uændret og skal køres. Smoke-bevist e2e i sandkassen (pair → token →
> backend → planner → Ollama). Får du 422 "unsupported top-level fields"
> er det den typede kontrakts fail-closed afvisning af modellens output —
> et ægte eval-fund, ikke en kædefejl (se TROUBLESHOOTING).

## 7. T-019 — scheduler-pilot (read + `note_append`)

Kør runbooken i `DEVICE_TEST.md` sektion 1.6 (read-plan via loopback, write-plan
med den fulde godkendelses-ceremoni, pausen mid-flight, crash-recovery). Notér
de to schedule-id'er, recovery-linjen fra worker-loggen, og skriv den lille
manual-observations-fil:

```json
{"revocation_confirmed": true,
 "recovery_line": "scheduler: recovered 0 executed / 1 abandoned / 0 unknown occurrence(s) at startup",
 "operator": "Anders"}
```

Producér derefter evidensen (maskin-halvdelen læses live fra workeren:
receipts, budgetter, read-uden-approval; menneske-halvdelen er dine to
observationer):

```cmd
python scripts\scheduler_pilot_report.py --read-schedule-id <ID> --write-schedule-id <ID> --manual-observations validation\scheduler-manual-observations.json --report validation\scheduler-pilot-latest.json
```

Produceren fælder selv dom (`pilot.passed`) og skriver rapporten uanset —
aggregatoren genvaliderer alt mod den frosne kandidat.

**Forensik (v2):** rapporten pinner det *konkrete* forløb direkte fra storene
(read-only): schedule-rækken (tool/args/cadence/budget), hver occurrence med
claim_id, status, job og audit-sekvens (`attempt` → `executed`), receipt-rækken
og tidsvinduet. Pausens bevis er en `released`-occurrence bundet til et
`cancelled` job. Kør produceren fra workerens arbejdsmappe, eller peg
`--schedules-db`/`--jobs-db`/`--audit-db` på dens filer — aggregater tæller,
forensikken beviser.

## 8. Verificér hele kampagnen

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
| `0` | I `verify`: alle syv fysiske beviser er present, friske, candidate-bound og grønne. |
| `1` | En rapport mangler, er stale, mismatched eller har en rød individuel gate. |
| `2` | Kampagneværktøjet kunne ikke bestemme kandidat eller skrive en troværdig rapport. |

`gate.physical_campaign_complete=true` er den eneste kampagnestatus, der betyder
at alle fysiske beviser er samlet. `prepare` kan have `gate.passed=true`, men vil
altid have `physical_campaign_complete=false`, så længe en rapport mangler.

## Permanent evidens

Når `verify` er grøn og rapporten er manuelt reviewet:

```powershell
Copy-Item `
  validation\physical-validation-campaign-latest.json `
  validation\physical-validation-campaign-2026-07-XX.json
```

Kontrollér før commit:

- candidate version, Git-SHA og code fingerprint;
- alle syv evidence statuses er `pass`;
- ingen `missing`, `failed` eller `candidate_errors`;
- hver rapport- og lifecycle-artifact-SHA er udfyldt;
- `physical_campaign_complete=true`;
- `production_activation=false`.

Rolling-filer, lifecycle-arbejdsfilen, lifecycle-artifacts, rå voice-fixtures og
manuelle work files forbliver lokale. Kun dateret, manuelt reviewet evidens må
committes.
