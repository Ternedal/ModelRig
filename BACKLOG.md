# ModelRig / Kaliv — Backlog

> ## Tilstand står IKKE her
>
> **Aktuel tilstand: [`CURRENT_STATE.md`](CURRENT_STATE.md) og
> [`ACTIVATION_READINESS.md`](ACTIVATION_READINESS.md).** De genereres fra koden
> og kan ikke tage fejl om hvad der er på main. Den her fil er en **plan** — hvad
> der er tilbage, hvem der ejer det, og hvad der hænger på hvad. Den beskriver
> ikke hvad systemet ER.

Afledt af den strategiske analyse (1.58.107), `09_TASK_REGISTER.md`. Rækkefølgen
følger `ROADMAP.md`: **Prove → Scheduler → Agent 3-pilot → Capabilities →
Product**. Analysen fandt at der ikke fandtes en aktiv backlog (F-918); det her
er den, indtil den evt. importeres som GitHub-milestones/issues.

**Ejerskab-legende:**
- **[RIG]** kræver den fysiske Windows-rig — kan ikke laves solo i en session
- **[DEVICE]** kræver Pixel 6a — Android/klient-verifikation
- **[ANDERS]** kræver Anders' adgang (fx PR-lukning) eller beslutning
- **[ISO]** isoleret; kan laves uden rig/device og uden at kollidere med
  scheduler-kernen — men skær **ikke** en release under en frys
- **[KERNE]** rører den validerede appliance-kerne (worker/backend/scheduler) —
  **må ikke laves under en frys**, kun validation blockers

---

## Milepæl 1 — Prove (frys og bevis)

Intet nedenfor i senere milepæle promoveres før denne er grøn. Fysisk bevis er
3.2/10; det er den ene ting der låser resten op.

| Task | P | Ejerskab | Afhænger af | Accept |
|---|---|---|---|---|
| T-001 Frys en validation candidate | P0 | [ISO] ✅ gjort | — | Exact SHA/tag valgt; kun validation blockers merges. `freeze_check.py` bekræfter. |
| T-004 Kør `rig_preflight.py` | P0 | [RIG] | T-001 | Exit 0 eller dokumenteret blocker. |
| T-005 Kør fuld Agent 3 appliance-validation | P0 | [RIG] | T-001, T-004 | Frisk report matcher version + code SHA. |
| T-006 Bevis reboot, supervisor, updater, rollback | P0 | [RIG] | T-001, T-004 | reboot→ready, kill→restart, bad update→rollback. |
| T-007 Frys lokal model-eval baseline | P1 | [RIG] (harness [ISO] ✅ leveret) | T-001 | 30–50 tasks med success, latency, tool-discipline. |
| T-040 20-turn voice-kvalitetsbaseline | P1 | [RIG] | T-001, T-004 | TTFA, WER, cold/warm, stop, barge-in målt. |
| T-043 RAG load- og kvalitetsbenchmark | P1 | [RIG] (harness [ISO] ✅ leveret) | T-001 | 1k/10k chunks, recall, p50/p95, RAM/VRAM. |

**Isoleret forarbejde er leveret:** harnessene til T-007 og T-043 er nu
versionsbundne, regressions-testede og klar til riggen. Kun de faktiske lokale
model-/GPU-målinger mangler; de kan ikke bevises af CI eller en ekstern runner.

---

## Milepæl 2 — Scheduler (durable execution-truth)

Analysens vigtigste tekniske blocker. Flowet er stadig
`claim/due_at commit → in-memory claim → JobStore → ToolGate → runs_used` — et
crash i mellemrummet kan miste eller gentage en write. **Alt her er [KERNE]** og
ligger i Anders' aktive filer; må ikke laves under frysen, og kræver koordination
for ikke at kollidere.

| Task | P | Ejerskab | Afhænger af | Accept |
|---|---|---|---|---|
| T-010 Design occurrence-ledger + migration (leveret i 1.58.116) | P0 | [KERNE] | — | Schema, migration, failure-matrix reviewet. |
| T-011 Atomisk claim + budgetreservation (leveret i 1.58.116) | P0 | [KERNE] | T-010 | Budgetslot reserveres med claim. |
| T-012 Bind job/audit/outcome/recovery durable (leveret i 1.58.117) | P0 | [KERNE] | T-010, T-011 | Alle crashpunkter har deterministic terminal/reconcile-state. |
| T-013 Grant-revision, revoke, overlap-policy (leveret i 1.58.120; overlap → T-018) | P1 | [KERNE] | T-010 | Re-check før execution; UI viser in-flight. |
| T-014 Gem approval-receipt attribution (leveret i 1.58.123; renew bumper nu også revision) | P1 | [KERNE] (afgrænset) | — | Approval/device/tider/revision auditeres. |
| T-015 Fault-injection suite + readiness-gate (leveret i 1.58.121) | P0 | [KERNE] | T-011, T-012, T-013 | Crash/overlap/budget/revoke/approval E2E-gates. |
| T-016 Udvid Android ToolInfo + filtrér picker | P1 | [DEVICE] (backend ✅) | — | Unschedulable tools skjules/forklares. Backend-kontrakten findes allerede (F-823). |
| T-017 Timezone/DST/misfire-semantik | P2 | [KERNE] | T-010 | IANA-zone + DST/misfire-tests. |
| T-018 Bounded workers / eksplicit single-flight | P2 | [KERNE] | T-010, T-012, T-013 | Concurrency-model fault-testet. |
| T-019 Fysisk scheduler-pilot: read + `note_append` | P0 | [RIG] | T-005, T-006, T-015, T-016 | Begge paths kører, stopper, recoverer. |

