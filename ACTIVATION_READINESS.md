# Aktiverings-readiness

> **Genereret af `scripts/activation_readiness.py`. Ret ikke i hånden.**
> Den her side findes fordi de dokumenter der plejede at svare på spørgsmålet alle var driftet på én gang, og det er den side et menneske læser i præcis det øjeblik hvor de beslutter at give software lov til at handle selv. Den fejler lukket: ingen rapport = ikke klar.

**Version på main:** `1.58.103`  
**Genereret:** 2026-07-18 09:14 UTC

---

## Kan Agent 3 aktiveres nu? **NEJ**

Blokerende:

- **Fysisk rig-validering:** ingen rapport på disken — fysisk validering er ikke kørt

Indtil ovenstående er lukket, er `KALIV_AGENT3_ENABLED=1` en beslutning truffet uden evidens. Koden kan være korrekt i tests og fejle på Windows, Ollama, Tailscale eller en Pixel 6a — det er dét fysisk validering er til for, og det er ikke noget CI kan gøre for dig.

---

## Kan scheduleren aktiveres nu? **NEJ**

Ingen blokerende fund specifikke for scheduleren.

- **Beviser en godkendelse et menneske:** ja
- **Fysisk validering gælder også her:** scheduleren kører på den samme rig, så rapporten er en forudsætning for begge.

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

- **CI-gaten siger:** `===== AGENT3 DORMANCY: 16 passed, 0 failed =====`
- **Status:** Agent 3 sover

---

## Switches (læst fra koden, ikke fra hukommelsen)

**0 af 13 feature-switches er tændt som default.** (12 af posterne nedenfor er indstillinger — tal og stier, ikke beslutninger.)

| Switch | Default | Tilstand |
|---|---|---|
| `KALIV_AGENT3_ENABLED` | `0` | slukket |
| `KALIV_ALLOW_RAG_CLOUD` | `(tom)` | slukket |
| `KALIV_CLOUD_ALLOW_PRIVATE` | `0` | slukket |
| `KALIV_DATA_DIR` | `(unset)` | slukket |
| `KALIV_EGRESS_GATE` | `(tom)` | slukket |
| `KALIV_MAX_UPLOAD_MB` | `25` | indstilling |
| `KALIV_PULL_READ_TIMEOUT_S` | `600` | indstilling |
| `KALIV_SCHEDULER` | `(tom)` | slukket |
| `KALIV_SCHEDULER_API` | `0` | slukket |
| `KALIV_SCHEDULER_POLL_S` | `(tom)` | slukket |
| `KALIV_TOOLS_DIR` | `(unset)` | slukket |
| `KALIV_TOOLS_ENABLED` | `0` | slukket |
| `KALIV_TOOL_ISOLATION` | `(tom)` | slukket |
| `KALIV_VISION_MODEL` | `(unset)` | slukket |
| `KALIV_WORKER_ALLOW_LAN` | `0` | slukket |
| `MODELRIG_ADMIN_KEY` | `(unset)` | indstilling |
| `MODELRIG_CLAIM_MAX` | `(unset)` | indstilling |
| `MODELRIG_CONFIG` | `(unset)` | indstilling |
| `MODELRIG_DATA` | `(unset)` | indstilling |
| `MODELRIG_HOST` | `(unset)` | indstilling |
| `MODELRIG_OLLAMA_KEY` | `(unset)` | indstilling |
| `MODELRIG_OLLAMA_URL` | `(unset)` | indstilling |
| `MODELRIG_PAIRING_TTL` | `(unset)` | indstilling |
| `MODELRIG_PORT` | `(unset)` | indstilling |
| `MODELRIG_WORKER_URL` | `(unset)` | indstilling |

---

*En readiness-side der skrives i hånden er forkert første gang nogen har travlt. Derfor regner den her side svaret ud.*
