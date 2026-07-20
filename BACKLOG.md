# ModelRig / Kaliv — Backlog

> ## Tilstand står IKKE her
>
> **Aktuel tilstand:** [`CURRENT_STATE.md`](CURRENT_STATE.md) og
> [`ACTIVATION_READINESS.md`](ACTIVATION_READINESS.md). De genereres fra koden
> og kan ikke tage fejl om, hvad der er på `main`. Denne fil er en **plan** — hvad
> der er tilbage, hvem der ejer det, og hvad der afhænger af hvad.

Afledt af den strategiske analyse (1.58.107) og `09_TASK_REGISTER.md`.
Rækkefølgen følger `ROADMAP.md`: **Prove → Scheduler → Agent 3-pilot →
Capabilities → Product**.

De 26 reelt åbne tasks er importeret som GitHub-issues **#63–#88**. Da den
forbundne GitHub-integration ikke kan oprette GitHubs milestone-objekter, bruges
fem tracker-issues som den aktive styringsflade: **#58–#62**. Tracker-issues har
autoritative checklister; denne fil bevarer task-id, rækkefølge og afhængigheder.

**Ejerskab-legende:**

- **[RIG]** kræver den fysiske Windows-rig
- **[DEVICE]** kræver Pixel 6a / fysisk klientverifikation
- **[ANDERS]** kræver Anders' beslutning
- **[ISO]** kan laves uden rig/device og uden at aktivere produktionsfunktioner
- **[KERNE]** rører worker/backend/scheduler og må ikke laves under en
  validation-frys, medmindre ændringen er en dokumenteret blocker

---

## Milepæl 1 — Prove (frys og bevis) — tracker #58

Intet i senere milepæle promoveres, før denne er grøn. Det manglende arbejde er
nu fysisk evidens — ikke mere dormant hærdning.

| Task | Issue | P | Ejerskab | Afhænger af | Accept |
|---|---:|---|---|---|---|
| T-001 Frys en validation candidate | — | P0 | [ISO] ✅ gjort | — | Exact SHA/tag valgt; kun validation blockers merges. `freeze_check.py` bekræfter. |
| T-004 Kør `rig_preflight.py` | #63 | P0 | [RIG] (JSON-bevis [ISO] ✅) | T-001 | Exit 0 eller dokumenteret blocker. |
| T-005 Kør fuld Agent 3 appliance-validation | #64 | P0 | [RIG] | T-001, T-004 | Frisk report matcher version + code SHA. |
| T-006 Bevis reboot, supervisor, updater, rollback | #65 | P0 | [RIG] (schema/kampagne [ISO] ✅) | T-001, T-004 | reboot→ready, kill→restart, bad update→rollback. |
| T-007 Frys lokal model-eval baseline | #66 | P1 | [RIG] (harness [ISO] ✅) | T-001 | 30–50 tasks med success, latency og tool-discipline. |
| T-040 20-turn voice-kvalitetsbaseline | #67 | P1 | [RIG] (harness [ISO] ✅) | T-001, T-004 | TTFA, WER, cold/warm, stop og barge-in målt. |
| T-043 RAG load- og kvalitetsbenchmark | #68 | P1 | [RIG] (harness [ISO] ✅) | T-001 | 1k/10k chunks, recall, p50/p95, RAM/VRAM. |

Harnessene til T-007, T-040 og T-043 er versionsbundne og regressions-testede.
Preflight-JSON, lifecycle-schema og den samlede candidate-bound kampagnekontrol er
også leveret isoleret. Kun de faktiske rig-, model-, voice-, device-, update- og
GPU-observationer mangler.

---

## Milepæl 2 — Scheduler (durable execution-truth) — tracker #59

Occurrence-ledger, durable recovery, approval-attribution og fault-injection er
leveret. Det åbne arbejde er UI-kontrakten, tidssemantik, bounded concurrency og
den fysiske pilot.

