# CLIENT_STATE_DESIGN.md — #2a: uafhængige tilstande, samtykke-UI og capability-gating

> Design + handoff for klientens tilstandsmodel. **Dette er device-verificeret
> arbejde** — to tidligere blinde forsøg fejlede, så implementering sker i
> "test jeg"-loopet (APK → screenshots → itération), aldrig blindt. Den
> verificerbare kerne (TurnRouter-udvidelsen + tabel-tests) laves FØRST.

## 1. Verificeret nu-tilstand (main @ 1.58.43, line-refs — ikke husket audit-viden)

| # | Fund | Hvor | Konsekvens |
|---|---|---|---|
| N1 | `ragMode` nulstilles ved skift til cloud | `AppUi.kt:1633` (+ `:1026` ved samtale-load) | Dokumentviden "glemmes" af et mode-skift; brugeren skal genaktivere |
| N2 | RAG-togglen bor i rig-menu-flowet | `AppUi.kt:1466–1473` | Kan ikke ses/ændres i cloud-mode |
| N3 | **`allowRagCloud` er et dødt flag** | `AppUi.kt:650`: `remember { mutableStateOf(false) }` — aldrig persisteret, **ingen UI-toggle findes** | D4-samtykket kan ikke slås til af en bruger → `toolsWithRag` i cloud er ALTID false i praksis; koden bag samtykket er død sti |
| N4 | **`autoCloudFallback` har ingen UI** | Persisteret i TokenStore; kun læst (`AppUi.kt:1185/:1303`) | Local-first-defaulten kan aldrig ændres bevidst — hverken til eller fra |
| N5 | Klienten læser aldrig `/capabilities` | 0 referencer i `android/` | Voice/PDF-knapper vises også på en core-worker uden backends → fejl i stedet for forklaring |

N3/N4 er skarpere end auditsene fik sagt: det er ikke "UI'et sidder forkert" —
**samtykke-mekanismerne er utilgængelige.**

## 2. Målmodel: tre uafhængige tilstande + eksplicitte, persisterede samtykker

**Svarmodel** (rig/cloud) · **Dokumentviden** (til/fra + kildefilter) ·
**Tools** (til/fra) — uafhængige, synlige i begge modes, og **mode-skift
bevarer dem** (ingen tavse nulstillinger; N1 udgår).

**Samtykker som persisterede settings med UI:**
- `allowRagCloud` → TokenStore + samtykke-kort ved FØRSTE cloud+dokumentviden-
  send ("dine dokumentuddrag sendes til cloud-modellen — tillad?") + toggle
  under indstillinger. Aldrig implicit (INV-06/09).
- `autoCloudFallback` → toggle under indstillinger m. klar tekst; default
  forbliver FRA (local-first, settled beslutning).

**Capability-gating:** hent `GET /capabilities` ved pairing/forbindelse;
utilgængelige features vises deaktiveret m. installations-hint — ikke skjult,
ikke fejlende.

## 3. Arkitektur: udvid `TurnPlan`, opfind ikke en tredje routing

`logic/TurnRouter` (1.58.38) er kilden. Udvidelsen:

```kotlin
TurnInput  += allowRagCloud er der; tilføj hasConsentRagCloud? NEJ — allowRagCloud ER samtykket (persisteret).
TurnPlan   += useRagCloud: Boolean   // cloud-mode + ragMode + allowRagCloud (uden tools)
```

Semantik-tabellen (SKAL tabel-testes FØRST, i `TurnRouterTest` — det er den
verificerbare kerne en implementør starter med):

| mode | rag | tools | allowRagCloud | Rute |
|---|---|---|---|---|
| cloud | til | fra | **fra** | plain cloud + **blokeret-med-forklaring** (kort: "kræver samtykke") — ALDRIG tavs degradering (INV-06) |
| cloud | til | fra | til | `useRagCloud`: rig-`/rag/chat` m. cloud-modellen (RAG-data bor på riggen; syntesen er egress) |
| cloud | til | til | til | eksisterende `toolsWithRag`-sti (uændret) |
| rig | * | * | * | uændret (eksisterende tabel gælder) |

Eksekvering af `useRagCloud`: `ragChatStream` med cloud-model-parameter via
riggen (kræver rig-reachability → samme 3s-probe + ærlige fejl som cloud+tools,
1.58.36-mønstret). **A3-F01-kobling:** dette er endnu et down-payment på
spec'ens RoutePlan — samme retning, ingen konflikt.

## 4. Implementeringsrækkefølge (én APK-testet bid ad gangen)

1. **Persistér flag + settings-UI** (N3/N4): TokenStore-felter + to toggles i
   indstillinger. Lille, lav UI-risiko, gør samtykket muligt overhovedet.
2. **TurnRouter-udvidelse + tabel-tests** (ren logik, CI-verificeret grønt før
   næste skridt).
3. **Toggle-synlighed + tilstandsbevarelse** (N1/N2): flyt Dokumentviden/Tools
   ud af rig-blokken; fjern nulstillingerne ved mode-skift.
4. **Samtykke-kortet** (første cloud-RAG-send uden samtykke → kort m.
   [Tillad]/[Annullér]; Tillad sætter det persisterede flag).
5. **Capability-gating** (N5): hent/cache `/capabilities`; deaktiver + forklar.

Hvert trin: bump → CI (compile + unit) → APK → **Anders: "test jeg" +
screenshots** → næste trin. Aldrig to trin i samme APK.

## 5. Handoff-protokol (til session/udvikler med device-loop)

**Mål:** N1–N5 lukket; matricen i §3 grøn på enheden. **Constraints:** ingen
Android-SDK i sandbox — CI er eneste kompilator; runtime-bevis er Pixel 6a'en.
Ingen ændringer i eksekverings-stierne ud over §3; ingen reformat (PR #1);
branch-kroppe i `when` røres ikke uden testrække. **Kvalitetskriterier:**
tabel-tests før UI; hver påstand om adfærd efterprøvet på enheden før "virker";
verified/assumed/guessed-skelnen i alle statusser. **Acceptance:**
VALIDATION-matricen udvides med D7 (mode-skift bevarer tilstande), D8
(samtykke-kort første gang, husket derefter), D9 (capability-deaktiverede
knapper forklarer sig), E6 (cloud-RAG svarer m. kilder når samtykke givet).
**Gør IKKE:** auto-degradering, skjulte features, Agent 3-foregribelse ud over
`TurnPlan`-udvidelsen.
