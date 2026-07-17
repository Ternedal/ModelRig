# Aktiverings-readiness

> **Genereret af `scripts/activation_readiness.py`. Ret ikke i hånden.**
> Den her side findes fordi de dokumenter der plejede at svare på spørgsmålet alle var driftet på én gang, og det er den side et menneske læser i præcis det øjeblik hvor de beslutter at give software lov til at handle selv. Den fejler lukket: ingen rapport = ikke klar.

**Version på main:** `1.58.75`  
**Genereret:** 2026-07-17 13:13 UTC

---

## Kan Agent 3 aktiveres nu? **NEJ**

Blokerende:

- **Fysisk rig-validering:** ingen rapport på disken — fysisk validering er ikke kørt
- **To veje ind, og kun den ene er serverens løfte.** `/experimental/agent3/plans/{plan_id}/start` er serverautoritativ: `/plan` bygger planen ud fra et mål via modellen, gemmer den, og `start` tager kun id'et — klienten kan ikke røre det der køres. Men `/experimental/agent3/runs` tager stadig en `plan` i request-body ved siden af. Gaten afviser alt klienten ikke selv måtte bede om, så det er ikke en rettighedseskalering — men så længe den dør står åben, er "serverautoritativ" en egenskab ved den vej du valgte, ikke ved systemet

Indtil ovenstående er lukket, er `KALIV_AGENT3_ENABLED=1` en beslutning truffet uden evidens. Koden kan være korrekt i tests og fejle på Windows, Ollama, Tailscale eller en Pixel 6a — det er dét fysisk validering er til for, og det er ikke noget CI kan gøre for dig.

---

## Planautoritet

- **Serverbygget plan:** NEJ
- **Detalje:** **To veje ind, og kun den ene er serverens løfte.** `/experimental/agent3/plans/{plan_id}/start` er serverautoritativ: `/plan` bygger planen ud fra et mål via modellen, gemmer den, og `start` tager kun id'et — klienten kan ikke røre det der køres. Men `/experimental/agent3/runs` tager stadig en `plan` i request-body ved siden af. Gaten afviser alt klienten ikke selv måtte bede om, så det er ikke en rettighedseskalering — men så længe den dør står åben, er "serverautoritativ" en egenskab ved den vej du valgte, ikke ved systemet

---

## Fysisk validering

- **Rapport til stede:** NEJ
- **Sti:** `agent3-validation-latest.json`
- **Hvorfor ikke klar:** ingen rapport på disken — fysisk validering er ikke kørt

Sæt `KALIV_AGENT3_VALIDATION_REPORT` hvis rapporten ligger et andet sted.

---

## Dormans

- **CI-gaten siger:** `===== AGENT3 DORMANCY: 16 passed, 0 failed =====`
- **Status:** Agent 3 sover

---

## Switches (læst fra koden, ikke fra hukommelsen)

**0 af 12 feature-switches er tændt som default.** (4 af posterne nedenfor er indstillinger — tal og stier, ikke beslutninger.)

| Switch | Default | Tilstand |
|---|---|---|
| `KALIV_AGENT3_ENABLED` | `0` | slukket |
| `KALIV_ALLOW_RAG_CLOUD` | `(tom)` | slukket |
| `KALIV_CAPABILITY_TIMEOUT_S` | `2` | indstilling |
| `KALIV_CAPABILITY_TTL_S` | `10` | indstilling |
| `KALIV_CLOUD_ALLOW_PRIVATE` | `0` | slukket |
| `KALIV_DATA_DIR` | `(unset)` | slukket |
| `KALIV_EGRESS_GATE` | `(tom)` | slukket |
| `KALIV_MAX_UPLOAD_MB` | `25` | indstilling |
| `KALIV_PULL_READ_TIMEOUT_S` | `600` | indstilling |
| `KALIV_SCHEDULER` | `(tom)` | slukket |
| `KALIV_SCHEDULER_POLL_S` | `(tom)` | slukket |
| `KALIV_TOOLS_DIR` | `(unset)` | slukket |
| `KALIV_TOOLS_ENABLED` | `0` | slukket |
| `KALIV_TOOL_ISOLATION` | `(tom)` | slukket |
| `KALIV_VISION_MODEL` | `(unset)` | slukket |
| `KALIV_WORKER_ALLOW_LAN` | `0` | slukket |

---

*En readiness-side der skrives i hånden er forkert første gang nogen har travlt. Derfor regner den her side svaret ud.*