| Task | Issue | P | Ejerskab | Afhænger af | Accept |
|---|---:|---|---|---|---|
| T-010 Design occurrence-ledger + migration (1.58.116) | — | P0 | [KERNE] ✅ | — | Schema, migration og failure-matrix reviewet. |
| T-011 Atomisk claim + budgetreservation (1.58.116) | — | P0 | [KERNE] ✅ | T-010 | Budgetslot reserveres med claim. |
| T-012 Bind job/audit/outcome/recovery durable (1.58.117) | — | P0 | [KERNE] ✅ | T-010, T-011 | Alle crashpunkter har deterministic terminal/reconcile-state. |
| T-013 Grant-revision og revoke (1.58.120; overlap → T-018) | — | P1 | [KERNE] ✅ | T-010 | Re-check før execution; UI viser in-flight. |
| T-014 Gem approval-receipt attribution (1.58.123) | — | P1 | [KERNE] ✅ | — | Approval/device/tider/revision auditeres. |
| T-015 Fault-injection suite + readiness-gate (1.58.121) | — | P0 | [KERNE] ✅ | T-011, T-012, T-013 | Crash/overlap/budget/revoke/approval E2E-gates. |
| T-016 Udvid Android ToolInfo + filtrér picker | #69 | P1 | [DEVICE] (backend ✅) | — | Unschedulable tools skjules/forklares. |
| T-017 Timezone/DST/misfire-semantik | #70 | P2 | [KERNE] | T-010 | IANA-zone + DST/misfire-tests. |
| T-018 Bounded workers / eksplicit single-flight | #71 | P2 | [KERNE] | T-010, T-012, T-013 | Concurrency-model fault-testet. |
| T-019 Fysisk scheduler-pilot: read + `note_append` | #72 | P0 | [RIG] | T-005, T-006, T-015, T-016 | Begge paths kører, stopper og recoverer. |

---

**Analyse 1.58.123 (19/7):** de to recovery-kanter F-1002 (ukendt-vindue:
attempt-markør, slot beholdes, plan pauses — max_runs kan ikke blive N+1 via
crash) og F-1003 (owner-lease: en levende workers claims kan ikke opgives)
lukket i 1.58.126; F-1004 lukket ved at gaten nu kører 9 prober inkl. begge
kanter, bevist ikke-blinde. F-1005 (hul FROZEN) lukket i 1.58.127. F-1019
lukket 19/7 som docs-commit: SECURITY.md er nu selve trusselsmodellen
(model-output-som-angriber, stående-grant-kæden, F-1006 accepteret-med-
begrundelse) og peger på de genererede sider for tilstand.

