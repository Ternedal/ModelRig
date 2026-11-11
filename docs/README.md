# Dokumentation i `docs/`

Indeks over alle dokumenter i `docs/`, grupperet efter område. Hver linje er
taget fra dokumentets egen titel eller indledning. Statuskategorien står kun,
hvor dokumentet selv angiver den eller den følger entydigt af indholdet:
*levende reference*, *runbook*, *beslutning (ADR)*, *evidens*, *forslag* eller
*historisk*. Ingen kategori betyder, at dokumentet ikke selv siger det.

Repository-tilstand står ikke her. Den aktuelle tilstand genereres i
[`CURRENT_STATE.md`](../CURRENT_STATE.md) og
[`ACTIVATION_READINESS.md`](../ACTIVATION_READINESS.md); udgivelser står under
GitHub Releases.

## System

- [KALIV_SYSTEM_DEFINITION.md](KALIV_SYSTEM_DEFINITION.md) — systemdefinitionen: kanonisk produktdefinition og helsystem-arkitektur. *Levende reference.*
- [consciousness-core/](consciousness-core/) — Consciousness Core: arkitektur og slice-dokumenter (eget indeks i mappen).
- [devcontrol/](devcontrol/DEVCONTROL_ARCHITECTURE_DECISIONS.md) — DevControl: det komplette indeks over DevControl-beslutninger.

## Release og kvalifikation

- [KALIV_SYSTEM_RELEASE_QUALIFICATION.md](KALIV_SYSTEM_RELEASE_QUALIFICATION.md) — Kaliv system release qualification: exact repository pins plus uafhængig fysisk evidens; manifest, gates og binding af Consciousness-evidens.
- [KALIV_SOFTWARE_EXACT_GREEN_QUALIFICATION.md](KALIV_SOFTWARE_EXACT_GREEN_QUALIFICATION.md) — evidens for `software_exact_green`-gaten via `scripts/kaliv_software_exact_green_qualifier.py`.
- [KALIV_REPOSITORY_AUTHORITY_QUALIFICATION.md](KALIV_REPOSITORY_AUTHORITY_QUALIFICATION.md) — evidens for `repository_authority`-gaten via `scripts/kaliv_repository_authority_qualifier.py`.
- [KALIV_END_TO_END_LATENCY_QUALIFICATION.md](KALIV_END_TO_END_LATENCY_QUALIFICATION.md) — evidens for `end_to_end_latency`-gaten via `scripts/kaliv_end_to_end_latency_qualifier.py`.
- [KALIV_V1_RIG_SMOKE.md](KALIV_V1_RIG_SMOKE.md) — read-only readiness-diagnostik for riggen (checkout, backend/worker, ASR/TTS); ikke fysisk accept. *Runbook.*
- [RELEASE_TEST_2.0.14.md](RELEASE_TEST_2.0.14.md) — operatørens testvej for den første integrerede 2.0.14-kandidat. *Historisk.*
- [release/V1_EVIDENCE_TRUST_BOUNDARY.md](release/V1_EVIDENCE_TRUST_BOUNDARY.md) — operatørnote om hvad den eksisterende release-gate validerer, og hvad den ikke beviser.
- [release/KALIV_RELEASE_ACCEPTANCE_MATRIX_2026-10-16.md](release/KALIV_RELEASE_ACCEPTANCE_MATRIX_2026-10-16.md) — planlægnings- og evidensskabelon for release-accept, baseline 16/10-2026. *Historisk.*
- [PERFORMANCE_EXPERIMENT_CONVERGENCE_20261012.md](PERFORMANCE_EXPERIMENT_CONVERGENCE_20261012.md) — planlægnings- og evidensoversigt over performance-eksperimenter, 12/10-2026. *Historisk.*
- [audits/MODELRIG_REPOSITORY_AUDIT_2026-10-16.md](audits/MODELRIG_REPOSITORY_AUDIT_2026-10-16.md) — statisk repository-inventar og målrettet filgennemgang af `main`, 16/10-2026.

## Fysisk accept og drift på riggen

