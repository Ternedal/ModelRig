# Aktiverings-readiness

> **Genereret af `scripts/activation_readiness.py`. Ret ikke i hånden.**
> Den her side findes fordi de dokumenter der plejede at svare på spørgsmålet alle var driftet på én gang, og det er den side et menneske læser i præcis det øjeblik hvor de beslutter at give software lov til at handle selv. Den fejler lukket: ingen rapport = ikke klar.

**Version på main:** `2.0.13`
**Kørende appliance:** ingen fundet på 127.0.0.1:8080 — dommen bygger på dette miljøs rapportstier (CI-fallback)
**Genereret:** 2026-09-23 18:12 UTC

---

## Kan Agent 3 aktiveres nu? **NEJ**

Blokerende:

- **Fysisk rig-validering:** ingen rapport på disken — fysisk validering er ikke kørt

Indtil ovenstående er lukket, er `KALIV_AGENT3_ENABLED=1` en beslutning truffet uden evidens. Koden kan være korrekt i tests og fejle på Windows, Ollama, Tailscale eller en Pixel 6a — det er dét fysisk validering er til for, og det er ikke noget CI kan gøre for dig.

---

## Kan scheduleren aktiveres nu? **NEJ**

Ingen blokerende fund specifikke for scheduleren.

- **Beviser en godkendelse et menneske:** ja
- **Leveringsmodellen består alle durability-prober:** ja
- **Fysisk validering gælder også her:** scheduleren kører på den samme rig, så rapporten er en forudsætning for begge.

### Durability-prober (kørt live mod rigtige komponenter, T-015)

Hver probe bygger de RIGTIGE komponenter mod engangs-databaser og injicerer fejlen — claim-crash, post-eksekverings-crash, pause efter claim, udtømt budget, forfalsket approval. Grønt beviser at mekanismerne virker i processen på dette træ; det fysiske bevis på riggen er stadig sin egen blocker.

| Probe | Resultat | Detalje |
|---|---|---|
| Claim er durable + budget reserveres atomisk | ✅ | claim skriver durable occurrence og reserverer budget i samme transaktion |
| Samme occurrence kan ikke claimes to gange | ✅ | samme occurrence kan ikke claimes to gange |
| Crash før kørsel: opgives og refunderes | ✅ | crash før kørsel: occurrence opgives og slot refunderes |
| Crash efter kørsel: evidens holder budgettet brugt | ✅ | crash efter kørsel: audit-evidens holder budgettet brugt |
| Pause efter claim stopper in-flight occurrence | ✅ | pause efter claim stopper in-flight occurrence og refunderer |
| Budgetloft holder på tværs af claims | ✅ | max_runs kan ikke overskrides på tværs af claims |
| Ukendt udfald: slot beholdes og granten pauses | ✅ | ukendt udfald: slot beholdes og granten pauses — max_runs kan ikke blive N+1 via crash |
| Recovery respekterer en levende ejers lease | ✅ | recovery uden lease rører intet — en levende ejers in-flight claims kan ikke opgives |
| Forfalsket approval afvises og slot frigives | ✅ | en godkendelse der ikke matcher handlingen afvises før kørsel (runner-refusal + ToolGate som dobbelt bælte) og slotten frigives |

---

## Planautoritet (Agent 3)

- **Serverbygget plan:** ja
- **Detalje:** planen bygges og gemmes på serveren; klienten kan kun starte den via et kortlivet single-use plan-id, mens retry kloner den gemte plan

---

## Fysisk validering

- **Rapport til stede:** NEJ
- **Sti:** `validation/agent3-rig-validation-latest.json`
- **Hvorfor ikke klar:** ingen rapport på disken — fysisk validering er ikke kørt

Sæt `KALIV_AGENT3_VALIDATION_REPORT` hvis rapporten ligger et andet sted.

---

## Dormans

- **CI-gaten siger:** `===== AGENT3 DORMANCY: 41 passed, 0 failed =====`
- **Status:** Agent 3 sover

---

## Switches (læst fra koden, ikke fra hukommelsen)

**0 af 37 feature-switches er tændt som default.** (32 af posterne nedenfor er indstillinger — tal og stier, ikke beslutninger.)

