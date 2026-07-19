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