---

## Milepæl 3 — Agent 3-pilot (mål task success)

Agent 3 er moden i kode men slukket i produktet (flaget er off). Kør en rigtig
pilot og mål udfald frem for at bygge mere dormant hardening.

| Task | P | Ejerskab | Afhænger af | Accept |
|---|---|---|---|---|
| T-020 Read-only developer-pilot | P0 | [RIG]/[KERNE] | T-005, T-007 | 20 task-runs, ingen skjult write, instant fallback. |
| T-021 Promotion-gate + normal task-UI | P1 | [KERNE]/[DEVICE] | T-005, T-006, T-020 | Routing, stop, fallback, receipts, outcomes synlige. |
| T-022 Append-only write-pilot | P1 | [RIG]/[KERNE] | T-021 | `note_append` 20/20 med korrekt approval/audit. |
| T-023 Cancellation-UX + handles | P1 | [DEVICE] (UI [ISO]) | T-020 | UI viser none/cooperative/forceable; reel stop kræver per-tool handles. |

---

## Milepæl 4 — Capabilities (bredde, efter bevis)

Kun ni tools i produktion i dag (capability-bredde 2.2/10). Byg bredde **efter**
kernen er bevist, gennem én descriptor og en egress-beslutning først.

| Task | P | Ejerskab | Afhænger af | Accept |
|---|---|---|---|---|
| T-030 Canonical CapabilityDescriptor v2 | P1 | [KERNE] (adapter-isolerbar) | — | Descriptor driver gates, API, docs. |
| T-031 Bevis Windows process-isolation I0b | P1 | [RIG] | T-030, T-005 | Restricted token, Job Object, ACL, network-deny, kill-test. |
| T-032 Beslut + implementér private cloud-read egress | P0 | [KERNE] + beslutning | — | Én consent/receipt-model i v2 + Agent 3. |
| T-033 Krypter Agent 3 secret memory at-rest | P1 | [RIG] (envelope [ISO]) | T-030 | Secret values ulæselige i DB; backup/restore testet. DPAPI kræver Windows. |
| T-034 Web/research med citations | P1 | [KERNE] | T-030, T-032 | Scoped search/fetch, citations, audit, eval. |
| T-035 Scoped file-capabilities | P1 | [KERNE]/[RIG] | T-030, T-031 | Allowlisted workspace + traversal/symlink-tests. |
| T-036 GitHub connector/MCP-pilot | P1 | [KERNE] (afgrænset) | T-030, T-032 | Read-first; writes med exact confirmation. |
| T-037 Google/Notion connector-pakke | P2 | [KERNE] | T-030, T-032, T-036 | Read-first rollout; writes separat + revocable. |
| T-038 RigGate/Home Assistant read-only pilot | P2 | [KERNE] (afgrænset) | T-030, T-032 | Status/wake-preview med audit. |

---

## Milepæl 5 — Product (den oplevede assistent)

| Task | P | Ejerskab | Afhænger af | Accept |
|---|---|---|---|---|
| T-041 Streaming ASR + latency-optimering | P2 | [KERNE]/[DEVICE] | T-040 | Målt forbedring uden WER/cleanup-regression. |
| T-042 Mundtlig tool-confirmation | P2 | [KERNE]/[DEVICE] | T-022, T-040 | Repeat-back + approve/deny; timeout=denial; audit. |
| T-044 Kaliv Control Center | P1 | [DEVICE]/[KERNE] | T-020, T-016, T-032 | Én normal health/routing/privacy/permissions/jobs/audit-flade. |

---

## Styring (løbende, isoleret)

| Task | P | Ejerskab | Accept |
|---|---|---|---|
| T-002 Luk PR #1, #3, #36 | P1 | [ANDERS] | Lukket med superseded/inspection-note. (Session fik 403 på PR-operationer.) |
| T-003 Milestones + issues fra registeret | P0 | [ISO]/[ANDERS] | Milestones: Prove, Scheduler, Agent 3-pilot, Capabilities, Product. Denne fil er første skridt; GitHub-import kræver Anders' adgang. |

---

*Vedligeholdelse: når en task lukkes, flyt den ikke — markér ejerskab/accept
opdateret. Sand tilstand af koden er altid `CURRENT_STATE.md`, ikke denne fil.*
