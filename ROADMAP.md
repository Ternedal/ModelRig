# ModelRig / Kaliv — Roadmap

> ## Tilstand står IKKE her
>
> **Aktuel tilstand: [`CURRENT_STATE.md`](CURRENT_STATE.md) og
> [`ACTIVATION_READINESS.md`](ACTIVATION_READINESS.md).** De genereres fra koden
> ved hver release og kan ikke tage fejl om hvad der er på main, fordi de ikke
> husker — de regner efter.
>
> Den her fil er **beslutninger og historie**. Datoer og versioner i den er
> historiske og skal læses sådan. Hvis den modsiger de genererede sider om hvad
> systemet ER, så tager den fejl; det er ikke et spørgsmål der skal afvejes.
>
> **Ejer:** Anders · **Retningen nedenfor er fra 2026-07-13** — før Agent 3 og
> scheduleren fandtes. Læs den som "hvad vi ville dengang", ikke som en plan der
> gælder.

> **Status:** Gul. Backend er sikkerhedshærdet, versionsdrift mekanisk lukket, og
> **apparatdriften er bygget** (supervisor med autostart + crash-restart, updater med
> rollback, ressource-varsling — 1.58.8–1.58.14). Fokus nu er **integration + hardening**,
> ikke nye capabilities. Klient- og privacy-integrationen er nu i høj grad lukket (chained-writes
> ✅, local-first default ✅, Android credential-kryptering + backup ✅, **desktop-credentials
> med Windows DPAPI ✅**, checksums ✅); tilbage står primært RAG→cloud state-machine (#2a) og
> **validering på hardware** + klient-fixes — ikke backend-kode.
>
> Kompakt Now/Next/Later. **Vedtaget 13/7-2026**; afløser den gamle sprawlende roadmap,
> hvis fulde V1–V15-historik nu ligger i `HISTORY.md` (intet slettet). Autoritativ version
> er altid `VERSION`; sikkerhedsbaseline + accepterede risici i `SECURITY.md`.

---

## Retning — vedtaget 18/7-2026 (afløser Now/Next/Later nedenfor)

Den strategiske analyse (1.58.107) fandt kerneproblemet: en **hardening-treadmill**
hvor evidens er code-bound, så hver mikrorelease ugyldiggør den validering ingen
endnu har kørt. Modenheden siger det med to tal — sikkerhedsarkitektur 8.6/10,
fysisk bevis 3.2/10. Al maskineriet er bygget omkring noget der aldrig er trykket
på. Retningen herfra er derfor **bevis og promotion, ikke mere bred kode**, i denne
faste rækkefølge. (Dette er en plan; hvor tingene faktisk *er*, står i
`CURRENT_STATE.md`, ikke her.)

1. **Prove** — frys en kandidat, kør preflight, kør den fulde fysiske
   appliance-validering (Agent 3 + scheduler + Ollama + RAG + Windows + Tailscale +
   klient), og bevis reboot/supervisor/updater/rollback. Frys lokal model-eval-,
   voice- og RAG-baselines. **Intet promoveres før dette er grønt.** (T-004→T-007)
2. **Scheduler** — gør execution-truth durable: occurrence-ledger, atomisk
   claim+budget, bind job/audit/outcome/recovery, grant-revision/revoke/overlap,
   fault-injection + readiness-gate. Så fysisk read + `note_append`-pilot.
   (T-010→T-019; [KERNE]-delen leveret 18-19/7 i 1.58.116–123 inkl.
   approval-receipts — tilbage: den fysiske pilot T-019 og P2-opgaverne
   T-017/T-018, se `BACKLOG.md`)
3. **Agent 3-pilot** — read-only developer-pilot med telemetry og instant fallback,
   promotion-gate + normal task-UI, derefter append-only write-pilot. Mål task
   success frem for mere dormant hardening. (T-020→T-023)
4. **Capabilities** — canonical CapabilityDescriptor, egress-beslutning, og så
   10–15 konkrete Anders-workflows: web/research med citations, scoped files,
   GitHub, connectors, RigGate. Shell/computer-use sidst, efter I0b-isolation er
   bevist. (T-030→T-038)
5. **Product** — Kaliv Control Center: én flade for health, routing, permissions,
   jobs, schedules og audit. Voice- og RAG-kvalitet målt og optimeret. (T-040→T-044)

Målet efter sekvensen er ikke flere features, men **10–15 workflows der faktisk
bliver afsluttet stabilt af Kaliv**. Den fulde, prioriterede nedbrydning ligger i
[`BACKLOG.md`](BACKLOG.md).

---
## Vision

Lokal AI-platform der giver en Claude-lignende oplevelse med lokale open source-modeller
via Ollama. **Backend er eneste gateway** — klienter taler aldrig direkte med en
model-runtime. Slutbilledet er et **apparat**, ikke et evigt projekt: Kaliv starter,
overvåges og gendanner sig selv, og featuretoget stopper bevidst.

## Produktprincipper / invarianter

- Lyd forlader aldrig huset (ASR + TTS lokalt; cloud kun til LLM, eksplicit valgt).
- **Alle *model-initierede* writes går gennem workerens confirmation gate.**
  (IKKE "alle writes på platformen" — modelsletning m.m. er klient-bekræftet. Se D3.)
- Alt lokalt og sletbart. Ingen automatisk cloud-fallback (beskytter "100% lokal").
- Tailscale (WireGuard) er eneste sanktionerede remote-transport; rå LAN = accepteret
  risiko (`SECURITY.md`).
- Kun Windows + Android. CI bygger ikke Linux/macOS-desktop.

---

## NOW — Stabilisér & sikker baseline (1.58.x)

**Mål:** Seneste main er dokumenteret, versions-konsistent, sikker som baseline, og de
kendte on-device-tests har et registreret resultat.

| # | Leverance | Status / Acceptkriterium |
|---|---|---|
| N1 | Én VERSION-kilde + CI-gate | ✅ **Gjort.** `VERSION` + `version_tool.py` (sync/check); CI `version-check` gater build på tag- og site-match. |
| N2 | Committet signeringsnøgle | ✅ **Risiko accepteret** (`SECURITY.md`): solo/sideload, ingen store, appen taler kun mod egen backend. Ingen rotation nu; revurderes hvis appen distribueres bredt. |
| N3 | Synk docs → 1.58.2 | Delvist ✅: `VERSION`/`ROADMAP`/Notion aktuelle; `STATUS`/`HANDOFF` har banner der peger på autoritativ tilstand (historiske logs bevaret). |
| N4 | Security baseline | ✅ **Gjort.** `SECURITY.md`: trust boundaries, credentials, accepterede risici, defaults, rotation/incident. Desktop-hemmeligheder er DPAPI-beskyttet og legacy-klartekst migreres fail-closed. |
| N5 | De 5 on-device-tests | ⏳ **Afventer (Anders tester i dag):** streaming-voice S1–S4, desktop 1.58 mod designguide, samtale-eksport/import. |
| N6 | Bevist backup/restore | ⏳ Afventer rig. (CI kører allerede `worker_backup.py` round-trip pr. release — men ikke bevist på selve riggen.) |
| N7 | Model-eval baseline | ⏳ Afventer rig: `qwen3:14b` + baseline via eval-harness (MODELS.md har kommando + kriterier). |

**Exit:** CI grøn · versionskilder matcher (gaten håndhæver) · ingen P0/P1 uden dokumenteret
risikoaccept ✅ · de 5 device-tests har resultat · recovery bevist på riggen.

---

## NEXT → I HØJ GRAD BYGGET — "Kaliv som apparat" (1.58.8–1.58.14)

**Mål:** Kaliv starter, overvåges og gendannes uden manuel terminaldans.

Bygget: `modelrig-supervisor` (autostart ved logon via Task Scheduler · genstart ved crash/
unhealth · logrotation · egen supervisor-log · indlæser `modelrig.env` til børnene) ·
`modelrig-updater` (backup + swap + **auto-rollback**, verificerer BÅDE backend og worker) ·
disk/VRAM-varsling (off watchdog-path, med timeout). Auto-backup fandtes i forvejen.

**Udestår:** (a) **on-device-validering** af hele matricen (reboot→brugbar · kill-proc→genstart ·
korrupt release→rollback); (b) **executable-supply-chain** — SHA-256-verificeret (1.58.15: release publicerer
`SHA256SUMS.txt`, updateren tjekker før swap); næste niveau = signeret manifest; (c) diskchecket måler
kun supervisorens drev; (d) TLS/reverse-proxy-politik.

**Exit:** *Sluk strømmen, tænd igen → Kaliv er brugbar uden manuel processtart. En dårlig
opdatering kan rulles tilbage.* — kode findes; **mangler on-device-bevis + supply-chain-integritet.**

---

## NEXT — Voice & agent-pålidelighed

**Mål:** Stabil samtaleassistent *før* hun bliver "ambient".

Leverancer: afslut streamende voice-validering (**mål TTFA**, ikke "føles hurtigere") ·
streaming-ASR · voice-tools m. eksplicit mundtlig bekræftelse · eval-baseline for lokal
model · cloud-agent-test · **beslut privacy-regel for RAG + auto-cloud** (D4) før evt.
automatisk routing.

**Exit:** voice-turn stabil 10× i træk · stop/barge-in efterlader intet hængende · agent
slår baseline på tool-disciplin · cloud-routing er synlig + følger skreven privacyregel.

**Kendt åbent issue:** voice 501 / Piper-TTS (diagnose kører på riggen).

---

## LATER — Udvidelser med konkret brugerbehov

- **Knowledge/vision:** visionmodel på riggen · dansk foto-chat · samtaler som valgfri
  RAG-kilde · dedup + embedding-versionering · skaleringstest før vector-DB.
  *(Foto→RAG-plumbing er færdig; resten er primært model-/hardwarevalidering.)*
- **Integrationer:** Home Assistant read-only → writes m. confirmation gate · scheduler for
  read-only jobs · eksternt API m. scoped credentials + transportbeskyttelse.

---

## NOT NOW — betingede horisonter (aktiveres kun ved målt behov)

- **Multi-device** ≠ **multi-user.** Flere enheder til dig er lille (store'et har allerede
  device-liste + token-hashes + revocation → mangler mest 2-klient-test + delt/separat
  historik-beslutning). Flere *personer* m. isolerede data er et stort nyt sikkerheds-/
  datamodelspor — betinget af faktisk husstandsbehov.
- Egen finjusteret model (kun ved målt modelproblem + grund til ikke at bruge cloud).
- Føderation/split-rig, dedikeret Kaliv-station, e-ink-display — betinget af målt
  strøm-/availability-behov.

---

## Tværgående kvalitetsporte (gælder hver leverance)

Funktion bevist (ikke bare implementeret) · nye fejlklasser har regressionstest · trust
boundary/credentials/writes vurderet · health/logs/recovery beskrevet · migration/backup/
rollback vurderet · relevant latency/ressource **målt** · hardware-test ved UI/device-
ændringer · kun aktuelle docs opdateres · artefakter findes + versioner matcher (CI-gate) ·
ikke-verificerede dele mærkes eksplicit.

**Mål med tal (erstat "virker"):** tekst-TTFT · voice-TTFA · RAG p95 @ 1k/10k chunks ·
koldstartstid · maks RAM/VRAM · succesrate over 10–20 gentagelser · restore-tid · antal
manuelle trin efter genstart.

---

## Åbne beslutninger (kræver Anders)

- **Research-sporet:** `research_contract` + `research_egress` +
  `research_peer_binding` (1.564 linjer, 8 testfiler, nul produktionskaldere) er
  en **vedtaget tillidsgrænse uden adapter** — modulets egen docstring siger at
  en fremtidig BrowserUse/Playwright/HTTP-adapter skal opfylde kontrakten *i
  stedet for selv at definere hvor grænsen går*. Beslutning: markér statussen i
  koden, så den ikke læses som forfald. (Ikke: om den skal skæres væk — man
  skærer ikke en tillidsgrænse væk fordi den mangler en bruger.)
- **1.0:** anbefaling er at tagge `v1.0.0` på `1.58.146` umiddelbart efter
  rig-dagen. 1.0 har konsistent betydet *"apparatet er bevist på hardware"* i
  hele roadmap'en, og det er præcis hvad rig-dagen afgør.

*Afgjort 25/7-2026:*

**D3 — Write-invariant: klient-bekræftelse bevares på bruger-admin-stien.**
Der er to veje til en destruktiv handling, og de er bevidst forskellige:
*model-initierede* writes går gennem ToolGate og kræver et bekræftelseskort
(`requires_confirmation`: `risk in ("write","desktop")`); *eksplicitte
bruger-admin-kald* (`DELETE /api/v1/models/delete`) er bearer + klient-bekræftede.
Invarianten skrevet ud: **server-side gates beskytter mod at MODELLEN handler
uden dig — ikke mod at nogen har dit enhedstoken.** Tokenet ér autorisationen
for dine egne admin-handlinger; rotation er svaret på et lækket token. En
server-gate på brugerstien ville tilføje friktion mod den forkerte trussel: har
nogen dit token, er slettede modeller ikke det største problem — de kan læse
dine dokumenter gennem RAG. **Genbesøges hvis appen distribueres bredere end én
ejer.** Se `SECURITY.md`.

**D4 — Automatisk routing må ALDRIG sende RAG-kontekst til en cloud-model.**
Reglen gælder en feature der ikke findes endnu (auto lokal/cloud-routing;
`ChatRouter.autoFallback` er `false`, og `autoCloudFallback` er off som default
i begge klienter). Samtykke kan kun komme fra to steder: eksplicit
`allow_rag_cloud` på requesten, eller operatørens `KALIV_ALLOW_RAG_CLOUD`. **En
router må aldrig være den tredje.** Begrundelse: produktet bæres af *"lyd
forlader aldrig huset"*, og dens søster er *"dine dokumenter forlader ikke huset
uden at du siger ja"* — en automatisk router er per definition et sted hvor du
ikke sagde ja. Konsekvensen accepteres bevidst: matcher RAG, bliver turen lokal,
også når det er langsommere. **Håndhævet som test**
(`tests/worker_d4_auto_routing.py`), ikke kun som prosa — en regel der kun står
i et dokument driver, og den her ville drive mod "det var vel også i orden".

*Afgjort 13/7-2026: **D1** keystore = risiko accepteret (`SECURITY.md`) · **D2** VERSION-kilde
+ CI-gate = leveret · **D5** dokumentstruktur = lean (denne fil + `STATUS.md` + `SECURITY.md`)
· ROADMAP_V2 vedtaget.*

---

## Afhængighedsrækkefølge

```
Sikker baseline (NOW)
  → Apparatdrift (NEXT)
    → Voice/agent-pålidelighed (NEXT)
      → Ambient/proaktiv + integrationer (LATER)
        → betingede horisonter (NOT NOW)
```

Faser navngives ved **navn** (Baseline, Apparat, Voice, Agent, Integrationer) — ikke
V-numre — så de ikke forveksles med SemVer (`v1.58.2`). Softwareversion forbliver SemVer.
