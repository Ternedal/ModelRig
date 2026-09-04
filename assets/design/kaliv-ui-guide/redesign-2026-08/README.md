# Handoff: Kaliv Android App — designoverhaling

## Overview
Komplet visuel og strukturel overhaling af Kaliv (Android-appen i ModelRig-repoet, `android/app`): 27 mobilskærme i mørkt + lyst tema. Kernen er to UX-greb: (1) kilde-skift lokal/cloud samlet i ét ark bag en model-chip, (2) RAG/værktøjer/agent samlet i ét "Kapaciteter"-ark. Dertil skærme for hele produktfladen: chat, samtaler, Viden, modeller, Handlingslog, Agent 3, Agent 4, stemme, onboarding m.fl.

## About the Design Files
Filerne i denne pakke er **designreferencer bygget i HTML** (`Kaliv Redesign.dc.html` + `assets/ankh_gold.png` + kontaktark-PNG'er). De er prototyper der viser tilsigtet udseende og adfærd — ikke produktionskode. Opgaven er at **genskabe designet i den eksisterende Kotlin/Jetpack Compose-app** (`android/app/src/main/java/dk/ternedal/modelrig/ui/`, Material 3, dark-first) med appens etablerede mønstre: Compose `ModalBottomSheet`, `LazyColumn`, eksisterende ViewModels og API-klienter.

## Fidelity
**High-fidelity.** Farver, typografi, spacing, radier og copy er endelige og skal genskabes præcist med værdierne nedenfor. Skærme mærket **"designforslag"** i mockup-filens billedtekster har ingen API-flade endnu — implementér dem kun efter separat beslutning.

## Kilde-sandhed i repoet
- Tokens: `assets/design/kaliv-ui-guide/kaliv-ui-tokens.json` (+ `.css`)
- Target-mockup (desktop): `assets/design/kaliv-ui-guide/Kaliv_UI_Target_Mockup.png`
- Mærke: `android/app/src/main/res/drawable-nodpi/ic_launcher_monochrome.png` (ankh — genfarves til guld, se Assets)
- API: `backend/internal/httpapi/server.go` · Agent 3: `AGENT3_READ_REVIEW.md`, `AGENT3_CANCELLATION_CONTRACT.md` · Agent 4: `docs/AGENT_4_A4_10_OPERATOR_READ.md` · KalivDev: `devcontrol/`

## Design Tokens

### Farver — mørkt tema (standard)
| Rolle | Værdi |
| --- | --- |
| canvas | #0B0A09 |
| surface (kort, komposer, sheets #120E0A) | #171411 |
| surfaceDim (bannere, info-kort) | #141009 / #14110E |
| elevated (ikonbrikker, toggle-spor fra, badges) | #211B16 |
| userBubble | #211D18, kant #2F2A24 |
| hairline | #2A2521 · #2A2119 · listedeler #1C1611 |
| tekst primær | #F3EFE6 · #E9DFCA · brød #EEE6D8 |
| tekst sekundær | #A89D90 · svag #776D62 · svagest #6A6156 |
| **guld fyld** (primærknap, aktiv toggle, valgt kant, KALIV-capslinje) | **#B08A3E** |
| **guld accent** (tekst/ikon, links) | **#D4AB52** |
| guld tint-bg (badges) | rgba(212,171,82,.16) |
| status ok | #77836D · advarsel #A08050 · destruktiv #C96B5D |
| tekst på guld fyld | #F6EFE2 |

### Farver — lyst tema
| Rolle | Værdi |
| --- | --- |
| canvas | #F7F3EC |
| surface | #FFFDF9 · surfaceDim #F1EADC/#EFE8DB · elevated #EDE5D8 |
| userBubble | #EDE5D8, kant #DCD2C2 |
| hairline | #D7C9B4 · deler #E3DACB |
| tekst primær | #231E19 · sekundær #776D62 · svag #9A9084 |
| guld fyld | #B08A3E (samme som mørk) · guld accent-tekst **#9C7A28** |
| status ok #5F6B52 · advarsel #957620 · destruktiv #A8503F |
| toggle-knop | #FFFDF9 i begge temaer |

### Typografi
- **EB Garamond** (Google Fonts) weight 500: wordmark (caps, tracking .22em; splash .42em) og skærmtitler 21px (sheets 19–20px), tracking .01em
- **Inter** alt andet: brød 13.5px/1.6 · rækketitel 600 13–13.5px · sekundær 11–11.5px · sub 10.5px · caps-labels 700 9.5px tracking .18em farve #6A6156
- Assistent-svar: **flad tekst på canvas** (ingen boks), KALIV-capslinje 700 10px tracking .2em i #B08A3E ovenover + tid i svag
- Minimum interaktiv højde 44dp-ækvivalent (mockup bruger 322px-bredde ~ 393dp reference)

### Form
- Radier: kort/rækker 12 · popovers 13 · komposer 16 · bottom-sheets 18 18 0 0 · brugerboble 14 14 5 14 · chips/piller 999
- Kontakter: 42×24, spor guld-fyld (til) / elevated (fra), knop 20px hvid
- Primærknap: fyldt #B08A3E, tekst #F6EFE2, radius 12–14. Sekundær: transparent + hairline-kant. Ingen gradients, ingen glød, ingen skygger på statusdots.
- Bezel/mockup-ramme er kun til præsentation — implementeres ikke.

## Screens (struktur + nøglekomponenter)
Alle skærme findes i begge temaer i `Kaliv Redesign.dc.html`; rækkefølgen her matcher filen.

1. **Tom-tilstand (chat)** — top-bar: ankh-brik 32px + KALIV-wordmark, søg + overflow. Kontekst-chip-række (horisontal scroll, højre-fade): `◈ qwen3:14b ▾` (åbner Kilde & model), `RAG`, `Tools` (åbner Kapaciteter). Midte: ankh 64px (opacity .85), serif-linje "Hvad kan jeg hjælpe med?", sub "Alt kører på din rig", 3 forslag-rækker (surfaceDim, ingen kant, trailing pil). Komposer: tekstfelt + vedhæft/mic + guld send-FAB 38px.
2. **Aktiv samtale** — brugerbobler højre (userBubble). Assistent: KALIV-capslinje + tid, flad brødtekst; kilder som chips UNDER svaret (neutral dot #8A7A66); handlingsrække kopiér/up/down i svag farve; blink-cursor #D4AB52 ved streaming. RAG-chip i chip-rækken viser aktiv tilstand (guld tint-bg + guld kant, "RAG · Til").
3. **Kilde & model** (bottom-sheet) — sektion KILDE: radiokort "Din rig · lokalt" (valgt: 1.5px guld kant, grøn statusdot + adresse) og "Ollama Cloud" ("gpt-oss:120b · forlader enheden"). Sektion MODEL PÅ DIN RIG: radioliste qwen3:14b (Indlæst, grøn) / llama3.1:8b / mistral:7b (Klar) + Genindlæs-link. API: `chat_mode` rig|cloud, `/models`, `/models/running`.
4. **Kapaciteter** (bottom-sheet) — rækker m. ikonbrik + titel + status + kontakt: Viden (RAG) ("3 dokumenter · svarer med kilder", link "Kilder: Alle"), Værktøjer ("Kræver din godkendelse hver gang", advarselsfarve), Agent, Stemme (række m. "Åbn"). Bund: skjold-note "Værktøjer og agent kører kun på din rig og logges i Handlingslog." API: `/tools/enabled`.
5. **Opsætning/parring** — rig-kort udfoldet: Server-URL-felt, Parringskode-felt (tracking .16em), inline-advarsel om 0.0.0.0/Tailscale, guld Forbind-knap, gemte profiler som chips (Hjemme/Arbejde/+ Gem). Cloud-række kollapset under. API: `POST /pair/start` + `/pair/claim`.
6. **Stemme** — status-chip "Lokalt · da-DK" + luk. Midte: ankh 60px + 15-søjle equalizer (guld #B08A3E-varianter, scaleY-animation), serif "Lytter …", transkript. Bund: guld mic-knap 74px, "Tryk for at afbryde". API: `/voice/status`, `/voice/converse/stream`. ASR/TTS altid lokalt.
7. **Samtaler** — søgefelt, dato-grupper (caps-labels), rækker: titel + snippet (ellipsis) + kilde-ikon (rig/cloud) + tid. Aktiv række: surfaceDim + guld hairline-kant (ingen venstre-bjælke).
8. **Viden (RAG)** — skjold-note "…bliver på din rig". Dokumentkort: filtype-brik (neutral farve), navn, "2.4 MB · 128 udsnit", kontakt pr. dokument; deaktiveret kort i 60% opacity; "Tilføj dokument"-række (hairline, guld tekst). Bundkort: "Henter top 5 udsnit · kun lokalt". API: `/rag/ingest` (pdf/docx/pptx/html/image/tekst), `/rag/sources`.
9. **Onboarding · parring** (designforslag: QR oven på pair-koden) — "TRIN 2 AF 3", serif-titel, QR-viewfinder m. guld hjørner, "Indtast kode manuelt"-fallback.
10. **Modeller** — VRAM-linje ("Din rig · 24 GB VRAM fri"), kort pr. model: navn + STANDARD-badge (guld tint), størrelse/parametre, status Indlæst (grøn)/Klar; download-kort m. fremdriftsbjælke (guld på elevated, 62 %); "Hent ny model". API: `/models/pull`, `/models/delete`.
11. **Handlingslog** — skjold-note. Afventende kort øverst (surfaceDim): handling + "Afventer din godkendelse" + Godkend (guld fyld)/Afvis. Historik-rækker: ikonbrik, titel, "Værktøj: Filer · 10:41", badge Godkendt/Afvist. API: `/tools/confirm`, `/tools/audit`.
12. **Agent-kørsel (chat)** — plan-kort i assistent-position: header "Plan" + Stop-pille (destruktiv tekst), trinliste: done-flueben (ok-grøn), aktivt trin guld dot + fed, kommende svag. Capslinje: "agent · trin 3 af 4".
13. **Fejltilstand · rig offline** — banner-kort: afbrudt-rig-ikon, "Din rig svarer ikke", "Sidst set 10:43 · skifter aldrig selv til cloud", knapper "Prøv nu" (guld) + "Skift til cloud" (sekundær). Historik 45% opacity, komposer deaktiveret ("Afventer forbindelse …", send-knap elevated/svag). Princip: `autoCloudFallback=false` — aldrig stille fallback.
14. **Splash** (designforslag) — ankh 62px (op. .85), wordmark tracking .42em, bund-linje "LOKAL-FØRST · PRIVAT" 9px tracking .3em. Ingen animation.
15. **Tænke-tilstand** (designforslag) — ankh 16px m. rolig puls (opacity .4→.85, 2.6s) + "læser 2 dokumenter …" i stedet for generisk "skriver".
16. **Widget & Quick Settings** (designforslag) — widget: ankh-brik + "Spørg Kaliv …"-pille + guld mic; QS-flise "Kaliv · Tal" (aktiv = guld cirkel).
17. **Del til Kaliv** (designforslag) — share-sheet: fil-kort, to valgkort "Tilføj til Viden" (valgt, guld kant) / "Send i samtale", guld CTA.
18. **Rig-status** — forbindelseskort m. adresse + oppetid; målere VRAM/GPU-temp/CPU (guld fyld på elevated spor); INDLÆST-liste; knapper "Genstart model-server" / "Frigør VRAM" (sekundære).
19. **Eksport & backup** (designforslag) — kontakt-kort "Automatisk backup til riggen" ("Hver nat kl. 03:00 · krypteret"), seneste backup-linje, rækker Eksportér samtaler/Viden, destruktiv "Slet alle data på enheden".
20. **Model-hurtigskift** (designforslag) — langt tryk på model-chip → popover: SENESTE, qwen3:14b (flueben), llama3.1:8b, deler, "Alle modeller …" (guld). Chat bag dæmpes rgba(5,4,3,.62).
21. **Svar-citater** (designforslag) — markeret passage: guld tint-bg + 1px guld-ring, radius 3; handlingspille under: "Spørg videre" (guld) / Kopiér / Gem i Viden, adskilt af lodrette delere.
22. **Offline-kø** (designforslag) — top-pille "Rig offline · 1 besked i kø"; kø-besked: boble 75% opacity + ur-ikon + "I kø — sendes når riggen svarer" i advarselsfarve.
23. **KalivDev · pipeline** (designforslag som mobilflade; kontrakter i `devcontrol/`) — task-kort m. REVIEW-badge; lodret evidenskæde: Task-kontrakt → Tier A → Semantisk review (aktiv) → Draft-PR → Publisher (todo m. connector-linjer); bundnote "Merge kræver altid dig."
24. **KalivDev · review** — verdiktliste pr. acceptkriterium (ok/afventer/mangler), EVIDENS-kort (Tier A-kvittering, workspace-snapshot, Ed25519-signatur), knapper Godkend verdikt (guld) / Afvis med begrundelse.
25. **Agent 3 · read-checkpoint** (fra `AGENT3_READ_REVIEW.md`; API `/experimental/agent3/*`) — run pauser efter hvert read: udført read m. resultatkort, pending read-window, "KAN FJERNES"-badges på removable reads, låst write-tail (hængelås, "kræver separat bekræftelse"), knapper "Fortsæt (ét read)" (guld) / "Replan-preview", note "Fortsætter aldrig automatisk", "Stop plan" destruktiv. Stop = plan-scope (cancellation-kontrakt).
27. **Scheduler** (API: `/schedules` — preview/create/renew m. godkendelses-token pr. enhed, `/enabled`, `/status`; worker `schedule_api.py`) — skjold-note "Oprettelse og fornyelse kræver din godkendelse — hver gang." Fornyelseskort øverst (surfaceDim): UDLØBER-badge (advarselsfarve), aftale-detaljer + kvitteringslinje "Godkendt fra denne enhed · 2/8 14:02", knapper "Forny (preview)" (guld) / "Lad udløbe". Aftalekort: ur-ikonbrik, titel, `tool · cadence · tidszone`, "Næste: …" (guld ved aktiv), kontakt til/fra; pause-kort viser "fornyelse bevarer pausen"; meta-række Kørsler x af y / Udløber. Maks 1 banner + 2-3 kort synlige — listen scroller. "Ny planlagt kørsel (preview)"-række. Bundkort: runtime-status (kører · aktive · ticks · overlap afvist).

26. **Agent 4 · kampagner** (fra `A4-10 operator read`; API `/experimental/agent4/operator/*`) — read-only, nyeste først: kampagnekort m. statusbadge KØRER (guld tint)/I KØ (elevated)/FEJLET (destruktiv tint), sub-linje (lease/retry), meta-række Timeline/Evidens/Forsøg; bundkort: timeline-hash (monospace) + "Efter genstart: Intet antages kørende."

## Interactions & Behavior
- Bottom-sheets: standard Compose ModalBottomSheet, drag-handle 38×4 (#2A2521), scrim rgba(5,4,3,.64) mørk / rgba(35,30,25,.32) lys
- Chip-række: horisontal scroll m. fade-mask i højre kant (86%→transparent)
- Streaming: blink-cursor (7×15px #D4AB52, 1s steps) sidst i svaret; tænke-puls 2.6s
- Equalizer (stemme): scaleY .32→1, 1.4s ease-in-out, staggered -0.09s pr. søjle
- Fejl/offline: aldrig automatisk kilde-skift; altid eksplicit brugervalg. Send-knap deaktiveret = elevated bg + svag ikon
- Godkendelses-flow (tools/KalivDev/Agent 3): afventende handling altid øverst m. guld primær + sekundær afvis; alt logges
- Ingen hover-afhængighed (touch); tryk-feedback via Compose ripple

## State Management (eksisterende flader)
- Kilde/model: chat_mode rig|cloud + valgt model (persisteret); modelliste fra `/models` + `/models/running`
- Kapaciteter: tools enabled/disabled (`/tools/enabled`), RAG on/off + kildevalg, agent on/off, alt pr. samtale
- Forbindelse: rig-status (forbundet/offline, adresse, oppetid) driver top-chip, fejlbanner og komposer-tilstand
- Handlingslog: pending confirmations (`/tools/confirm`) + audit-liste (`/tools/audit`)
- Agent 3: run-tilstand (running/waiting read_review/finished), pending reads, write-tail
- Agent 4: kampagneliste m. lifecycle, timeline-antal, evidens, leases — poll via operator read
- Viden: kilder m. størrelse/udsnit/enabled (`/rag/sources`, `/rag/stats`)

## Assets
- `assets/ankh_gold.png` — ankh genereret fra `ic_launcher_monochrome.png` m. mat guld-gradient (#C49C42→#95702C), 6% padding. I Compose: brug monochrome-draweren + tint, eller eksportér denne PNG.
- Ikoner: alle er inline-SVG'er i mockuppen (stroke 1.7–2, round caps) — map til Material Symbols outlined-ækvivalenter.
- Fonts: EB Garamond + Inter fra Google Fonts (bundl som ressourcer).

## Kendte huller (reelle features uden skærm endnu)
Enheder (`/devices` + revoke, token-rotation) · RAG-kilde-sletning.

## Files
- `Kaliv Redesign.dc.html` — alle 27 skærme × 2 temaer (åbn i browser; mørk sektion øverst, lys nederst)
- `kaliv-dark.png` / `kaliv-light.png` — kontaktark
- `assets/ankh_gold.png` — guld ankh