| Switch | Default | Tilstand |
|---|---|---|
| `KALIV_AGENT3_APPROVAL_REQUIRED` | `0` | slukket |
| `KALIV_AGENT3_APPROVAL_SECRET` | `(tom)` | indstilling |
| `KALIV_AGENT3_ENABLED` | `0` | slukket |
| `KALIV_AGENT3_MEMORY_API_SECRET` | `(tom)` | indstilling |
| `KALIV_AGENT3_MEMORY_GRANT_DB` | `(tom)` | indstilling |
| `KALIV_AGENT3_MEMORY_STORE` | `(tom)` | indstilling |
| `KALIV_AGENT3_TASK_WORKERS` | `2` | indstilling |
| `KALIV_AGENT4_DATA_ROOT` | `(tom)` | indstilling |
| `KALIV_AGENT4_OPERATOR_API` | `0` | slukket |
| `KALIV_ALLOW_RAG_CLOUD` | `(tom)` | slukket |
| `KALIV_CLOUD_ALLOW_PRIVATE` | `0` | slukket |
| `KALIV_COMPUTER_USE` | `0` | slukket |
| `KALIV_COMPUTER_USE_SCREEN` | `0` | slukket |
| `KALIV_CONSCIOUSNESS_AUTONOMOUS_ENABLED` | `0` | slukket |
| `KALIV_CONSCIOUSNESS_CHAT_ENABLED` | `0` | slukket |
| `KALIV_CONSCIOUSNESS_CORE_ENABLED` | `0` | slukket |
| `KALIV_CONSCIOUSNESS_EPISODE_REVIEW_ENABLED` | `0` | slukket |
| `KALIV_CONSCIOUSNESS_EPISODE_REVIEW_RUNTIME_ENABLED` | `0` | slukket |
| `KALIV_CONSCIOUSNESS_EVENT_STEP_ENABLED` | `0` | slukket |
| `KALIV_CONSCIOUSNESS_GUIDANCE_ENABLED` | `0` | slukket |
| `KALIV_CONSCIOUSNESS_REPLY_GUIDANCE_ENABLED` | `0` | slukket |
| `KALIV_CONSCIOUSNESS_SLEEP_LIFECYCLE_ENABLED` | `(tom)` | slukket |
| `KALIV_CONSCIOUSNESS_STEP_ENABLED` | `0` | slukket |
| `KALIV_CONSCIOUSNESS_SUPERVISOR_ENABLED` | `0` | slukket |
| `KALIV_CONSCIOUSNESS_TURN_COGNITION_ENABLED` | `0` | slukket |
| `KALIV_DATA_DIR` | `(unset)` | indstilling |
| `KALIV_DESKTOP_ALLOWLIST_FILE` | `(tom)` | indstilling |
| `KALIV_DEVCONTROL_PILOT` | `0` | slukket |
| `KALIV_EGRESS_GATE` | `(tom)` | slukket |
| `KALIV_FILE_CAPABILITIES_ENABLED` | `(tom)` | slukket |
| `KALIV_FILE_WORKSPACE_ID` | `(tom)` | indstilling |
| `KALIV_FILE_WORKSPACE_ROOT` | `(tom)` | indstilling |
| `KALIV_GITHUB_CONNECTOR_PILOT` | `0` | slukket |
| `KALIV_HOME_RIG_PILOT` | `0` | slukket |
| `KALIV_MAX_UPLOAD_MB` | `25` | indstilling |
| `KALIV_MEMORY4_CHAT_ENABLED` | `0` | slukket |
| `KALIV_MEMORY4_CHAT_WRITE_ENABLED` | `0` | slukket |
| `KALIV_MEMORY4_CONTEXT_ENABLED` | `(tom)` | slukket |
| `KALIV_MEMORY4_SEMANTIC_ENABLED` | `(tom)` | slukket |
| `KALIV_MEMORY4_WRITE_ENABLED` | `(tom)` | slukket |
| `KALIV_MEMORY4_WRITE_INDEXED_PROTECTED` | `(tom)` | slukket |
| `KALIV_PULL_READ_TIMEOUT_S` | `600` | indstilling |
| `KALIV_READ_CONNECTOR_PILOT` | `0` | slukket |
| `KALIV_SCHEDULER` | `(tom)` | slukket |
| `KALIV_SCHEDULER_API` | `0` | slukket |
| `KALIV_SCHEDULER_APPROVAL_SECRET` | `(tom)` | indstilling |
| `KALIV_SCHEDULER_POLL_S` | `(tom)` | indstilling |
| `KALIV_TOOLS_DIR` | `(unset)` | indstilling |
| `KALIV_TOOLS_ENABLED` | `0` | slukket |
| `KALIV_TOOL_ISOLATION` | `(tom)` | indstilling |
| `KALIV_VISION_MODEL` | `(tom)` | indstilling |
| `KALIV_WEB_RESEARCH_ENABLED` | `(tom)` | slukket |
| `KALIV_WORKER_ALLOW_LAN` | `0` | slukket |
| `MODELRIG_ADMIN_KEY` | `(unset)` | indstilling |
| `MODELRIG_CLAIM_MAX` | `(unset)` | indstilling |
| `MODELRIG_CONFIG` | `(unset)` | indstilling |
| `MODELRIG_DATA` | `(unset)` | slukket |
| `MODELRIG_EMBED_MODEL` | `nomic-embed-text` | indstilling |
| `MODELRIG_GEN_MODEL` | `qwen2.5-coder:7b` | indstilling |
| `MODELRIG_HOST` | `(unset)` | indstilling |
| `MODELRIG_OLLAMA_KEEP_ALIVE` | `30m` | indstilling |
| `MODELRIG_OLLAMA_KEY` | `(unset)` | indstilling |
| `MODELRIG_OLLAMA_TIMEOUT` | `600` | indstilling |
| `MODELRIG_OLLAMA_URL` | `http://127.0.0.1:11434` | indstilling |
| `MODELRIG_PAIRING_TTL` | `(unset)` | indstilling |
| `MODELRIG_PORT` | `(unset)` | indstilling |
| `MODELRIG_WORKER_HOST` | `127.0.0.1` | indstilling |
| `MODELRIG_WORKER_PORT` | `8099` | indstilling |
| `MODELRIG_WORKER_URL` | `(unset)` | indstilling |

---

*En readiness-side der skrives i hånden er forkert første gang nogen har travlt. Derfor regner den her side svaret ud.*