- [T044_CONTROL_CENTER_PHYSICAL_ACCEPTANCE.md](T044_CONTROL_CENTER_PHYSICAL_ACCEPTANCE.md) — manuel accept-evidens for Control Center på fysisk enhed (issue #88). *Runbook.*
- [T038_HOME_ASSISTANT_LIVE_READ.md](T038_HOME_ASSISTANT_LIVE_READ.md) — T-038: samtykket, read-only live-læsning af Home Assistant; hvad fixture-evidensen beviser, og hvordan live-læsningen køres. *Runbook.*
- [T038_WINDOWS_TOKEN_ACL_DESIGN.md](T038_WINDOWS_TOKEN_ACL_DESIGN.md) — design for Windows-ACL-tjek af credential-filer (`credential_acl*.py`, `credential_file.py`).
- [VOICE_RUNTIME_PREFLIGHT.md](VOICE_RUNTIME_PREFLIGHT.md) — read-only diagnostik af den kørende workers ASR/TTS-runtime.
- [VOICE_STARTUP_RECOVERY.md](VOICE_STARTUP_RECOVERY.md) — opstartsgrace for den frosne voice-worker, updaterens readiness-vindue og opgradering fra den gamle updater.
- [OLLAMA_LOCAL_INFERENCE_BENCHMARK.md](OLLAMA_LOCAL_INFERENCE_BENCHMARK.md) — opt-in, afgrænset lokal timing-probe for Ollama-inferens.
- [OLLAMA_LOCAL_PERFORMANCE_DIAGNOSTIC.md](OLLAMA_LOCAL_PERFORMANCE_DIAGNOSTIC.md) — read-only diagnostik af reel token-genereringshastighed (ikke Stage-B CI-hastighed).

## Medier (#2296)

- [MEDIA_GENERATION_PROFILES.md](MEDIA_GENERATION_PROFILES.md) — generator-siden: modelprofiler og GPU-lease. Default-off.
- [MEDIA_EXECUTOR.md](MEDIA_EXECUTOR.md) — media-executoren (G2): proces pr. GPU, exit-koder og supervisorens politik. Default-off.
- [MEDIA_VIDEO_GENERATION.md](MEDIA_VIDEO_GENERATION.md) — videogenerering via ComfyUI: supervisor, adapter, staged video sink, template- og pin-regler. Default-off.
- [MEDIA_VOLUME.md](MEDIA_VOLUME.md) — den verificerede medievolumen (G1), hvor genererede medier publiceres; operatøropsætning og checks.

## Krop (BodyRig)

- [BODYRIG_AUTHORITY.md](BODYRIG_AUTHORITY.md) — ADR-BODYRIG-001: standalone `Ternedal/BodyRig` er produkt- og kontraktautoritet. *Beslutning (ADR).*
- [MRBODY_SPEC.md](MRBODY_SPEC.md) — `.mrbody` v1: versioneret, data-only ZIP-container for en krop/avatar-profil.
- [BODYRIG_V1.md](BODYRIG_V1.md) — BodyRig V1: virtuel embodiment for ModelRig, oprindelig ModelRig-side designnote. *Historisk.*
- [bodyrig/README.md](bodyrig/README.md) — BodyRig-integration i ModelRig: ansvarsgrænse og hvad mappen indeholder.
- [bodyrig/FIRST_LIVE_BODY.md](bodyrig/FIRST_LIVE_BODY.md) — den første levende krop: Unity-gate, Android live-body og fysisk qualification. *Runbook.*
- [bodyrig/UNITY_RENDERER_ROADMAP.md](bodyrig/UNITY_RENDERER_ROADMAP.md) — Unity/UniVRM-rendereren fra proof til produkt (Anders 2/9-2026). *Beslutning (ADR).*
- [bodyrig/KALIV_EMBEDDED_RENDERER.md](bodyrig/KALIV_EMBEDDED_RENDERER.md) — kroppen i Kaliv: lagene L1–L4 og valget af MVP-vært (taget 4/9-2026). *Beslutning (ADR).*
- [bodyrig/VOICERIG_COMPAT.md](bodyrig/VOICERIG_COMPAT.md) — den VoiceRig-kontrakt, der blev inspiceret under BodyRig M0.2 (snapshot af en pinnet kandidat). *Evidens.*
- [bodyrig/SPEC.md](bodyrig/SPEC.md) — BodyRig System Specification v0.1. *Historisk.*
- [bodyrig/BODYPRINT.md](bodyrig/BODYPRINT.md) — `.bodyprint`-pakkespecifikation v0.1. *Historisk.*
- [bodyrig/PROTOCOL.md](bodyrig/PROTOCOL.md) — BodyRig Runtime Protocol v0.1. *Historisk.*
- [bodyrig/ROADMAP.md](bodyrig/ROADMAP.md) — den oprindelige BodyRig-roadmap (M0 ff.). *Historisk.*
- `bodyrig/schemas/` — JSON Schema-kontrakter (v0.1: bodyprint-manifest, cancel-event, expression-plan, render-frame, runtime-state, state-event; tracking v1), som CI læser.

## Personer og hukommelse

- [PERSON_PROFILE.md](PERSON_PROFILE.md) — Person Profile (#752): den fælles kontrakt for personer med versionsstyrede body-, voice- og personality-komponenter.
- [memory/MEMORY_4_CLOSURE.md](memory/MEMORY_4_CLOSURE.md) — Memory 4.0: den autoritative landede status med PR'er, commits og flag. *Levende reference.*
- [memory/MEMORY_4.md](memory/MEMORY_4.md) — Memory 4.0: delt retrieval og normal-chat-integration; designhistorik for R01–R05 og W01–W02. *Historisk.*
- [memory/MEMORY_4_W02.md](memory/MEMORY_4_W02.md) — W02: autoritetssikker konsolidering og durable writes.
- [memory/MEMORY_4_PROTECTED_EXACT_LOOKUP.md](memory/MEMORY_4_PROTECTED_EXACT_LOOKUP.md) — beskyttet verbatim exact-match-sidecar (#1218).
- [memory/MEMORY_4_W03.md](memory/MEMORY_4_W03.md) — W03: afgrænset orkestrering af durable writes for afsluttede ture.
- [memory/MEMORY_4_W04A.md](memory/MEMORY_4_W04A.md) — W04-A: default-off loopback-skriveflade for afsluttede ture.
- [memory/MEMORY_4_W04B.md](memory/MEMORY_4_W04B.md) — W04-B: stream-bevarende persistens efter normal-chat-ture.
- [memory/MEMORY_4_H2.md](memory/MEMORY_4_H2.md) — H2: no-redirect loopback-egress fra backend til worker.
- [memory/MEMORY_4_R04_H1.md](memory/MEMORY_4_R04_H1.md) — R04-H1: hærdning af context-request-grænsen.

## Agent 3 og Agent 4

Agent 4-dokumenterne ejes af Sol (se [AGENT_4_IDENTITY.md](AGENT_4_IDENTITY.md)).

- [agent3/ADR-A3-001_CHAT_AGENT_SURFACE.md](agent3/ADR-A3-001_CHAT_AGENT_SURFACE.md) — ADR-A3-001: chattens adgang til Agent 3 (vedtaget 15/8-2026). *Beslutning (ADR).*
- [AGENT_4_IDENTITY.md](AGENT_4_IDENTITY.md) — Agent 4: identitet og ejerskabskontrakt.
- [AGENT_4_FOUNDATION.md](AGENT_4_FOUNDATION.md) — Agent 4 foundation-kontrakt (A4-01).
- [agent4/ADR-A4-006_STATE_PROJECTION.md](agent4/ADR-A4-006_STATE_PROJECTION.md) — ADR-A4-006: autoritativ kampagnestate og reparerbar audit-projektion. *Beslutning (ADR).*
- [agent4/ADR-A4-007_OPERATOR_API_BOUNDARY.md](agent4/ADR-A4-007_OPERATOR_API_BOUNDARY.md) — ADR-A4-007: operator-API'ets host-, transport- og auth-grænse. *Beslutning (ADR).*
- [agent4/ADR-A4-008_SIDE_EFFECT_HANDOFF.md](agent4/ADR-A4-008_SIDE_EFFECT_HANDOFF.md) — ADR-A4-008: handoff af eksterne sideeffekter og ukendt udfald. *Beslutning (ADR).*
- [agent4/A4-008_SLICE_2_PREFLIGHT.md](agent4/A4-008_SLICE_2_PREFLIGHT.md) — ADR-A4-008 slice 2: målt preflight. *Evidens.*
- [agent4/A4-008_SLICE_3_PREFLIGHT.md](agent4/A4-008_SLICE_3_PREFLIGHT.md) — ADR-A4-008 slice 3: målt adfærds-preflight. *Evidens.*
- [agent4/A4-008_SLICE_4_PROOF.md](agent4/A4-008_SLICE_4_PROOF.md) — ADR-A4-008 slice 4: bevis for Agent 3-adapteren. *Evidens.*
- [agent4/A4-008_SLICE_5_PREFLIGHT.md](agent4/A4-008_SLICE_5_PREFLIGHT.md) — ADR-A4-008 slice 5: preflight for end-to-end-beviset. *Evidens.*
- [agent4/A4-008_SLICE_5_PROOF.md](agent4/A4-008_SLICE_5_PROOF.md) — ADR-A4-008 slice 5: end-to-end-bevisrapport. *Evidens.*
- [agent4/A4-18R_PHYSICAL_READ_PRODUCT.md](agent4/A4-18R_PHYSICAL_READ_PRODUCT.md) — A4-18R: fysisk read-validering af det aktuelle produkt. *Runbook.*
- [agent4/A4-25F_PHYSICAL_QUALIFICATION_RUNBOOK.md](agent4/A4-25F_PHYSICAL_QUALIFICATION_RUNBOOK.md) — A4-25f: fysisk kvalifikation af snapshot-autoriteten. *Runbook.*
- [AGENT_4_A4_01_SCHEDULER.md](AGENT_4_A4_01_SCHEDULER.md) — A4-01: caller-drevet kampagne-scheduler.
- [AGENT_4_A4_01_RECOVERY.md](AGENT_4_A4_01_RECOVERY.md) — A4-01: startup recovery.
- [AGENT_4_A4_02_CHECKPOINTS.md](AGENT_4_A4_02_CHECKPOINTS.md) — A4-02: durable kampagne-checkpoints.
- [AGENT_4_A4_03_RESOURCE_LEASES.md](AGENT_4_A4_03_RESOURCE_LEASES.md) — A4-03: resource leases og samtidighedsgrænser.
- [AGENT_4_A4_03_RESOURCE_ADMISSION.md](AGENT_4_A4_03_RESOURCE_ADMISSION.md) — A4-03: ressourcebevidst scheduler-admission.
- [AGENT_4_A4_04_RETRY_POLICY.md](AGENT_4_A4_04_RETRY_POLICY.md) — A4-04: retry-klassifikation og deterministisk backoff.
- [AGENT_4_A4_04_FAILURE_HANDLING.md](AGENT_4_A4_04_FAILURE_HANDLING.md) — A4-04: durable fejlhåndtering.
- [AGENT_4_A4_05_HEALTH_POLICY.md](AGENT_4_A4_05_HEALTH_POLICY.md) — A4-05: health-observationer og interventionspolitik.
- [AGENT_4_A4_05_HEALTH_INTERVENTION_COORDINATOR.md](AGENT_4_A4_05_HEALTH_INTERVENTION_COORDINATOR.md) — A4-05: caller-drevet koordinator for health-interventioner.
- [AGENT_4_A4_05_HEALTH_INTERVENTION_ADAPTERS.md](AGENT_4_A4_05_HEALTH_INTERVENTION_ADAPTERS.md) — A4-05: konkrete service-adaptere for health-interventioner.
- [AGENT_4_A4_06_TIMELINE.md](AGENT_4_A4_06_TIMELINE.md) — A4-06: append-only timeline og evidensreferencer.
- [AGENT_4_A4_06_DELIVERY_SINGLE_FLIGHT.md](AGENT_4_A4_06_DELIVERY_SINGLE_FLIGHT.md) — A4-06: delt process-lokal single-flight for levering.
- [AGENT_4_A4_07_TIMELINE_QUERY.md](AGENT_4_A4_07_TIMELINE_QUERY.md) — A4-07: verificeret paging af timeline-forespørgsler.
- [AGENT_4_A4_08_BATCH_DELIVERY.md](AGENT_4_A4_08_BATCH_DELIVERY.md) — A4-08: afgrænsede durable consumer-batches.
- [AGENT_4_A4_09_COMPOSITION.md](AGENT_4_A4_09_COMPOSITION.md) — A4-09: eksplicit dormant runtime-komposition.
- [AGENT_4_A4_10_OPERATOR_READ.md](AGENT_4_A4_10_OPERATOR_READ.md) — A4-10: afgrænset operator-read-model.
- [AGENT_4_A4_12_EVIDENCE_RECORDS.md](AGENT_4_A4_12_EVIDENCE_RECORDS.md) — A4-12: first-class evidensrecords.
- [AGENT_4_A4_13_EVIDENCE_OPERATOR_READ.md](AGENT_4_A4_13_EVIDENCE_OPERATOR_READ.md) — A4-13: afgrænsede operator-reads af evidens.
- [AGENT_4_A4_14_OPERATOR_API.md](AGENT_4_A4_14_OPERATOR_API.md) — A4-14: default-off worker-monteret operator-read-API.
- [AGENT_4_A4_15_PRODUCTION_READ_BOOTSTRAP.md](AGENT_4_A4_15_PRODUCTION_READ_BOOTSTRAP.md) — A4-15/A4-21: produktions-bootstrap for dormante operator-reads.
- [AGENT_4_A4_16_READ_GRANT_ADMIN.md](AGENT_4_A4_16_READ_GRANT_ADMIN.md) — A4-16: lokal administration af `agent4:read`-grant.
- [AGENT_4_A4_17_ANDROID_READ_CLIENT.md](AGENT_4_A4_17_ANDROID_READ_CLIENT.md) — A4-17: Kaliv Android-read-klient.
- [AGENT_4_A4_19_CAMPAIGN_LIST_PAGING.md](AGENT_4_A4_19_CAMPAIGN_LIST_PAGING.md) — A4-19: snapshot-paging af kampagnelisten.
- [AGENT_4_A4_25_SERVER_SNAPSHOT_AUTHORITY.md](AGENT_4_A4_25_SERVER_SNAPSHOT_AUTHORITY.md) — A4-25: server-side snapshot-autoritet (A4-25a–e).

## Sikkerhed

- [security/ANDROID_SIGNING_EXPOSURE_20261024.md](security/ANDROID_SIGNING_EXPOSURE_20261024.md) — eksponeret Android-signeringsnøgle: inddæmning og migrationsbeslutning (24/10-2026).
- [security/ANDROID_SIGNING_MIGRATION_PLAN.md](security/ANDROID_SIGNING_MIGRATION_PLAN.md) — kontrolleret migration af signeringsidentiteten; kun sikkerhedsplanlægning. *Forslag.*
- [security/ANDROID_EXTERNAL_SIGNING_SOURCE.md](security/ANDROID_EXTERNAL_SIGNING_SOURCE.md) — ekstern Android-signeringskilde via `KALIV_SIGNING_PROPERTIES_FILE`/`KALIV_SIGNING_KEYSTORE_FILE` (migrationsforberedelse).

## Leverancestyring

- [proposals/KALIV_DELIVERY_SNAPSHOT_OPERATIONS.md](proposals/KALIV_DELIVERY_SNAPSHOT_OPERATIONS.md) — operatørguide til det manuelle Kaliv Delivery Snapshot-workflow. *Runbook.*
- [proposals/KALIV_DELIVERY_EVIDENCE.md](proposals/KALIV_DELIVERY_EVIDENCE.md) — evidensledger for leverancestyringen: verificerede kørsler adskilt fra planer. *Evidens.*
- [proposals/KALIV_LIVE_EVIDENCE_20261023.md](proposals/KALIV_LIVE_EVIDENCE_20261023.md) — delvis verifikation af tværrepo-live-evidens for tre P0-tracking-issues (23/10-2026). *Evidens.*

## Design

- [design/DDR-001_KALIV_REDESIGN_FASE0.md](design/DDR-001_KALIV_REDESIGN_FASE0.md) — DDR-001: Kaliv-redesign fase 0 — palette, skala og scope (12/8-2026). *Beslutning (ADR).*
- [design/FONT_LICENSES.md](design/FONT_LICENSES.md) — fontlicenser for Kaliv-redesignet (SIL OFL 1.1).
- `design/fonts/` — fulde OFL-licenstekster for EB Garamond og Inter.