**Valideringsplanens fault-liste (19_VALIDERINGSPLAN) foldet ind 19/7:**
punkt 1-6 var allerede dækket af unknown-kæden og lease-suiten; #5
(takeover + ukendt udfald) og #7 (two-process max_runs=1 over flere
cadences) tilføjet som eksplicitte tests i 1.58.128. **#7 fandt en levende
P1:** reserve-at-claim (1.58.116) gjorde refusal-checkets `>=` til en
off-by-one — max_runs=1 kørte ALDRIG, alle planer fik max_runs−1 kørsler;
rettet i 1.58.128 (budget-sandheden bæres nu af claimets
reservations-status). **Opfølgning:** T-019-pilotens bevis skal ind i
kampagne-aggregatoren (`scripts/physical_validation_campaign.py`).
**Lukket 19/7:** skema-spørgsmålet blev besvaret ved måling af
aggregatorens eget mønster (slot → sti → producer → validator +
kandidat-binding); kampagnen har nu et `scheduler_pilot`-slot med
validator, producer (`scheduler_pilot_report.py`, maskin-halvdel læses
live fra workeren, menneske-halvdel via manual-observations som voice)
og cases i kampagne-suiten.
**Gap-analysen 1.58.128 (19/7, snapshot 1c3a978):** Gate A F-1202→F-1206
lukket i 1.58.129 — stop drainer før lease frigives (og frigiver IKKE ved
timeout; TTL er fallback), service-heartbeat fornyer under lange kørsler,
unknown+pause er én transaktion, de tre interleavings er testet og
mutations-dræbt, og pilot-slottet er forensic (v2: pinner
occurrence/job/audit-sekvens/receipt/vindue fra storene). F-1201 (kampagnen)
er fortsat riggens.
**Gitless-rig-blockeren (19/7, fundet ved rig-flow-simulation):** hele
kampagne-værktøjskæden antog en git-klon — freeze_check, candidate_identity
(prepare OG verify) og rig_preflight døde alle på ZIP-workflowet. Lukket i
1.58.131: freeze_check får API-mode + attestationsfil, preflight/aggregatoren
arver den (kæden eksplicit, netværksfri aggregator bevaret), uverificerbar
tree-renhed navngives i stedet for at grønnes.
**Fund fra generalprøve 2 (19/7, sandkasse-Ollama):** (1) Produktions-
entrypointet mountede ALDRIG agent3 — `mount_agent3` fandtes, var suite-
testet via direkte kald, og blev kaldt af ingenting; live-probe svarede 404
med flaget sat. Fixet + wiring-parity-suite i 1.58.131. (2) **model_eval-blockeren LUKKET — og
diagnosen var forkert:** `/plan` → `/plans/{id}/start` ER den dokumenterede
produktions-sti (StartReq's docstring); ruterne boede på planner-routeren,
som `build_router` aldrig inkluderede — samme orphaned-wiring-fejl som
mountet, ét lag nede. 404'eren var wiring, ikke flow; ordinationen
"omlæg produceren til chat→runs" trækkes tilbage (klient-forfattede planer
via POST /runs forbliver F-608-fixturen). Wiring-suiten vendte den
forkerte assertion og kræver nu /plan + /plans/{id}/start til stede.
Smoke-bevist e2e i sandkassen: pair-kode → device-token → backend-proxy →
planner → qwen2.5:0.5b — 1/3 gyldig plan scoret; de to 422'ere
("unsupported top-level fields") er den typede kontrakts fail-closed
afvisning af legetøjsmodellens sjusk, dvs. præcis dét evalen måler.
Fuld skala med qwen3:14b er riggens. (3) RAG-kæden generalprøvet grønt mod ægte
Ollama (producer exit 0, validator-kontrakt ren — kun de forventede
skala-afvigelser); fuld skala er riggens (~80+ min på 1 CPU her).
**Helanalyse-gap-drop mod 1.58.131 (19/7, F-1301..F-1327):** dom "platform-
complete candidate with unproven and partially under-bound promotion
evidence" — bevisapparatet var længere fremme end bevisets egen integritet.
De fire adresserbare P1'er lukket i 1.58.132: **F-1302** runbookens falske
model_eval-blocker fjernet (den forbød at køre et påkrævet slot på basis af
den tilbagetrukne diagnose) + doc-parity-checks i doc-gaten så påstanden
ikke kan gro tilbage. **F-1303** gitless FROZEN binder nu det lokale
ZIP-træ til release-committen fil-for-fil via git/trees-API'et (blob-sha-
sammenligning, truncated→FAIL, extras navngives) — at en release FINDES er
ikke det samme som at VÆRE den. **F-1304** attestationen er v2 med ét delt
modul (`scripts/frozen_attestation.py`) som writer og BEGGE læsere
(campaign+preflight, før: to løsere kopier) håndhæver: strict schema,
version-pin, 24t-freshness (dækker også F-1324/P3), ci=codeql=success, og
offline tamper-evidens via genberegnet worker-fingerprint — fem
forfalsknings-mutationer + ZIP-tamper testet røde. **F-1305** schedulerpilot
v3 er manifest-bundet: §1.6-manifestet pinnes (read: rig_status/{}/every:60/
max 3; write: note_append + ceremonien), komplet inventar i pilotvinduet
(unlisted plan = rød), executed uden claim_id = rød; kampagne-validatoren
kræver vindue+manifest+tomt unlisted. **Freshness (1.58.133):** pilotens
nyeste forensik-tidsstempel skal ligge ≤24t fra rapportens generated_at,
håndhævet i BÅDE producer og kampagne-validator — droppens "historiske
pilot-IDs"-mutation testet rød på begge niveauer. Accepteret rest fra
mutationslisten: recovery-linjens tal kan ikke DB-krydstjekkes ærligt
offline (startup-snapshot ≠ slut-tilstand); linjen kræves fortsat, tallene
attesteres af operatøren. F-1301 (kampagnen) er fortsat riggens.
**Post-133-audit af ps1-kæden (19/7):** harnessens komplette rute-kontrakt
målt mod den mountede tabel (openapi-linsen — app.routes-iteration er blind
for includes) afslørede TREDJE forekomst af orphaned-wiring-klassen:
`build_memory_router` havde nul callere; harnessen kalder POST /memory,
/memory/context-preview og DELETE /memory/{id} → ps1'ens step 1 ville 404'e
på rig-dagen. Mountet i 1.58.134 (mount ejer store + router; dev-runnerne
slanket til genbrug), wiring-suiten kræver trioen.
**Fjerde+femte orphan (1.58.135, samme audit ét ring ud):** Android-appens
egen rute-kontrakt målt mod tabellen — `/capabilities` (en hel skærm) og
replan-preview-flowet (`/runs/{id}/replan-preview` + `/replan-previews/
{id}/apply`) 404'ede i produktion, mens dev-runnernes rigere includes
virkede. Værre: runnerens RIGE planner (plan_store, memory-kontekst,
capability-graph) blev stille skygget af mountens bare planner fra 131 —
first-match-routing gjorde plan-persistens død selv i dev. Mountet ejer nu
HELE surfacen (rig planner + replan-preview + outcome-answer + capability
graph/receipt); runnerne tilføjer intet — dev serverer præcis hvad
produktion serverer. 19→24 mountede stier; wiring-suiten kræver app-
kontrakten (8 checks).
**Helanalyse-gap-drop mod 1.58.133 (20/7, F-1401..F-1431):** dom
"evidence-hardened promotion candidate, still physically unproven" — fem
resterende risici, fire lukket i 1.58.136: **F-1402** extras i gitless
freeze er nu FAIL (før NOTE) — en frisk ZIP har nul; kun validation/,
__pycache__ og *.pyc er sanktionerede mutationer. **F-1403** attestation
v3 med fuldt træ-rollup: freeze registrerer HELE den committede filliste
+ sha256-rollup over blob-sha'er; begge læsere genberegner offline — en
post-freeze-ændring HVOR SOM HELST i træet (ikke kun worker/) afvises ved
navn. **F-1404** write-manifestet er exact (kanonisk pilot-write defineret
i §1.6: note_append/{"text":"pilot"}/every:60/max 2) + receipt bundet til
granten (fingerprint == approved_fingerprint, revision-match). **F-1405**
freshness pr. HALVDEL (en frisk halvdel bærer ikke en gammel), samlet
12t-vindue på tværs, og execution-completeness: occurrences-inventar
fanger foreksisterende planer der fyrer i vinduet. Bonus: **F-1407**
attestationen afviser ukendte felter (exact key set); **F-1426** freeze's
"changes nothing"-docstring rettet; **F-1431** draft-tallet. Pilot-schema
v4, attestation-schema v3, alle mutationer testet røde. F-1401 = riggen.
Krydsvalidering: droppet (133-snapshot) fandt IKKE memory-orphanen eller
app-surface-hullerne — 134/135's kontrakt-mod-tabel-målinger så ting
statisk helanalyse ikke gjorde. P2/P3 fra det NYE drop (F-1406..F-1431: baselines qwen3/RAG/voice, scheduler-tid/grants/concurrency, Android-UX,
capability/data-sharing/research, isolation, memory, updater, merge-tog for
de 19 drafts er parkeret til EFTER kampagnen jf. styringsreglen.

## Milepæl 3 — Agent 3-pilot (mål task success) — tracker #60

Agent 3 er moden i kode, men slukket i produktet. Pilotresultater og fysisk
readiness — ikke mere skjult aktivering — afgør næste skridt.

| Task | Issue | P | Ejerskab | Afhænger af | Accept |
|---|---:|---|---|---|---|
| T-020 Read-only developer-pilot | #73 | P0 | [RIG]/[KERNE] | T-005, T-007 | 20 task-runs, ingen skjult write, instant fallback. |
| T-021 Readiness-gate + normal task-UI | #74 | P1 | [KERNE]/[DEVICE] | T-005, T-006, T-020 | Routing, stop, fallback, receipts og outcomes synlige. |
| T-022 Append-only write-pilot | #75 | P1 | [RIG]/[KERNE] | T-021 | `note_append` 20/20 med korrekt approval/audit. |
| T-023 Cancellation-status + runtime-handles | #76 | P1 | [DEVICE]/[KERNE] | T-020 | UI viser den faktiske afslutningssemantik. |

---

## Milepæl 4 — Capabilities (bredde efter bevis) — tracker #61

Nye connectors og scopes bygges gennem ét fælles schema og én data-sharing-policy.
Research-forarbejdet er merged, men forbliver dormant indtil de resterende gates.

| Task | Issue | P | Ejerskab | Afhænger af | Accept |
|---|---:|---|---|---|---|
| T-030 Fælles versioneret capability-schema v2 | #77 | P1 | [KERNE] (adapter-isolerbar) | — | Schema driver gates, API, klienter og docs uden automatisk aktivering. |
| T-031 Validér Windows isolation I0b | #78 | P1 | [RIG] | T-030, T-005 | Rettigheder, workspace, netværk, lifecycle og cleanup fysisk bevist. |
| T-032 Fælles data-sharing policy for cloud-read | #79 | P0 | [KERNE] + [ANDERS] | — | Én scoped policy/receipt-model i v2 + Agent 3. |
| T-033 Beskyt følsomme Agent 3 memory-felter | #80 | P1 | [RIG] (format [ISO]) | T-030 | Værdier ulæselige i DB/backups; restore testet på Windows. |
| T-034 Web/research med citations | #81 | P1 | [KERNE] | T-030, T-032 | Peer-binding, citations, receipt, audit og eval. |
| T-035 Scoped file-capabilities | #82 | P1 | [KERNE]/[RIG] | T-030, T-031 | Explicit workspace og adversarial path-tests. |
| T-036 GitHub read-only connector-pilot | #83 | P1 | [KERNE] (afgrænset) | T-030, T-032 | Scoped read-pilot med revisionsgrunding og audit. |
| T-037 Google/Notion read-first connector-pakke | #84 | P2 | [KERNE] | T-030, T-032, T-036 | Separate scopes, read-first rollout og revocation. |
| T-038 RigGate/Home Assistant read-only pilot | #85 | P2 | [KERNE] (afgrænset) | T-030, T-032 | Status og wake-preview uden side effect. |

---

## Milepæl 5 — Product (den oplevede assistent) — tracker #62

| Task | Issue | P | Ejerskab | Afhænger af | Accept |
|---|---:|---|---|---|---|
| T-041 Streaming ASR + latency-optimering | #86 | P2 | [KERNE]/[DEVICE] | T-040 | Målt forbedring uden WER/cleanup-regression. |
| T-042 Mundtlig tool-confirmation | #87 | P2 | [KERNE]/[DEVICE] | T-022, T-040 | Repeat-back, approve/deny, timeout=denial og audit. |
| T-044 Kaliv Control Center | #88 | P1 | [DEVICE]/[KERNE] | T-020, T-016, T-032 | Én normal health/routing/privacy/permissions/jobs/audit-flade. |

---

## Styring (løbende, isoleret)

| Task | Status | Resultat |
|---|---|---|
| T-002 Luk PR #1, #3, #36 | ✅ 19/7-2026 | Alle tre er closed med konkret superseded/inspection-note. |
| T-003 Importér registeret til GitHub | ✅ 19/7-2026 | Tracker-issues #58–#62 og åbne task-issues #63–#88 er oprettet og assigned. GitHub milestone-objekter er valgfri manuel pynt; tracker-issues er den aktive styringsflade. |

---

*Vedligeholdelse: når en task lukkes, markeres issue og tracker-checklist. Sand
tilstand af koden er altid `CURRENT_STATE.md`; GitHub-issues og denne fil beskriver
plan og fysisk evidens.*
