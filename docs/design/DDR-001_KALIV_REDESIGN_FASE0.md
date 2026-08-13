# DDR-001 — Kaliv-redesign fase 0: palette, skala og scope

**Status:** Besluttet af Anders 12/08-2026 ("jeg følger dine anbefalinger", issue #518)
**Kilde:** Redesign-handoff v2 (26 skærme × mørk/lys, high-fidelity, endelige tokens) + read-only repo-recon mod c6aaf927

DDR-serien (design decision records) dokumenterer designbeslutninger for Kaliv-fladerne på samme måde som ADR-serierne dokumenterer arkitektur: beslutning før kode.

## B1 — Kontrast: AA holdes, fire roller justeres

Handoffens palette er endelig, men fire tekstroller målte under WCAG AA 4,5:1. De justeres efter husets egen præcedens (light.muted-mørkningen 27/07, semantic.warning 29/07, Theme.kt's ink-på-accent-regel):

| Rolle | Handoff | Besluttet | Målt |
| --- | --- | --- | --- |
| Tekst på guld-fyld | #F6EFE2 (2,80:1) | **#2B1C05** | 5,15:1 |
| Svag tekst, mørk | #776D62 (3,91:1) | **#8A8073** | 5,10:1 |
| Caps-label, mørk | #6A6156 (3,26:1) | **#857A6C** | 4,71:1 |
| Guld accent-tekst, lys | #9C7A28 (3,63:1) | **#7E621C** | 5,20:1 |

Resten af paletten står uændret: guld fyld #B08A3E, guld accent mørk #D4AB52, canvas #0B0A09/#F7F3EC osv.

**Tillægsjusteringer i samme ånd (afgjort under implementering af B1):**
- Lyst tema-hierarki: sekundær tekst beholdes på nuværende **#6F665C** (består 4,54:1 på elevated #EDE5D8; handoffens #776D62 måler 4,08:1 dér). Svag/caps i lyst tema = **#776D62** (4,64:1 på canvas); handoffens #9A9084 (2,85:1) udgår.
- Guld-fyld mod lys canvas måler 2,92:1 (grænse 3,0 for non-text). Accepteret som dokumenteret `KNOWN_BELOW_AA`-post: knappen identificeres af sin tekst (5,15:1), ikke af fladens kant.

## B2 — px→dp-skala

Mockuppen er tegnet i 322px-bredde ≈ 393dp-reference. Regel: **uniform ×393/322 (≈1,2205)**. Tekst afrundes til nærmeste 0,5sp, mål til nærmeste hele dp. **1px-hairlines skaleres ikke** (forbliver 1dp). Nøgletabellen står i `kaliv-ui-tokens.json` under `conversion`; al geometri i Compose går via navngivne konstanter, aldrig inline.

## B3 — Rig-status-målere

VRAM pr. model findes allerede via `GET /api/v1/models/running` (Ollama `/api/ps`). GPU-temp + CPU leveres af en lille ny `GET /api/v1/system/status` i Go-backenden (egen slice, blokerer først skærm 18/PR-16).

## B4 — Version

Faserne lander løbende på main. **2.0.0 tagges når fase 3 er komplet** (1.0.0 er udelukket: updaterens isNewer afviser fald fra 1.58.x).

## B5 — M3 vs. pixel-perfekt

`Theme.kt`s eksisterende mønster (KalivColors + CompositionLocal + afledt M3-scheme) er arkitekturen. M3-komponenter med Kaliv-tokens hvor afvigelsen er ≤ 3dp (Switch m.fl.); custom composables kun hvor M3 ikke kan (chip-række m. fade-mask, capslinje, equalizer, plan-kort, streaming-cursor). "High-fidelity" betyder: tokenværdierne håndhæves — ikke pixeljagt på M3's indre geometri.

## Scope

15 API-bårne skærme implementeres nu; de 10 skærme mærket **designforslag** i handoffen udskydes til separat beslutning; KalivDev-mobilflader kræver API der ikke findes (egen ADR i DC-serien). Eksisterende skærme uden mockup-modstykke (ControlCenter + sektioner, Schedules, Agent3 Task/Memory/Validation/Replan/Capability) **re-skinnes via tokens** — layoutomlægning kræver design.

## Konsekvenser

1. `kaliv-ui-tokens.json` udvides (skema-version 2.0): nye roller i dark/light, ny `gold`-gruppe, radier og typografi for mobilfladen. **Ingen eksisterende nøgler fjernes eller omdøbes** — kun værdiskift og tilføjelser, så kaldende kode kompilerer uændret.
2. `brand.bronze/gold/highlight` og `semantic.*` er **deprecated** fra denne DDR: nye flader bruger `gold.*` og de tematiserede `ok/warn/danger`. Fjernes når desktop `Brand.kt` er migreret.
3. Palettepinnen af 30/07 (`platformOverrides.android.color.light.muted` #5A4831) står urørt indtil `Theme.kt` migreres til tokens i fase 1 — derefter afløses posten af denne DDR, og divergens-gaten forenkles i samme PR.
4. Kontrast-gatens parliste udvides til de nye roller, målt hvor de bruges (svag/caps/accent på canvas; tekst-på-guld på guld-fyld; statusfarver på surface).

## Referencer

Issue #518 (beslutningsgrundlag med recon-fund) · handoff-pakken i `assets/design/kaliv-ui-guide/redesign-2026-08/` (landes med PR-1) · implementeringsplanens 18 slices i 5 faser.
