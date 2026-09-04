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
> (Denne header pegede på `ROADMAP.md` og `SECURITY.md` som autoritet. Begge var
> selv driftet — ROADMAP siden før Agent 3 og scheduleren overhovedet fandtes.
> Dokumentet der skulle afgøre tvivl, henviste til dokumenter der tog fejl.)
> 13/7-2026: audit-P0/P1 lukket (1.58.1/1.58.2); VERSION-kilde + CI-gate indført; roadmap fornyet.

# ModelRig / Kaliv — komplet handoff til ny chat

**Repo:** `github.com/Ternedal/ModelRig` (**PUBLIC** — gratis CI) · **Version:** se `VERSION` eller `CURRENT_STATE.md`

*(Her stod "Version: v1.58.52" i et hjørne hvor ingen kigger. Et versionsnummer
skrevet i hånden i en header er ikke information — det er en tidsindstillet
usandhed, og den her var 29 releases gammel.)*

Copy/paste dette som første besked i en ny chat. Dokumentet er selvbærende:
det dækker beslutninger, tilstand, arbejdsform, release-flow, toolchain,
arkitektur og lektier. Ved tvivl om **beslutninger**: dette dokument vinder over
hukommelse og antagelser. Ved tvivl om **tilstand**: de genererede sider vinder
over dette dokument.

---

## 0. AFGJORTE beslutninger — genåbn dem IKKE

Disse er truffet af Anders og står ved magt. En ny session skal IKKE flagge
dem, minde om dem eller starte en diskussion om dem.

1. **Tokens/PAT ligger i Notion — Anders VED det.** PAT'en (og øvrige tokens)
   er gemt i Notion og skal på et tidspunkt revokes/roteres. **Det er Anders'
   opgave, på Anders' tidspunkt.** Ingen påmindelser, ingen "akut punkt 1",
   ingen ny diskussion — dette afsnit ER kvitteringen for at det er kendt.
   Den eneste stående, operationelle regel: **masker altid tokens i output**
   (release-flowets `sed 's/[A-Za-z0-9_]\{20,\}/***/g'`-mønster) og brug
   origin-URL'ens indlejrede PAT som den er.
2. **Keystoren + passwords ligger i det offentlige repo** (`android/signing/`,
   committet v1.10.1 mens repoet var privat; repoet blev senere public).
   **Risiko ACCEPTERET af Anders 12/7.** Rationale: personligt projekt; der
   installeres udelukkende APK'er fra egne releases. Rotation ved en naturlig
   geninstallations-lejlighed (samtale-eksport findes nu, v1.56.0, så det
   koster ikke data). Fjern den IKKE — CI signerer hver `kaliv-latest.apk`
   med den. Stående regel: kun egne releases; rotér hvis reglen brydes.
3. **Navne:** kun BACKEND hedder ModelRig (server/worker/repo/API/exes).
   ALT brugervendt hedder **Kaliv**. `applicationId dk.ternedal.modelrig`
   er permanent og må ALDRIG ændres. ALVA_*-env-navnene er bevidst uændrede.
4. **qwen3:14b er primær rig-model** (bekræftet on-device 12/7: kender
   identitet + tools). Kendte model-svagheder (IKKE app-bugs): dropper
   bindestreger, hallucinerer dansk faktaviden, ignorerer emoji-forbud
   (→ deterministisk klient-strip). hermes3:8b er fallback.
5. **CI bygger KUN** Windows-jar + Android-APK + 2 Windows-exes (6 assets).
   Ingen Linux/macOS-desktop-builds — Anders kører Windows + Android.
6. **Notion-MCP må ALDRIG kaldes uopfordret.**

---

4. **Computer-use ER en del af pakken** (Anders, 16/7). Lokal PC-styring
   først, browser senere; placeret EFTER Agent 3 + valideringsrunden; og
   **isolation løses FØRST** (ISOLATION_DESIGN.md). En tidligere session
   anbefalede at droppe computer-use som kategori-brud — **den anbefaling er
   trukket tilbage og skal ikke genfremsættes**: lokal, gated, single-machine
   computer-use er kategori-KONSISTENT. Diskuter rækkefølgen hvis der er data,
   men ikke om.

**Operationel skærpelse (16/7):** maskerings-mønstret `[A-Za-z0-9_]\{20,\}`
æder også flagnavne, testnavne og SHA'er over 20 tegn. Brug det til blinde
push/tag-kommandoer, men **`sed 's/github_pat_[A-Za-z0-9_]*/***REDACTED***/g'`
når du skal LÆSE tool-output** — ellers redigerer du din egen evidens væk.

10. **Agent 4's arkitektur er fastlagt** (30/7). Se
   `AGENT_4_ARCHITECTURE_DECISIONS.md` for de gældende arkitekturbeslutninger
   og CI-gates. Den fil er den autoritative kilde — gengiv ikke
   beslutningerne her.

**Tre beslutninger truffet af Anders 30/7 — genåbn dem ikke:**

7. **D7 trin 1 = et ToolGate-værktøj.** Henterens produktionskaldested er
   `web_research` i workerens `REGISTRY`, ikke et nyt endpoint og ikke en
   RAG-sidevej. Gaten er den eksisterende flade-gate
   `KALIV_WEB_RESEARCH_ENABLED` — ét navn for én flade. Rig-dagens form er
   **(c)**: scriptet frosset som `.retained` plus ét separat produktionskald
   mod en rigtig URL. **Landet 30/7** (se §9).
8. **`#163` lukkes; desktop-sporet reddes separat.** Research-delen er
   supersederet, og branchens `capability_schema`-ændring ville tavst
   genindføre den forkastede `external`-adgangsklasse. De 12 desktop-moduler
   + 11 testfiler (Computer Use I3/I4) løftes i en frisk branch mod main —
   kun A-filer, versionsrodet fladet ud undervejs. Milepælen defineres i
   ROADMAP; navnet `F5` genoplives ikke.
9. **Android-palettens divergens er et bevidst platformsvalg.** Forskellen i
   mætning (29,5 % mod 9,4 %) pinnes med dokumenteret override i token-laget
   plus test, så velmenende oprydning ikke kan slette den tavst. Det
   æstetiske valg træffes på rig-dagen med begge apps foran sig.

---

**Truffet af Anders 1.–16./8 — genåbn dem ikke.** ADR'erne er autoritet;
de gengives IKKE her (A4-005's stopregel gælder ogsaa for denne fil):

11. **ADR-A4-007** (1/8, #319) — Agent 4's operator-read: worker-hostet,
    KUN backend-proxied, paired-device Bearer + eksplicit `agent4:read`-grant
    pr. enhed, fraværende by default. Implementeret i baade worker og backend.
12. **ADR-A4-008** (1/8, #324, præciseret i #329/#330) — side-effect handoff.
    Fuldt implementeret 2/8 i fem slices (#331–335), alt fortsat DORMANT.
13. **ADR-DC-001** (5/8, #349) — DevControl: fail-closed autoritetskæde for
    kontrolleret selvudvikling. Menneskelig terminal autoritet kan ikke
    delegeres; dvale BEVISES af gate; aktiveringsport kræver sin egen ADR.
    **Sol ejer `devcontrol/`** (5/8, #350).
14. **ADR-A3-001** (15/8, #598, `docs/agent3/`) — chattens adgang til Agent 3.
    Smal åbning: kun eksplicit igangsættelse, kun READ-planer, godkendelser
    og checkpoints bliver paa den dedikerede skærm. Aktiverer ingenting.
15. **Redesign-rammen** (12/8, issue #518) — fire kontrastroller til AA;
    px→dp uniform x1,2205; `GET /api/v1/system/status` i Go-backenden;
    2.0.0 tagges når fase 3 er komplet; M3-komponenter med tokens.
    DDR-001 i `docs/design/` er designautoritet efter ADR-mønsteret.
16. **1.0.0 er udelukket som version** — updaterens `isNewer` afviser et fald
    fra 1.58.x. Derfor gik vejen til 2.0.0.
17. **De ti "designforslag"-skærme er vurderet** (16/8). Bygget: Del til
    Kaliv, Svar-citater, Onboarding, Offline-kø. Droppet: Splash,
    Model-hurtigskift, Tænke-tilstand (riggen har FASER, ikke modellens
    tanker — en tankestrøm ville være attrap). Afventer: Eksport & backup,
    KalivDev.

---

## 1. Hvad projektet er

Anders' personlige, selv-hostede AI-platform ("Local AI Control Surface"):
Ollama-modeller på egen Windows-rig (RTX 3060 12GB), nået fra **Kaliv**
(Android, Pixel 6a) og **Kaliv Desktop** (Windows, Compose JVM). Dansk voice
(ASR→LLM→TTS, streamet sætning-for-sætning), RAG-ingest (pdf/docx/pptx/html/
foto), bekræftelses-gatet tool-lag, og valgfri Ollama Cloud-hjerne. Telefonen
når riggen via Tailscale: `http://100.88.91.64:8080`.

Succes = pålidelig, testet on-device-oplevelse med rene CI-verificerede
releases. Kadence: MVP → V1 → V2; roadmap er lukket-endet ved V15.

---

## 2. Tilstand — hvor sandheden bor

Håndskrevne docs må ikke påstå aktuel tilstand (F-516) — den rådner. Den bor i:
- `CURRENT_STATE.md` (genereret: version, hvad der er koblet)
- `ACTIVATION_READINESS.md` (genereret: Agent 3- og scheduler-verdicts;
  scheduler-delen kører 7 durability-prober LIVE mod rigtige komponenter ved
  hver generering — prober der er bevist ikke-blinde via sabotage-selvtests)
- `BACKLOG.md` (planen, med leveret-markører og versionsnumre — historik er
  sand for evigt)
- `tests/`-globben (kør den; skriv aldrig faste tal i docs — F-008)

**Hardware-bekræftet (pr. 12/7, uændret):** PDF/DOCX→RAG · dansk TTS+ASR (CUDA
large-v3) · voice ende-til-ende inkl. via-cloud · barge-in/tap-to-stop ·
agent-laget (læs + skriv bag bekræftelseskort, audit) · rig-model-skifter ·
streamende voice.

**Varige arkitektur-fakta (dyre at genopdage — alle CI-verificerede, IKKE
hardware-beviste før valideringsrunden):**

- **Scheduler-leveringsmodellen (bygget 18-19/7, 1.58.116–130):** execution-truth
  er durable fra claim, ikke fra finish. `occurrences`-ledger: claim skriver
  durable række + reserverer budget-slot i SAMME transaktion som due_at-advance;
  claim_id binder job, audit, outcome og recovery. Recovery er evidensbaseret —
  audit-conversation `schedule:<sid>:occ:<claim_id>`, outcome='executed' holder
  slotten brugt, ellers abandon+refund; den blinde store-recovery er FJERNET (én
  kanonisk sti). Revision-guard umiddelbart før ToolGate: `set_enabled` bumper
  BEGGE veje, `renew` bumper også (fingerprint for samme tool+args er
  byte-identisk efter renew — kun revisionen afslører et stale claim).
  Approval-receipts: hver konsumeret godkendelse (create/renew) persisterer
  device_id/nonce/issued_at/consumed_at/revision i samme tx som granten; en
  grant med menneskelig godkendelse kan ikke eksistere uden sin receipt.
  `GET /schedules/{id}` viser historikken.
  **Det ukendte vindue (F-1002, 1.58.126 — RETTELSE af en tidligere
  dokumenteret invariant):** runneren skriver en durable attempt-række
  umiddelbart før propose; recovery skelner tre dødsfald: intet attempt →
  refund; attempt+executed → behold; attempt alene → UKENDT, hvor slotten
  BEHOLDES og granten pauses (refusion var hvordan max_runs=N blev N+1
  reelle writes — den gamle "undertælling foretrukket"-sætning her var
  forkert). Unknown+pause er ÉN transaktion (F-1204). **Owner-lease
  (F-1003/F-1202/F-1203, 1.58.126+129):** recovery og tick kræver lease;
  service-heartbeat (ttl/3) holder den forbi lange kørsler; stop drainer FØR
  frigivelse og frigiver IKKE ved join-timeout (TTL er fallback).
  **max_runs-claim-splittet (1.58.128, levende P1 fra 116):** claimede
  snapshots inkluderer reservationen — refusal på claim-stien må ikke bruge
  stored-`>=` (max_runs=1 afviste ellers sin egen første kørsel).
  **Freeze-gaten er fail-closed (1.58.127):** FROZEN kræver token +
  ci+codeql grønne på exact head. **Kampagnens scheduler_pilot-slot
  (v2, 1.58.129):** forensisk — pinner occurrence/job/audit-sekvens
  (claim→attempt→executed)/receipt/tidsvindue direkte fra storene.
  **Recovery-linjen er synlig fra 1.58.130:** root-loggeren har ingen
  handler under produktions-launchen, så alt under WARNING forsvandt —
  scoped fix i scheduler_lifespan (fundet ved fuld sandkasse-generalprøve
  af §1.6-kæden, hvor recovery kørte perfekt og sagde intet; token-mint
  kræver v:1 + ALLE previewede vilkår, og aggregatorens
  path-escape-guard beviste sig selv).
  **Evidens-integritetskæden (1.58.132, svar på helanalyse-gap-droppet
  F-1301..F-1327):** gitless FROZEN binder det lokale ZIP-træ til
  release-committen fil-for-fil (git/trees-API, blob-sha'er); attestationen
  er v2 i ÉT delt modul (`scripts/frozen_attestation.py`) som writer og
  begge læsere håndhæver — strict schema, version-pin, 24t-freshness,
  offline tamper-evidens via genberegnet worker-fingerprint (fem
  forfalsknings-mutationer + ZIP-tamper testet røde). Schedulerpiloten er
  v3: manifest-bundet mod §1.6 (exact read-spec, write-tool), komplet
  inventar i pilotvinduet (unlisted plan = rød), claim-bundet executed.
  Runbookens falske model_eval-blocker er fjernet med doc-parity-checks i
  doc-gaten. Freshness (1.58.133): pilot-forensik ≤24t fra generated_at,
  producer + validator uafhængigt — replayede pilot-IDs dør på begge. Agent3-ps1'en (`run-agent3-rig-validation.ps1`) er auditeret
  OK: token-krav, backend-stier, report_sha256-binding og
  production_activation-vagt matcher koden. **Dens harness-afhængighed
  havde derimod hullet (1.58.134):** build_memory_router var TREDJE
  orphaned router (mount → planner → memory) — harnessen kalder tre
  memory-ruter som produktions-entrypointet aldrig mountede (dev-
  runnerne byggede dem selv: dev/prod-divergens). Mountet ejer nu
  store+router (KALIV_AGENT3_MEMORY_DB-konventionen); wiring-suiten
  kræver trioen. Audit-metoden: harnessens KOMPLETTE rute-kontrakt mod
  openapi-tabellen — app.routes-iteration er blind for includes.
  **Samme audit ét ring ud (1.58.135):** appens kontrakt afslørede fjerde+
  femte orphan (/capabilities-skærmen og replan-preview-flowet 404'ede i
  produktion) OG at runnerens rige planner var stille skygget af mountens
  bare fra 131 (first-match). Mountet ejer nu HELE surfacen; runnerne
  tilføjer intet. Princip: dev serverer præcis hvad produktion serverer.
  **Evidens-kæden strammet igen (1.58.137, gap-136-droppet F-1501..F-1536):**
  bytecode (.pyc/__pycache__) er nu FAIL i freeze i begge modes (readerne
  sætter dont_write_bytecode så de ikke selv-detonerer på rig-dagen); de
  offline læsere geninventerer træet og afviser filer TILFØJET efter freeze
  (ikke kun ændrede); kampagne-validatoren håndhæver per-halvdel freshness +
  12t-spænd uafhængigt af produceren; git-mode kræver HEAD == publiceret
  tag-SHA. Generalprøve mod ægte 136-ZIP afslørede bytecode-selvdetonering
  og git/gitignore-hullet — ting hverken statisk analyse eller suiten fandt.
  **Gap-drop mod 133 lukket i 1.58.136 (F-1402..F-1405 + 1407/1426/1431):**
  extras = FAIL i gitless freeze; attestation v3 med fuldt træ-rollup
  (offline tamper-evidens for HELE træet, ikke kun worker/) + exact key
  set; kanonisk pilot-write pinnet exact med receipt↔grant-binding
  (fingerprint/revision); freshness pr. halvdel + 12t samlet vindue +
  execution-inventar (foreksisterende planer der fyrer fanges). Schemas:
  attestation v3, pilot v4 — begge fail-closed mod ældre filer.

**Bygget 12-14/7 (samme forbehold):**
- **Substrat:** JobStore (persistent, terminal sandhed, cancel, restart→
  interrupted) · ToolHost I0a (procesgrænse, timeout-kill, output-cap,
  credential-fri child-env, frozen-exe child-mode) · Tier B policy I0c
  (screenshot-binding, fail-closed allowlist, rate limit, lokal-model-only).
  **Alt dormant** — `KALIV_TOOL_ISOLATION=process` + `Tool.isolate`, og ingen
  tools sætter dem.
- **Ren logik med tests (Android):** `logic/TurnRouter` (rute; send+retry samme
  kilde) · `logic/StreamContract` (typed events; EOF ≠ succes) ·
  `logic/TokenFormat` (profil-migration; korrupt `enc:v1:` bliver ALDRIG
  plaintext).
- **Hærdning:** ydre ASGI byte-cap (chunked kunne omgå Content-Length) ·
  single-writer pairing · fail-closed desktop-streams · RAG-stream efterlader
  altid en årsag · deps pinnet `==` + actions SHA-pinnet + Dependabot + CodeQL.
- **Samtykker er VIRKELIGE** (1.58.45): `allowRagCloud` var et dødt
  `remember{false}` — D4-samtykket kunne bogstaveligt ikke gives. Nu
  persisteret + to toggles i ⋮-menuen.
- **Release-flowet beskytter sig selv:** `ensure-draft-release` er eneste
  create-autoritet (draft-only); build-jobs havde `gh release create || true`
  **uden --draft** = halvpublicerede releases. Kontrakt-testet.

**Kontrakt-tests (nye klasse af sikkerhedsnet):** `tests/workflow_release.py`
(release-synligheden) · `tests/workflow_agent3_dormant.py` (**gate 3 — ligger
på main, så Agent 3-mergen gates automatisk**) · `tests/workflow_test_coverage.py`
(ingen test kan gemme sig for CI's glob). Alle med selv-tests: de er drevet mod
syntetiske overtrædelser, fordi en test der kun kan bestå ikke er en test.

**Tests:** kør dem — `tests/`-globben er sandheden. Hold op med at skrive faste
tal i docs (det var F-008: README påstod "298 tests" med en opdeling der ikke
matchede nogen fil).

---

## 3. Arbejdsform med Anders

- **Svar på dansk.** Koncist, ærligt, direkte. Ingen falsk sikkerhed.
- **Skeln verificeret / kvalificeret antagelse / gæt.** Sig hvad der ikke er
  testet. Standard-forbehold på UI: "verificeret ved build, ikke med øjne".
- **"kør" / "kør videre"** = fuld autonom eksekvering uden check-ins, med
  fuld commit-autoritet. **"test jeg"** = Anders tester på hardware.
- **Anders kører FLERE parallelle Claude-sessioner.** Derfor: `git pull
  --rebase` før alt arbejde, tjek version-sites for kollisioner, og forvent
  at en anden session kan have tilføjet det samme (skete med
  voiceCloudModel — dup fjernet, UI wired ovenpå).
- **Ærlig modstand er ønsket.** Sig fra når noget ikke kan bygges meningsfuldt
  uden Anders' test eller beslutning — det har flere gange været det rigtige.
- **MVP → V1 → V2.** Byg smalt, bevis, udvid. **DKK** ved priser;
  København/Nørrebro som kontekst.
- Ret aldrig noget "efter øjemål" når der findes en autoritativ kilde
  (design-tokens, fejltekster, docs) — og læs fejlteksten FØR du fikser.

---

## 4. Release-flow (ATOMISK — bevist 15+ gange, følg det præcist)

**Det gamle "POST release med make_latest:true" er DØDT.** Det publicerede en
tom release som CI derefter fyldte progressivt: hvis noget fejlede, stod der en
halv release og lignede en hel. Flowet nu:

0. **FØR noget som helst: tjek om arbejdet allerede er gjort.**
   `git reflog` + `git ls-remote --tags origin`. FEM af 2.0.x-releasene var
   allerede fuldført af et timeout't tvillingeforsøg da en session begyndte
   paa dem. Der er EEN session — uventet arbejde er typisk dit eget.
1. `git fetch` FØRST og vælg version over origins `VERSION` (parallelle
   sessioner!) → `python3 scripts/version_tool.py set X.Y.Z` (synker de fire
   KODE-sites) → **`versionCode` = origins + 1** (slå det op i origins
   build.gradle.kts — skriv ALDRIG et fast tal her, F-008) →
   `python3 scripts/version_tool.py check`.
   **`version_tool.py` er ikke hele bumpet.** Versionen står OGSAA i
   `CURRENT_STATE.md`, `ACTIVATION_READINESS.md`,
   `scripts/agent3_write_pilot_current_main.py` og
   `AGENT3_WRITE_PILOT_CURRENT_MAIN.md`. Regenerér med
   `python3 scripts/current_state.py`, `scripts/activation_readiness.py` og
   `scripts/route_inventory.py` (sidstnævnte prober WORKERENS OpenAPI — nye
   backend-ruter alene drifter den ikke). Springes de over, står bumpet rødt
   paa test/exact-head, ikke paa selve versionen.
2. Kør ALT lokalt: `(cd worker && PYTHONPATH=. python3 ../tests/worker_*.py)` ·
   `(cd backend && go build ./... && go vet ./... && go test ./...)` ·
   `python3 tests/workflow_*.py` · `ruff check --select E9,F63,F7,F82`.
   **Kotlin kan IKKE kompileres her — CI er den eneste verifikation.**
3. **Alt landes gennem CI — ikke ved push til main.** Arbejdet ligger paa
   en gren, får sin PR, og landingen er et fast-forward af
   `refs/heads/main` EFTER grønt run paa den NYESTE sha. Verdiktet er en
   HAARD betingelse INDE i landingsscriptet: check-runs paa præcis den sha,
   alle `completed`, nul `failure` — ellers exit FØR patch. Verdikter
   håndhæves, aldrig kun rapporteres (#315 landede paa rød CI med en falsk
   grøn kommentar). **CHECK-RUNS ≠ WORKFLOW-RUNS:** fire grønne workflows
   kan staa ved siden af et rødt CodeQL-check-run. Gate paa BEGGE.
   Bekræft ad TO veje (`ls-remote` + REST med retry) FØR PR'en lukkes, og
   lad lukningen ligge INDE i den bekræftede gren af scriptet — en
   ';'-kædet lukning fyrer på falsk bekræftelse. `scripts/stale_check.py`
   før enhver merge. Først når main står paa din sha gælder resten:

   `git add -A && git -c commit.gpgsign=false commit -q -F /tmp/m.txt` →
   `git fetch -q origin main && git rebase origin/main` → **STRAM PROTOKOL
   (indført 18/7 efter to fejlplacerede tags):** tjek
   `[ -d .git/rebase-merge ] || [ -d .git/rebase-apply ]` — står rebasen åben,
   abort og løs; push ALDRIG fra den tilstand ("Could not apply" efterlader
   HEAD på origins tip, og merge-base "bekræfter" så trivielt DERES commit).
   Efter push: `git merge-base --is-ancestor $MYSHA origin/main` OG
   `$MYSHA != origins gamle tip` — først DA må der tagges.
4. **Opret releasen som DRAFT via API** (`"draft": True`) — aldrig public.
5. **Push tagget SEPARAT** (`git tag vX.Y.Z <sha>` + push) — og KUN mod din
   egen merge-base-bekræftede sha (pkt. 3). GitHub laver ikke tags for drafts,
   og CI trigger på tagget. Fejlplaceret tag: slet lokal+remote
   (`:refs/tags/vX`), slet evt. release/draft via API (DELETE giver 204 = tom
   body), ryd op, start forfra.
6. CI's `ensure-draft-release`-job er **eneste create-autoritet** (og tvinger en
   public release tilbage til draft). Build-jobs uploader; release-jobbet
   verificerer asset-listen og publicerer **som sidste step**
   (`--draft=false --latest`).
7. Poll autentificeret med bounded sleeps (≤250s):
   `?head_sha=<full-sha>` for ci/codeql, `?branch=vX.Y.Z` for release-runnet.
   **Mellemlæsninger kan vise 5 assets — det er upload-racet, ikke en fejl.**
   Afvent `completed`. Forventet: **9 assets** (2 APK'er, JAR, 3 exe'er, zip,
   SHA256SUMS, +1). **Modstridende API-læsninger (404 på by-tag, "1 draft",
   forkert latest) er eventual consistency i publiceringsøjeblikket — mål igen
   før du konkluderer.** End-tjek altid: drafts == 0 (slet leftovers — CI
   publicerer sin egen; din API-draft kan hænge).
8. **Docs/CI-only = commit uden bump/tag/release.**
9. **Efter hver release: post status til Notion** (side
   `389e6b11-bf7b-812f-89ba-fc17e3c2dcda`, dateret entry + Version-property).
   Stående ordre, spørg ikke først. *(Rettelse 17/8: den tidligere note her
   sagde at connectoren havde været nede siden 16/7 og bad en fremtidig
   session om at poste en samlet 1.58.116→130-status "som det første".
   Connectoren virker, og den backlog er for længst overhalet af 2.0.x.
   Noten er fjernet frem for at staa og pege paa et arbejde ingen skal lave.)*
10. **En dårlig release når telefonen af sig selv nu.** Fra v2.0.2 har
    appen en in-app-updater: den læser `/releases/latest`-redirectens
    `Location`-header (ingen API, intet token), henter `kaliv-latest.apk`,
    sammenligner strengt semver og tilbyder opdateringen.
    Publicér derfor aldrig en release du ikke har verificeret — der er ikke
    længere et manuelt sideload-trin imellem dig og enheden.
11. **Æra-skiftet er STØRRE end version_tool + generatorerne.** Lært den
    hårde vej ved 2.0.12 (#757, fire identiske rig-blokeringer): udover
    punkterne ovenfor bærer disse steder æraen og skal rykkes manuelt i
    samme bump —
    wizard/pilot-`BRANCH`-pins (`stage_a_one_click.py`,
    `agent3_readonly_pilot_one_click.py`, `scheduler_pilot_wizard.py` —
    wizarden `git switch`'er selv til pinnen ved start, så en glemt pin
    trækker riggen tilbage til den gamle kandidat);
    operator-stemplerne `EXPECTED_VERSION` (`stage_a_physical_operator.py`
    m.fl.) og `EXPECTED_SOURCE_VERSION` (`stage_b_one_click_v2.py`,
    `stage_b_strict_evidence.py` — kilden er den NETOP udgivne version);
    loader-substitutionsparrene i `tests/workflow_*`-loaderne (kilde- og
    målversion rykker begge ét hak);
    kontraktfixtures i `tests/workflow_stage_b*`;
    og de tre gate-læste runbooks `RIGDAG_SIMPEL.md`,
    `STAGED_PHYSICAL_PROMOTION.md`, `STAGE_B_UPDATER_EVIDENCE.md`
    (kilde-versionen skal FORBLIVE eksplicit — kontrakterne kræver både
    kilde og mål nævnt).
    Det strukturelle fix er en udledt gate over æra-pins (#753); indtil
    den findes, er denne liste bump-proceduren.

---

## 5. Sandbox-toolchain (verificér selv i ny session)

```
Repo-klon    /home/claude/repo   (PAT indlejret i origin-URL — masker i output)
Android SDK  /home/claude/android-sdk
             export ANDROID_HOME=/home/claude/android-sdk ANDROID_SDK_ROOT=$ANDROID_HOME
             aapt2 findes via: find /home/claude/android-sdk -name aapt2
Gradle       wrapper i repoet (android/gradlew, desktop/gradlew) — brug --offline
Go 1.23      /usr/local/go/bin — SKAL sources: export PATH=$PATH:/usr/local/go/bin
JDK 21       forudinstalleret
mermaid-cli  /home/claude/.npm-global/bin/mmdc — kræver -p cfg med {"args":["--no-sandbox"]}
```
Desktop er JVM-only Compose: tasken hedder `:composeApp:compileKotlin`
(IKKE compileKotlinJvm). Android release-build: `:app:assembleRelease`.
Stierne kan ændre sig mellem sandbox-generationer — verificér med `ls`/`which`.

---

## 6. Sådan starter Anders riggen

**Nem vej:** `scripts\start-kaliv.bat` — starter Ollama + worker + server
korrekt (inkl. `MODELRIG_HOST=0.0.0.0`) og kører `/health/full`. Se
`scripts/START_HERE.md` for manuel vej og fejlsøgning. Telefonen parres mod
Tailscale-IP'en (`http://100.88.91.64:8080`), ikke LAN.

---

## 7. Arkitektur (kort)

```
Kaliv (Android/Desktop) → Go :8080 (pairing/tokens/reverse-proxy, flusher
streams) → Worker :8099 (RAG · voice · tools · eval) → Ollama :11434 (lokal)
                                        └→ Ollama Cloud (valgfrit LLM-trin)
```
- **Voice:** ASR/TTS altid lokalt; LLM-trin kan gå til cloud med EGEN model
  (`voiceCloudModel`, fallback til `cloudModel`). Bufret:
  `/voice/converse/upload`. **Streamet: `/voice/converse/stream`** (NDJSON:
  transcript → chunk pr. sætning m. base64-lyd → done). **`keep_alive`
  sendes ALDRIG til cloud** (lokal-VRAM-direktiv; hang requests — v1.50.0).
- **Tools:** registry i kode, bekræftelses-gate i WORKEREN (klient kan ikke
  omgå), append-only audit. `KALIV_TOOLS_ENABLED=1` for at tænde.
- **RAG:** pdf/docx/pptx/html + foto (`/rag/ingest/image`, 501 uden
  `KALIV_VISION_MODEL`). Embeddings altid lokale (nomic-embed-text).
- **Design:** `assets/design/kaliv-ui-guide/` er autoritativ
  (kaliv-ui-tokens.json v1.0). Ændr tokens, ikke øjemål. Desktop følger den
  fra v1.58.0; **Android kører ældre bronze (#8B6B3D) — alignment er en
  ÅBEN Anders-beslutning.** Fonte (Inter/EB Garamond) mangler som filer.
- Fuld env-liste og endpoints: `README.md` + `TROUBLESHOOTING.md`.

---

## 8. Hårdt tillærte lektier (gentag ikke disse fejl)

1. **On-device-test er den eneste sandhed.** Næsten hver v1.34.x+-bug var
   "koden korrekt, tests grønne, brudt på rigtig hardware".
2. **At kompilere er ikke at shippe** — og **at editere træet er ikke at
   shippe.** CI-jobbet verificerer at assets faktisk ligger på releasen.
3. **Verificér HVER patch-erstatning individuelt.** v1.57's composer-patch
   matchede aldrig (søge-anker med `\uXXXX`-escapes mod en fil med rigtige
   tegn) og scriptet printede succes ubetinget → release-noten overpåstod.
   Nu: assert pr. erstatning + grep-verifikation bagefter. Match mod filens
   FAKTISKE indhold, ikke mod hvad du tror du skrev.
4. **Den korteste timeout i kæden vinder.** Voice: Android/Go/worker skal
   alle være lange (5min/10min/600s); almindelig chat bevidst 120s.
5. **Blokerende arbejde i `async def` fryser hele workeren.** Alt tungt i
   `to_thread` — men BEHOLD serialiseringen med en lås (delte modelobjekter).
6. **Windows-lektierne:** env-reads kræver `TrimSpace` (cmd's `set X=val &&`
   fanger trailing spaces — mutations-testet); datafiler ankres til exe-dir
   (Go) / `%LOCALAPPDATA%\Kaliv` (Python); PyAV blokeres af Application
   Control (→ soundfile); CUDA-DLL'er kræver BÅDE `add_dll_directory` OG
   PATH; multi-line python-one-liners virker ikke i cmd; parenteser +
   nested quotes → goto-labels og genererede `.cmd` i `%TEMP%`.
7. **Læs fejlteksten FØR du fikser** — svaret har stået der ordret, to gange.
8. **Et status-endpoint må ikke lave arbejde.**
9. **En ny gren i et `when` arver ingenting.** List hvad de andre grene gør,
   og begrund pr. ting hvorfor din ikke behøver den (kostede historik, RAG,
   billede, persistens ad tre omgange).
10. **Prompt alene tøjler ikke en lille models vaner** (emojis, persona) —
    deterministisk efterbehandling gør (klient-strip på færdige + indlæste).
11. **"Slet det aktive X" skal nulstille den aktive peger FØR næste
    skrivning** (FK-crash på begge platforme, v1.46.0).
12. **Compose:** `SnapshotStateList` er tråd-sikker at mutere fra IO-tråde;
    sæt indeks-variabler synkront i callback-rækkefølgen (replyIdx-racet);
    `painterResource` tegner kun animerede WebP'ers første frame (→ native
    Canvas-animation); `remember` genlæses når skærmen disposes via
    `when(screen)` — naviger tilbage skal sætte den state den forventer.
13. **Send aldrig lokale Ollama-parametre til cloud-upstreams** (keep_alive).
14. **Fire versionskonstanter i lockstep** — CI-smoke fejler releasen ved
    mismatch. **"✓ forbundet" skal pinge**, ikke bare betyde "parring gemt".
15. **Et verifikations-step skal asserte sin EGEN exit-kode.** 16/7: en commit
    påstod PowerShell-parser-verifikation, men `pwsh` manglede +x og fejlede
    tavst FØR pushet. `chmod +x /opt/pwsh/pwsh` først — og lad scriptet fejle
    højlydt, ellers "verificerer" du ingenting.
16. **En test der kun kan bestå er ikke en test.** Kontrakt-tests mod kode der
    ikke findes endnu (gate 3) skal drives mod syntetiske OVERTRÆDELSER, ellers
    er de dekoration.
17. **Docs kan rulle hærdning tilbage.** README bad folk starte workeren med
    `uvicorn app.main:app` — efter 1.58.46 er det entrypointet UDEN ASGI-guard.
    Docs er ikke pynt; de er en kørende instruktion.
18. **Duplikér aldrig en konstant hvis hele dens job er at matche sig selv.**
    Jeg var ved at lave en anden `"enc:v1:"`-literal i den nye rene logik. Den
    rene lag ejer strengen; `data.Crypto` re-eksporterer.
19. **Afkræft ikke en audit på en delvis søgning.** Min 1.58.40-analyse afviste
    README-dubletten fordi *overskrifterne* var unikke — indholdet stod 3
    gange. Auditen havde ret.
20. **To sessioner kan være varme samtidig.** 16/7 landede den anden JobStore
    på main mens denne læste analysen; opdaget sekunder før dobbeltarbejde.
    Fetch/rebase + kig på `origin/main` FØR hvert push.
21c. **Brug `bash scripts/ci_local.sh`** i stedet for at samle kommandoerne
    selv. Den kører hvad `ci.yml` + `_tests.yml` kører, og — vigtigere — den
    NAVNGIVER hvad den ikke kan køre (Android SDK, Windows-DPAPI) i stedet for
    at springe det over i stilhed. Et tjek der tier om sine huller rapporterer
    grønt for noget mindre end du tror du målte. Den siger selv "grønt her
    betyder grønt for 8 af 10 kontroller".
21c. **En afkortet skærmvisning er ikke en måling.** 26/07 læste jeg
    `Invoke-RestMethod`s standardformatering af en array — `{@{...; misfire_policy=ru...`
    — som en komplet liste, konkluderede at en godkendt plan manglede, og
    sendte Anders ud at lede efter en fejl der formentlig ikke fandtes.
    PowerShell afkorter objekter i visningen. Brug
    `... | Format-Table felt1, felt2` eller `ConvertTo-Json`, aldrig
    standardvisningen, når svaret skal bruges som evidens.
21b. **Verificér med den task CI faktisk kører — ikke en svagere.** 25/7
    brugte jeg `./gradlew :composeApp:compileKotlin` hele dagen til at godkende
    desktop-ændringer. CI's `desktop-compile` kører `:composeApp:test`, som
    ogsaa kompilerer `src/test` og eksekverer unit-testene. Mit arbejde bestod
    begge (efterprøvet), saa der skete ingen skade — men jeg havde et svagere
    net end jeg troede, og en test-only-fejl ville være sluppet igennem lokalt.
    Samme klasse som probe-fejlene: læs workflow-filen, gæt ikke kommandoen.
21. **En reachability-graf er kun så god som sit entrypoint.** 24/7: målt
    "70% af workeren er død" fra `app.main` — men CI pakker
    `worker/run_worker.py`, som monterer agent3 ovenpå. Rigtigt tal: **24%**
    (~4.900 linjer, browser/research-klyngerne — bevidst staged, se §0/§9).
    Verificér entrypointet i PyInstaller-kommandoen i workflowet FØR du
    tegner grafen. Samme fælde som probe-fejlene: mål mod det der faktisk
    kører.
22. **Tagget skal selv bære sine regenererede docs.** v1.58.143 fejlede i
    build-and-release fordi `ACTIVATION_READINESS.md`-regenereringen lå i en
    commit EFTER tagget — readiness-gaten så en driftet fil (36/2) og
    stoppede alt; draft med 0 assets. Bump + `activation_readiness.py` +
    `current_state.py` skal i SAMME commit som tagget peger på (144 gjorde
    det; genudsendelse, ikke ny kode).

---

23. **En måling finder ting læsning ikke gør.** 25/7 blev workflow-succes-
    harnessen bygget (`scripts/workflow_eval.py` + `workflow_runner.py` +
    `eval/workflows_v1.json`, 14 workflows). Den fandt med det samme at
    **bekræftelseskortet ikke bar `impact`** — kun `risk`, som er for grov:
    note_append, delete_model og pull_model er alle `risk=write`. Desktop-
    klienten kompenserede med en værktøjsnavn-tabel, altså en anden kopi af en
    risikoklassifikation, der bliver forældet næste gang et værktøj tilføjes —
    samme fejlklasse som `desktop`-klassen der fik et skærmbillede til at
    ligne en READ. Lukket i 1.58.144+ (`961fd61`): kortet bærer nu `impact`,
    og `riskOf` foretrækker serverens ord.
    **Mønsteret er værd at gentage: byg måleinstrumentet, og det peger på
    huller i det målte.** Kodelæsning havde ikke fundet den — feltet manglede
    et sted ingen ledte.
24. **Harnessen er selv sabotage-testet.** Før den blev troet: ordre-tjekket
    blev fjernet → gate-bypass-testen blev rød; side-effect-tjekket fjernet →
    fantom-skrivnings-testen blev rød; gendannet → 25/25 grøn. Gør det samme
    med enhver ny probe i dette repo. Grønt fra en probe der ikke er
    kontrolleret imod en kendt fejl betyder ingenting.

25. **Målingen er mistænkt før konklusionen — og et instrument der siger
    nul skal bevises i stand til at sige andet.** 27/7 ramte samme fejl fem
    gange i forskellig forklædning: en importgraf gav tre forskellige tal og
    ingen af dem repoets kendte 24% (statisk AST kan ikke se `mount_agent3`);
    `git log A..B` gav tomt på en shallow clone og `2>/dev/null` slugte fejlen;
    `ls X | sed && echo ok` meldte succes fordi `sed` lykkedes; testsuiten blev
    kørt før `current_state.py` og fejlede på en fil der var ved at blive
    rettet; og et touch-target-grep rapporterede "0 overtrædelser" mens
    kontroltjekket viste at det fandt 0 af 23 klikbare elementer overhovedet.
    **Kør altid kontroltjekket:** hvis målingen kan finde nul, så bevis først at
    den kan finde noget. Et nul fra et blindt instrument ligner et rent resultat.
26. **Grønt main er ikke leveret.** 27/7 stod der 27 commits og 12 timer mellem
    sidste release og main, mens `VERSION` stadig sagde det udgivne nummer — så
    enhver der byggede fra main fik en binær der rapporterede en version den
    ikke var. Færdigt arbejde der ikke er ude er ikke færdigt. Skær en release
    når main har samlet noget der er værd at have ude, frem for at vente på at
    nogen spørger.
27. **Et dokument adresseret til en AI rådner farligere end andre.**
    `brand/05_handoff-docs/claude-handoff-brief.md` beder eksplicit en AI om at
    omsætte brandretningen til et designsystem — og beskriver ModelRig med
    safirblå som primærfarve. Det gældende Kaliv-system er messing og har nul
    blålige tokens. En session der læste den ville bygge det forkerte produkt
    uden at noget advarede den. Alle fire ModelRig-era briefs er nu bannerede
    som overhalede. Markér den slags **når** retningen skifter, ikke bagefter.

28. **Fysisk bevis er bundet til koden, så produktion er en tilstand du
    genetablerer — ikke en milepæl du passerer.** `activation_readiness.py`
    afviser en valideringsrapport fra et andet commit, og begrundelsen står i
    generatoren selv: *"a report from a rig running different code is not stale
    evidence, it is evidence about something else."* Målt 27/7 lå der 52
    commits mellem Stage A og main — intet var i stykker, men rapporten
    beskriver ét bestemt træ. Konsekvensen er en planlægningsregel: skær en
    release, checkout **det tag**, kør beviserne mod netop det, spørg
    `activation_readiness.py`, og tænd derefter. Samler du 52 commits mellem
    rig-dage, har du spildt den forrige.

29. **Asymmetri betyder som regel en fejl i den ene — men ikke altid, og
    forskellen er hvad de to ting SVARER PÅ.** Heuristikken virkede fire gange
    27/7: `Brand.kt` kopierede hex mens generatoren ejede dem; ét SSRF-tjek
    encodede sine stier mens tre ikke gjorde (path-traversal, rettet); én
    memory-klient krævede en klassifikation mens skrivestien tav (stille
    nulstilling, rettet); `DRIFT`s API-liste var frosset mens koden gik videre.

    Modeksemplet, så ingen "retter" det: **Agent 3's `confirm` bærer en digest,
    tools' `confirm` gør ikke.** Det ligner samme mangel og er det ikke. Tools'
    gate fryser argumenterne server-side i `Pending` ved propose — *"the model
    never gets a second chance to change the arguments after Anders has read
    them"* — så klienten godkender ved id, og serveren holder indholdet. Agent
    3's digest er et EKSTRA led, ikke det samme led. Tilføjer man en digest til
    tools, tilføjer man en kopi af en sandhed serveren allerede ejer, og så er
    man tilbage ved den fejl heuristikken skulle fange.

    Samme gælder de inverterede defaults i `Agent3ValidationClient`:
    `production_activation` læses med default **true** blandt et dusin `false`.
    Det ligner en slåfejl. Det er retningen: en manglende tilladelse må ikke
    give adgang, et manglende farefelt må ikke give tryghed. Begge peger mod at
    afvise. Beskyttet af `Agent3InvertedDefaultTest`.

    **Test før du retter:** spørg hvad de to ting svarer på. Er det samme
    spørgsmål, er den ene forkert. Er det forskellige, er asymmetrien
    meningen — og så skal den have en test der siger det, ellers bliver den
    ryddet op næste gang.

30. **GitHubs læse-API'er er eventually consistent — skriv-svaret og
    git-protokollen er autoritative.** 29/7 svarede `PATCH refs/heads/main`
    med den nye sha, mens et GET i samme sekund viste den gamle: en stale
    replica, ikke en fejlet landing. Vagten "bekræft, så luk" nægtede korrekt
    at lukke PR'en, og tre målinger ad to uafhængige veje (`git ls-remote` +
    REST, med retry) bekræftede landingen. Samme familie: search-API'ets
    PR-tælling haltede tre bagud efter seks lukninger — det paginerede
    pulls-endpoint er det autoritative tal. Konkludér aldrig "falsk landing"
    eller "nye PRs" på én læsning af et lagged endpoint.

31. **Ancestor-af-main er skal-kriteriet for stacked PRs — to-punkts-diff
    lyver, når main bare er nyere.** Fejemålingen 29/7 viste #149+#151–#155
    med ~200 "afvigende" filer mod main; ancestry (`git merge-base
    --is-ancestor <head> origin/main`) beviste, at alle seks var fuldt
    indeholdt i main via #156-merget — afvigelserne var main's egen videre
    udvikling. Alle seks lukket med det bevis. Klassifikationen NY/AFVIGER
    er stadig den rigtige til retningsspørgsmål (#98/#133/#140/#144 og
    #165–#167: nul nye filer, ægte divergens), men "er den landet?" afgøres
    med ancestry, ikke diff.

32. **En optælling beviser ikke fravær. Kald funktionen.** Tre gange 29/7 pegede
    en tælling den forkerte vej, og hver gang rettede et funktionelt tjek den:
    `KALIV_AGENT3_ENABLED` optrådte nul gange i `#183`s `production_mount.py`,
    så jeg mistænkte en brudt dormans — gaten sad i `api.mount_agent3`, som
    wrapperen delegerer til, og `#167`s ene forekomst stod i en **docstring**;
    et mount med flaget usat gav `False` og nul ruter. `/confirm` optrådte i nul
    `Forward`-linjer i mains `agent3.go`, så jeg konkluderede et hul i
    host-laget — ruten er registreret i `server.go` og går gennem
    `handleAgent3ApprovalConfirm`, som er **rigere** end den forward jeg var på
    vej til at "genindsætte"; havde jeg porteret den, havde jeg fjernet
    invariant 5 fra host-laget. Og linjetal fik `#183` til at se ud som et
    supersæt, hvor kun en diff pr. fil kunne vise det.

    **Reglen:** grep afgør hvor du skal læse, aldrig hvad der er sandt. Er
    påstanden "X mangler" eller "A indeholder B", så udfør den — importér
    modulet, kald funktionen med flaget slået fra, ram ruten, diff filen. Alle
    tre fejl ville have kostet arbejde eller sikkerhed; alle tre blev fanget af
    et tjek der tog under et minut.

33. **En gruppering er ikke en optælling — og et branch-prefix er ikke et
    spor.** Mit spor-sweep 29/7 grupperede åbne PR'er efter `t021-`, `t022-`,
    `t033-` osv. og lagde resten i "andet". Det gav 58 åbne PR'er og to i
    "andet". Det korrekte tal var 62, og forskellen var en **hel ni-PR-stak**
    (Agent 4, `#220`–`#228`), som ingen af mine nøgler matchede. En ekstern
    read-only analyse fangede den; jeg gjorde ikke, selv med fuld klon.

    Værre: prefixet er nu tvetydigt. `agent/t033-*` dækker i dag **to
    urelaterede spor** — memory-beskyttelse (`#143`, `#202`–`#212`, `#214`) og
    Agent 4's retry (`#224`, `#225`). Et sweep der grupperer efter `t033-`
    blander dem sammen og rapporterer ét spor hvor der er to.

    **Reglen:** tæl først (`pulls`-endpointet, pagineret, `len()`), gruppér
    derefter, og verificér at grupperne summerer til tællingen. Gør de ikke
    det, mangler der en gruppe — det er dét, "andet: 2" i virkeligheden sagde.

34. **Enumerér lukkesættet — et filter er ikke en beslutning.** 30/7 lukkede
    et oprydningsscript `#241`, en PR skabt kl. 06:02 samme morgen — *efter*
    målingen der definerede oprydningen. Scriptet udledte lukkesættet af et
    `t021`-filter på den aktuelle åben-liste i stedet for at bruge de
    enumererede numre fra målingen, og dets eneste vagt (nul unikke filer)
    holdt tilfældigvis, fordi `#241` viste sig at være en dublet af netop
    landet arbejde. Udfaldet var korrekt; mekanismen var det ikke — det samme
    kriterium ville have lukket en retnings-PR som `#144` (nul nye filer,
    ægte divergens) uden et blik.

    **Reglen:** en masse-handling opererer kun på de numre, målingen
    identificerede. Alt der matcher filteret men ikke målingen, er et fund,
    ikke et mål — og i et repo hvor flere sessioner arbejder samtidig (se
    §9, 30/7), skal det forventes at listen har flyttet sig mellem måling og
    handling.

35. **Et rent merge er ikke et review. Diff HELE filen, ikke din hunk.** 30/7
    landede jeg `#243` efter et grundigt review af dens confirmation-ændring.
    Samme PR bar en **stale kopi** af `android/.../CapabilityDescriptorV2.kt`,
    skåret før `3c8a3884` ("fail closed on Android descriptor parse errors",
    19/7). Målt mod PR'ens egen merge-base var den fil derfor en *revert* af
    hærdningen — og fordi main ikke havde rørt den region, anvendte git
    reverten **rent, uden konflikt og uden et ord**. `canonicalize` faldt
    tilbage til `else -> value.toString()`. Den lå på main i tre timer og blev
    kun fanget, fordi `#246` tilfældigvis bar den hærdede udgave.

    **Målt bagefter, og det korrigerer min egen første beskrivelse:** ingen
    digest var nogensinde forkert. Skemaet indeholder kun strenge, booleans,
    objekter, arrays og null, og for hver af dem giver de to udgaver
    byte-identisk output (`is Boolean -> toString()` mod `else -> toString()`).
    Kun tal ville afvige (`numberToString` mod `toString`), og skemaet har
    ingen numeriske felter. Dertil er inputtet til `canonicalize`
    `JSONObject(source.toString())` — en genparsning fra JSON-tekst — så en
    ikke-JSON-native type kan strukturelt ikke nå frem. Den svækkede gren var
    uopnåelig ved konstruktion.

    Lektien står uændret, for den handler om mekanismen, ikke om skaden: en
    stale kopi bliver til en tavs revert. Men **skriv altid den målte
    alvorlighed, ikke den frygtede** — jeg kaldte det først fail-open på
    digest-stien, og det var mere alarmerende end fakta bar.

    **Reglen:** for hver fil en branch rører, diff hele filen mod main før
    landing — ikke kun den ændring du kom for. "Ingen konflikter" betyder at
    git kunne kombinere ændringerne, ikke at kombinationen er rigtig. En
    branch der er ældre end main i en fil, ser for git ud som en bevidst
    ændring af den fil.

36. **Stale-tjek før hvert merge — tre kommandoer, syv fund hver gang.**
    Konsekvensen af lektie 35, gjort mekanisk. For hver berørt fil: er main's
    seneste commit på filen med i branchens historie?

    ```
    for f in $(git diff --name-only origin/main $HEAD); do
      last=$(git log -1 --format=%H origin/main -- "$f")
      git merge-base --is-ancestor "$last" $HEAD || echo "STALE $f"
    done
    ```

    Er en fil stale, afgør ét spørgsmål mere udfaldet: **ændrer branchen den
    selv** (sammenlign `$HEAD:$f` med `$MB:$f`)? Er den blot gammel, tager git
    main's udgave rent og alt er godt. Har branchen ændret den, er ændringen
    en revert af main's nyere arbejde, og git anvender den uden at spørge.
    Det er hele forskellen mellem `#246` (revert, fangede den i hånden) og
    `#250`/`#251` (blot gamle, gik rigtigt af sig selv) — samme syv filer,
    modsat udfald. Kør tjekket; gæt det ikke.

37. **En generator i et halvt miljø fejler ikke — den skriver fejlen ind i
    dokumentet.** 17/8 under 2.0.9-bumpet kørte `activation_readiness.py`
    uden `fastapi`/`pydantic` installeret. Den returnerede exit 0, skrev
    "skrev ACTIVATION_READINESS.md (111 linjer)" og erstattede linjen *"Ingen
    blokerende fund specifikke for scheduleren"* med *"kunne ikke læse
    schedule-godkendelsen: No module named 'fastapi'"*. Havde den commit fået
    lov at lande, stod der nu en påstand på main om at scheduleren fejler —
    fordi en sandkasse manglede en pakke. Fanget kun fordi diffen blev læst
    linje for linje.

    Reglen: **installér workerens afhængigheder FØR generatorerne køres**
    (`pip install --break-system-packages -r worker/requirements.txt`), og
    læs derefter deres diff. En generator hvis output er *degraderet* ser
    ud præcis som en generator hvis output er *opdateret* — begge giver
    exit 0 og en ændret fil. Grep efter `No module named`, `Traceback` og
    `kunne ikke` i de genererede filer før commit.

38. **`git add -A` er ikke en beskrivelse af dit arbejde.** Samme bump fejede
    `validation/stage-b-easy-state.json` med — en tilstandsfil som
    testkørslerne selv havde skabt, aldrig sporet før. Den nåede en commit og
    blev først opdaget i diffstat'en bagefter.

    Reglen: **sammenlign diffstat'en med den liste filer du HAVDE til hensigt
    at røre**, hver gang. Et bump rører ni navngivne filer; ser du ti, er den
    tiende ikke dit arbejde. `git status --short` før `git add`, og vær
    særligt mistroisk efter en testkørsel — suiter skriver tilstand.

## 9. Kø — hvem har bolden (16/7, opdateret 3/9)

**[3/9 kl. 07:00 UTC — status. main = `#844`-landing, VERSION 2.0.13. Frosset
kandidat uændret (`4f80693f`). 2/9-aftenblokken nedenfor er historik.]**

### Beslutning 2/9 aften: den rigtige løsning til kroppen er Unity/UniVRM

Anders: Kaliv skal kunne **vise, afspille og afvikle** `.mrbody` — AR-agtigt.
Ikke en web-renderer; Unity/UniVRM-sporet fra `BODYRIG_V1.md`. Roadmap:
`docs/bodyrig/UNITY_RENDERER_ROADMAP.md` (#832).

### Hvad der skete 2/9 aften – 3/9 morgen

- **#720 (Unity/VRM-proof) ajour og grøn:** merget 71 commits fra main uden
  konflikter; 32/33/11 kontrakter + 14/14 CI på ny head. Forbliver draft
  efter sin egen regel — kun den fysiske gate mangler. Riggens forudsætninger
  står på PR'en: Unity `6000.3.21f1` i Hub, en rigtig VRM 1.0-avatar (VRoid
  Studio), en `.mrbody` bygget/installeret/valgt.
- **Slice A — assets (#842):** `GET /body/active` + `avatar.vrm`, thumbnail,
  motions, læst kun gennem BodyRigs validerede veje, sha256 pr. medlem,
  `X-BodyRig-*`-headers som proxyen nu lader passere. `KALIV_BODY_STORE` i env.
- **Slice B — live frames (#843):** én embodiment-session pr. worker
  (`BodyRigRuntime` + `EmbodimentScheduler` + `wav_envelope_track` + wire v0.1),
  drevet af chat-faser og TTS-sætninger; `GET /body/frames` (SSE 20 fps),
  `/body/state`, `POST /body/interrupt`, `POST /body/state/{navn}`.
- **Afspilningssync (#844):** telefonen melder start/slut pr. sætning
  (`POST /body/speech/{utterance}/started|ended`), munden forankres til det,
  der faktisk høres. Gamle klienter uændrede.
- Fund undervejs: Go ServeMux tillader ikke `{name}.vrma` (ville have væltet
  backend ved opstart; test fangede det); proxyen lod kun `Content-Type`
  passere (nu præfiks-allowlist for `X-BodyRig-*`).
- **Slice C — Unity frame-kilde (#846, DRAFT mod `agent/bodyrig-unity-renderer`):**
  `BodyRigFrameSource` læser `/api/v1/body/frames` bag device-token gennem
  samme `Apply` som fixturen; bootstrappen vælger den kun når `BODYRIG_RIG_URL`
  + `BODYRIG_RIG_TOKEN` er sat. **Kompilerer kun i Unity** — verificeres af den
  fysiske gate. Rækkefølge: #720's gate → #720 lander → #846 merges.
- **Første krop fra en VRM alene (#847):** `scripts\bodyrig_demo_body.py --vrm
  … --name … --store …` bygger/installerer/vælger en `.mrbody` med
  demo-identitet (fixture, siger det selv). Rig-runbook:
  `docs/bodyrig/FIRST_LIVE_BODY.md` — fra Unity i Hub til krop der følger chatten.
- **Cues (#848), default fra:** `KALIV_BODY_CUES=1` → `explain` ved lange
  sætninger, `curious` under thinking, `concerned` ved fejl; intet udledt af ordene.
- **Driftsfund ved gennemlæsning af egen kode (3/9 middag):** frame-streamen
  re-validerede hele `.mrbody` 20×/s (#850 — nu cache med markør-mtime i
  nøglen, 13 ms → 8 µs); proxyens 10-min timeout ville have klippet streamen
  på klokken (#851 — frames forwardes uden timeout; klientens context lukker);
  `/body/state/{navn}` tager nu kun `listening`/`idle` fra klienten (#852).
- Proces-fejl, min: landings-scriptet slettede en gren FØR mergen var
  bekræftet, da et Windows-job flakede (#848). Gendannet uden tab; mønstret
  rettet — sletning kun i samme program som en bekræftet merge.

Core er urørt i hver regel: workeren sekvenserer kun. Alt en Unity-klient på
telefon/Quest skal hente fra riggen, findes nu bag device-token.

### Stående instruks (Anders, 3/9): hold git opdateret

Hver session: triagér dependabot (CI-grønne patch/minor-bumps landes; CodeQL-
trinnene flyttes samlet; majors og governance-gates går til Anders), luk
overhalede PRs, og hold draft-grene (#720, #846) merget med main, så den
fysiske gate beviser nutidens kode. Gjort 3/9: 8 landet (#833–#836, #838,
#839, #759, #853), 3 lukket (#840, #841, #775), #837 forklaret (Ed25519-
review-pin), #720/#846 ajour med main (kontrakter 39/33/11 grønne).

### Rigdag 3/9 aften — bekræftet med Anders' øjne

- **Dev-kanalen virker ende til ende, første kørsel.** Én ægte fejl: workeren
  fejlede lukket, fordi `KALIV_AGENT4_OPERATOR_API=1` stod uden
  `KALIV_AGENT4_DATA_ROOT` (min aktiveringsblok 30/8 manglede den; kravet
  findes i 2.0.12 siden 12/8, så release-workeren KUNNE ikke starte med den
  env fra lørdag til torsdag). Rettet i env; dokumenteret;
  start-scriptet preflighter det nu. Anden "fejl" var kold worker-start > 90 s.
- Fire efterladte Python-workere fra 2/9 og 3/9 holdt scheduler-lease'en, så
  dev-workeren sprang hvert tick over. Dræbt manuelt; stop-scriptet dræber
  nu også workere uden port.
- **#789 bekræftet død** — frisk parring (adb reverse + `127.0.0.1:8080`),
  flere beskeder, ingen crash. Lukket.
- **#752 bekræftet fysisk** — `person_create.py` → Kaliv `person-r0001`;
  `/tools/chat` svarer i hendes stil med `person`; Personer-skærmen viser
  *"Taler lige nu som Kaliv"*. Body/voice `unbound` indtil VRM/.mrvoice.
- Mikrofonen forsvinder i cloud-mode — bekræftet som ønsket adfærd (ASR kunne
  teknisk køre via riggen i cloud-mode; produktvalg, ikke ændret).
- Smoke fra riggen: healthz 2.0.13, schedules 200, agent4 403 uden
  `agent4:read`-grant (korrekt), body 503 uden `KALIV_BODY_STORE` (korrekt).

### Rettelse 4/9: #720 har været på main siden 2/9 21:13

Den parallelle session mergede Unity-proofen via en base-gren
(`feat/bodyrig-unity-renderer-base`) 2/9 kl. 21:13 UTC — **uden den fysiske
gate** og tretten minutter før jeg skrev "ajour, venter på gaten" på den. Mine
noter 2/9–3/9 om "#720 draft, venter på gate" var derfor forkerte. Sandheden:
rendereren er på main; beviset (proof → visuel accept → gate) mangler stadig og
køres mod main's head. #846 er retargetet til main. `agent/bodyrig-unity-
renderer` er en død gren.

### I luften 4/9 — læs FØR du bygger noget på kroppen (to sessioner kører)

To sessioner har i dag landet identisk kode uafhængigt af hinanden (#861 og
min lokale bro var tegn for tegn ens) og kostet tre README-konflikter. Tjek
PR-listen, ikke kun denne fil, før du skriver:

| # | Hvad | Status |
|---|---|---|
| #846 | `BodyRigFrameSource` — live frames fra riggen | draft mod main, ajour |
| #858 | `BodyRigArPlacement` — kroppen i rummet, bag `BODYRIG_AR` | draft stablet på #846 |
| #860 | `BodyRigRigLink` — env / intent-extras / PlayerPrefs / parringsformular | draft stablet på #858 |
| #861 | Kaliv ⋮ → Krop → Kaliv Body med token som intent-extras | **landet** |

Kontrakten mellem #861 og #860: extras `bodyrig_rig_url`/`bodyrig_rig_token`,
pakke `dk.ternedal.kalivbody`. Alle tre drafts kompilerer kun i Unity og
verificeres af første import på riggen; de lander i rækkefølge 846 → 858 → 860.
`origin/agent/bodyrig-unity-renderer` er en død gren (#720 er på main), som
en session har genskabt — slet den ikke, mens den anden session muligvis
bruger den; den bærer intet, main ikke har.

Værtsvalget er taget (separat Kaliv Body-app; UaaL som V2) — byg ikke UaaL.

### 4/9 aften — puljen ryddet med Anders' accept ("kør det færdigt")

- **#863** cryptography 50.0.0 → 50.0.1 landet med Ed25519-reviewet
  (byte-identisk `ed25519.rs`/`.py`; eneste reelle ændring OpenSSL 4.0.2 i
  wheels). #837 lukket som overhalet.
- **#763** gradle-wrapper 8.14.4 → 9.7.1 (desktop) landet efter dependabot-
  rebase mod dagens main; hele matrixen grøn. Revert er ét commit, hvis et
  lokalt byg protesterer.
- **#395** DC-L14 (devcontrol-slutstykket) landet: rebaset 439 commits uden
  konflikter; én ægte fejl — `exact-head-core` manglede den pinnede
  packaging-toolchain (`setuptools==75.8.2`) som `test / test` havde — rettet
  i workflowet. **#338** lukket som overhalet (200/219 filer var på main; de
  sidste 19 kom med #395).
- Person-værktøjer: `person_bind.py` (#859) binder bodyid/.mrvoice som NY
  reviewet revision. Runbook-kapitler for stemme og rigtig krop.

**Åbent i git nu: kun #846 → #858 → #860 (Unity-drafts).** Alt andet er landet
eller lukket. Ingen gren bag main.

Parallelt landede den anden session samme aften ny-rig-bootstrap og komplet
ModelRig+VoiceRig-migration (`scripts/NEW_RIG_BOOTSTRAP.md`,
`scripts/COMPLETE_RIG_MIGRATION.md`, `migrate-complete-rig.ps1`). Kropssporets
env-krav flytter med: en ny rig skal have `KALIV_BODY_STORE` og
`KALIV_AGENT4_DATA_ROOT` sat, ellers svarer body-fladen 503 og workeren
fejler lukket — se `docs/bodyrig/FIRST_LIVE_BODY.md` afsnit 1.

### Bolden ligger hos Anders

0. **Læs `docs/bodyrig/FIRST_LIVE_BODY.md`** — hele rig-dagen på én side.
1. **Den fysiske Unity-gate mod main** (Unity i Hub, VRM fra VRoid, `.mrbody`
   i store + valgt, proof → visuel accept → gate). Derefter #846 (Slice C),
   der kun kan verificeres ved at kompilere i Unity.
2. Dev-kanalen, #789-bekræftelse, `person_create.py` — uændret fra 2/9.
3. `KALIV_BODY_STORE` sættes i appliancens env, når en profil-store findes.

**[2/9 kl. 20:30 UTC — status. main = `#827`-landing, VERSION 2.0.13. Frosset
kandidat uændret (`4f80693f`). 2/9-middagsblokken nedenfor er historik.]**

### Eftermiddag 2/9: #752 Person Profile — hele featuren landet

Kaliv kan være flere personer. Syv PRs, alle CI-grønne:

- **Registry** (#821): `worker/app/person_registry.py` — stabilt
  `person-<32 hex>`, komponentrevisioner som kandidater, uforanderlige
  Person Revisions gated af det fulde compatibility-review, **én**
  aktiveringsvej (`active_person_revision`). Rutesættet er kontrakten; en
  test over ruteinventaret beviser at ingen sti kan aktivere én komponent.
- **Backend** (#822): `/api/v1/persons` bag device-token, lukket allowlist,
  404 før worker-hit for ugyldige id'er og enkeltkomponent-forsøg.
- **Runtime** (#823): en valgt persons aktive personality ER system-prompten
  på `tools/chat`; svaret bærer `person`. Uden valgt person: uændret.
- **Skærm** (#824): ⋮ → **Personer** / launcher-genvej / `kaliv://persons`.
  Viser hvem Kaliv taler som, lister, vælger. Ingen aktiveringsknap med
  vilje — review er en operatørhandling.
- **Værktøj** (#825): `scripts\person_create.py` — én kommando fra intet
  til en person der taler; nægter uden `--reviewed`.
- **Stemme** (#826 + rettelse #827): workeren sender `voice_package` (VoiceRigs
  eget felt; `.mrvoice`-filnavn) og verificerer `X-VoiceRig-Package` →
  `voice_bound`. Virker mod VoiceRig som den er i dag. #826 brugte et
  opfundet `voice_id`, som pydantic droppede stille — læs den andens kode
  først.

Kontrakten: `docs/PERSON_PROFILE.md`. Kendte huller dér: plain
`/api/v1/chat` (uden om workeren) er ikke bundet; body-binding er BodyRigs
spor.

### Bolden ligger hos Anders

1. **Dev-kanalen, første kørsel** (tre kommandoer i `DEV_APPLIANCE.md`).
2. **Bekræft #789 død** — frisk parring, ét send.
3. **Opret Kaliv som person** — `person_create.py` (`--voice-source
   <navn>.mrvoice` hvis en profil er installeret), åbn Personer, send én
   besked, se `person` i svaret og hør stemmen.
4. Workflow-tærsklen (W-12/W-14-fraselister) — den eneste beslutning tilbage.

**[2/9 kl. 12:00 UTC — status. main = `b4bb1ed2`, VERSION 2.0.13. Frosset
kandidat uændret = `physical-proof/2.0.13` = `4f80693fd60de5ece483d25f5e622c771b81a9c2`.
30/8-blokken nedenfor er historik.]**

### Beslutning 2/9: udviklingskanalen

Anders: *så længe intet er i produktion, udvikles der så hurtigt som muligt.*
Den fysiske promotion-vej (Stage A → kampagne → Stage B) er IKKE længere
forudsætningen for at riggen kører ny kode; den er baren for produktion,
den dag den bliver virkelig. `production_activation` er urørt overalt.

Ny kode hele vejen rundt er nu tre kommandoer — se `DEV_APPLIANCE.md`:

    git pull --ff-only
    START_DEV_APPLIANCE.cmd     # backend+worker fra HEAD, egne data og env, LAN-bundet
    INSTALL_DEV_APK.cmd         # CI's kandidat-APK over release-appen, parring bevaret

`STOP_DEV_APPLIANCE.cmd` bringer den signerede release tilbage. UI-ændringer
der rammer golden-screenshots optages af workflowet **record-goldens** på
PR-grenen (#816) — første ægte brug var #817.

### Hvad der skete 31/8-2/9

- **#789 (crash ved første send efter frisk parring) — rodårsag fundet i
  koden og fixet (#818):** `LaunchedEffect(openConvId)` ryddede og
  genindlæste listen på det id, sendevejen selv lige havde udstedt, mens
  første svar streamede; første delta indekserede forbi en ét-elements
  liste fra en indlejret launch uden for `runCatching`. Effekten ignorerer
  nu sit eget id, og alle stream-skrivninger bruger `getOrNull`. Fysisk
  bekræftelse: ét parret send på dev-kanalen.
- **Regression fra #785 fundet og rettet (#812):** task-ui-linjen var splejset
  ind midt i scheduler-here-stringen, så `-EnableScheduler` stille mistede
  `KALIV_SCHEDULER`, DB-stierne og secreten. Form-gate tilføjet.
- **Rig-rapporterede UI-fejl fikset samme dag:** tale-etiketten i cloud-mode
  (#809), cloud-tilbuddet stillet én gang pr. session (#810), Agent-rækkens
  undertitel forklarer nu betingelsen (#817), og **Opgaver** i chattens
  ⋮-menu åbner Agent 3-opgaveskærmen (#815) — den skærm der bærer alle
  tretten task-UI-checks og før kun fandtes bag `kaliv://tasks`.
- **Æra-drift lukket for prosa:** gate for kandidat-referencer i operative
  runbooks (#807/#808); den fangede `PHYSICAL_VALIDATION_CAMPAIGN.md` på
  2.0.11 i første kørsel. Tre issues (#69, #72, #401) rettet manuelt.
- **Vedligehold:** dependabot-puljen ryddet, `compileSdk` 37 (#803), CodeQL
  samlet til v4.37.8 (#804). T-033's krav om en anden Windows-konto og den
  kandidatbundne a425f-APK dokumenteret (#811).

### Bolden ligger hos Anders

1. **Første kørsel af dev-kanalen** — tre kommandoer ovenfor. Nye scripts på
   en maskine, de aldrig har kørt på: send outputtet, uanset hvad.
2. **Bekræft #789 død** — fjern parring, par igen, send én besked.
3. **task_ui-beviset** — ⋮ → Opgaver, følg tabellen i
   `STAGED_PHYSICAL_PROMOTION.md`, sæt krydserne. Kun relevant hvis den
   fysiske vej stadig skal lukkes for 2.0.13; ellers venter den.
4. **Beslutninger uændret:** #763 (gradle-major), workflow-tærsklen, de tre
   gamle feature-spor. Kandidat A (2.0.13 skiber som frosset; UI-fixes i
   2.0.14) er valgt.

**[30/8 kl. 21:00 UTC — status. main = `05e6b93d`+, VERSION 2.0.13. Frosset
kandidat = `physical-proof/2.0.13` = `4f80693fd60de5ece483d25f5e622c771b81a9c2`
(`anchor_and_freeze`, alle fire exact-SHA-gates grønne). 27/8-blokken nedenfor
er historik.]**

### Hvad der skete 29-30/8

- **Agent 4 er kvalificeret, godkendt og aktiveret.** A4-25f kørt fysisk
  igennem for første gang: `physical_qualification_evidence_complete: true`,
  14/14 HTTP-trials, cursor-matrix, mutationskæde og cleanup verificeret,
  root-kæde `47529c6f…` → `e70a781f…`. Menneskelig GO registreret (Anders,
  30/8 18:10Z), og `KALIV_AGENT4_OPERATOR_API=1` sat på appliancen —
  operator-fladen svarer 401, altså live og token-vogtet.
  `production_activation` er fortsat false. Sporing: #474, #731.
- **Scheduleren og Agent 3-readiness aktiveret** 29/8 (Fase 2 + Fase 3's
  developer-flade): `/api/v1/schedules` svarer 401, og workerens
  task-readiness siger `agent3_readonly` efter en fejlfri 20/20-pilot.
- **Tre fejl blokerede A4-kæden i to æraer** — #797 (snapshot-operatorens
  fejlsvar bar `application/json`; fixture-hosten bygger sin egen app, så
  #794's mount-handler nåede den aldrig), #794 (`-W` bandt som
  PowerShell-parameternavn; `pm path` exit 1 tolket som værktøjsfejl) og
  #798 (`rm -rf` i `anchor_and_freeze` på en Windows-only rig).
- **Rodårsag fundet for tre døgns spøgelser:** en env-spejling tog
  `# kommentaren` med ind i variablens VÆRDI, så `MODELRIG_OLLAMA_URL` pegede
  på en ødelagt URL. Det forklarede `bad upstream request`, embeddings-405 og
  T-023's `plan → 500` på én gang. Env-filer må kun parses med kommentar-strip.
- **Task-UI: tidligere konklusion var forkert.** Fladen findes — som den
  dedikerede skærm `Agent3TaskScreen` (`kaliv://tasks`), ikke i chat-panelet.
  Runbooken mapper nu alle tretten checks til deres plads på den skærm.
  Chattens Agent-række er kun klikbar med parret rig, `rig`-mode OG tekst i
  feltet. Panelet fik surface/reason/fallback (#799), replans (#800),
  terminal-udfald (#801) og serverautoritativt Stop (#805, ægte T-023-brud).
- **Vedligehold:** dependabot-puljen ryddet (#760, #761, #762, #764, #767).
  `compileSdk` hævet til 37 (#803) — det blokerede både okhttp- og
  compose-bom-linjen. CodeQL-trinnene flyttet samlet til v4.37.8 (#804);
  dependabots enkeltvise PRs kunne aldrig bestå.

### Bolden ligger hos Anders

1. **2.0.13 på appliancen** — den kører stadig 2.0.12-binærer, mens
   kvalifikationen er bundet til 2.0.13-koden. Stage B-updater-runde.
2. **task_ui-beviset** — åbn `kaliv://tasks`, følg runbookens tabel,
   sæt krydserne, kør valideringen. Estimeret et kvarter.
3. **Beslutninger:** gradle-wrapper-majoren (#763), tærskeldommen på
   workflow-tallene (de rene 2.0.13-tal mangler), og hvad der skal ske med
   de tre gamle feature-spor (#720, #395, #338).
4. **#789** (crash ved første send efter frisk parring) mangler en
   `adb logcat -b crash -d` — kodelæsning fandt ingen usikre kald.

**[27/8 kl. 21:30 UTC — status. main = `178a352f`, VERSION 2.0.12, seneste tag
v2.0.12 (shipped 26/8 på én dag: bump #756 → æra-pakke #757 → Stage A 7/7 →
tag → release 9 assets verificeret). Kandidat = `origin/physical-proof/2.0.12`
= `76fc3fa2` (post-tag; main er foran, hvilket er korrekt efter promovering).
23/8-blokken nedenfor er historik.]**

### Hvad der skete 24-27/8

- 24/8: #747-planen afstemt med Sol (færdig = M1+M2+M3; "shipped" = M1) og
  beslutning B truffet. v2.0.11 shipped 24-25/8 med fuld Stage A+B-kæde.
- 25/8: task_ui-gaten fangede en ÆGTE 2.0.11-defekt: appen kalder
  `/api/v1/tools/chat/stream`, backend manglede ruten (#754). Fixet + udledt
  app↔backend-rutekontraktgate landet som #755. Stage B 2.0.11 bestod.
- 26/8: 2.0.12 shipped. Æra-skiftet afslørede den udokumenterede pin-pakke
  (#757, nu §4.11). Kanonisering #750, token-selv-mint #768 og
  release-opslag-token #770 landet.
- 27/8: Stage B-kæden BESTÅET på 2.0.12 (strict PASS: interruption, ægte
  opdatering gennem updateren, reboot, checksum-afvisning). Appens tools-chat
  bekræftet fysisk mod 2.0.12. Udestående: task_ui-bogføringen (begge
  klienter + evidensnoter — fulde krav nu i STAGED_PHYSICAL_PROMOTION §task_ui)
  og lifecycle-verify-genkørsel. Dagens fund: #753 pkt. 8-12.

### Bolden nu

- **Anders:** task_ui-sessionen (én kort seance, proceduren står i runbooken)
  → verify 8/8 → M2-kampagnen for tærskeltal → ROADMAP-beslutning om 2.0.13
  (anbefaling: M3-lukning).
- **Claude:** state/observations-kandidatbinding (#753 pkt. 3+8, fixet er
  næste kodede opgave), udledt gate over æra-pins (#753), M2-kampagneblokke.
- **Sol:** T-033-kontrakten (aftalt, afventes).


**[23/8 kl. 21:30 UTC — status. main = `274c8f60`, VERSION 2.0.11, seneste tag
v2.0.10. Kandidat = `origin/physical-proof/2.0.11`, som SKAL være lig
`origin/main` (#731). Ingen `validation/` på main. Åbne PRs: 3 (#338, #395,
#720). Åbne issues: 33. 18/8-blokken længere nede er historik.]**

### FREEZE-VINDUE — læs før enhver landing på main

Fra det øjeblik riggen har produceret et grønt `candidate_freeze_check.py`-
receipt på en exact SHA (meldt som kommentar på #731 / #58), og indtil den SHA
enten er promoveret (fast-forward + tag `v2.0.11` + release) eller eksplicit
opgivet, må INTET lande på `main`. Hver landing flytter `main` væk fra
kandidaten, og efter #731 §A/§E/§F.1 er freeze og al fysisk evidens derefter
ugyldig — `main` kan ikke flyttes tilbage.

Det skete 23/8: freeze PASS på `c45d97ed` kl. 20:23 UTC; #732, #734, #736 og
#738 landede 20:28–21:20 UTC. Kandidaten stod 4 bagud, og Stage A-evidens på
den SHA kunne ikke promoveres. Ingen af de fire PR'er var forkerte — det var
tidspunktet.

Regel for enhver session (Claude, Sol eller andre) før merge/fast-forward af
`main`:

1. Læs seneste kommentar på #731. Står der et freeze PASS uden efterfølgende
   promotion/abandonment: **land ikke**. Kommentér på #731 at PR'en venter.
2. Er der intet aktivt freeze: land, og forvent at kandidaten re-ankres
   bagefter (`scripts/anchor_and_freeze.py`).
3. Rig-dagens rækkefølge er derfor: alle ventende landinger FØRST → anchor +
   qualification → freeze på riggen → Stage A → beslutning → tag → Stage B →
   landinger genoptages.

### Hvad der skete 20-23/8 (siden 18/8-blokken nedenfor)

- 20/8: Stage A bestod 7/7 + T-006 på `bf505800`. Den evidens er historik —
  hovedet er flyttet flere gange siden, og RIGDAG_SIMPEL forbyder genbrug af
  evidens fra en ugyldiggjort head. Apparatet er dermed bevist at virke; beviset
  skal indsamles igen på den frosne SHA.
- 20/8: ti måleapparat-defekter fundet og lukket (#650–#667). Vigtigst #662
  (W-11 var CONFIRM_TTL, ikke modelkvalitet) og #667 (T-023 uden retry). Det
  reelle workflow-tal er stadig ukendt — kør `-WorkflowRounds 3` med
  #667-retryet før tærsklerne diskuteres.
- 21-23/8: proof-kæden gjort fail-closed (#670, #673, #675, `fec2e514`, #700 —
  regelmatricer 41→111 checks, kandidat-gate 9→26). Eneste produktændring i
  perioden er #668 (Computer Use-bro).
- 22/8: authority-kontrakterne pinnet (#693–#696): kandidat = `origin/
  physical-proof/2.0.11`, aldrig en gammel SHA. Rig-stien i alle docs er nu
  `C:\Users\admin\Desktop\ModelRig-git`.
- 23/8: flåden ryddet (~50 → 3 åbne PRs). Afhængigheder kvalificeret på exact
  head (#705–#712: AGP 9.3.1, Gradle 9.6.1, Compose MP 1.11.1, uvicorn 0.52.3,
  cryptography 50.0.0 m.fl.). T-035 scoped read-only file capabilities (#716).
  T-044 fysisk review bundet til én kandidat (#714).
- 23/8: NYT SPOR — BodyRig (embodiment, `.mrbody`): kontrakter #702,
  runtime-kerne #715, M1.1–M2.5 (#721–#738), `docs/BODYRIG_V1.md`,
  aktiveringsgate #704 (dormant/off indtil fysiske beviser i `Ternedal/BodyRig`
  findes). #720 (M0.3 Unity/VRM-renderer) er åben draft.

### Hvem har bolden

**Anders:**

- Tokenrotation (P0, uændret siden 19/8): GitHub-PAT'er med admin på et
  offentligt repo ligger i klartekst på Notion, én i en sidetitel. Rotér til
  fine-grained med Contents/PRs/Actions/Issues. Ingen tokenværdier i dette repo.
- Rig-dagen efter #731: re-anchor + freeze på current main → Stage A →
  beslutning → tag `v2.0.11` → Stage B. Samme session, hvis muligt: rent
  workflow-tal (`-WorkflowRounds 3`, qwen3:14b, ≥1 dokument i indekset) og
  Agent 4-APK (`MODELRIG_TOKEN` sat i miljøet FØR kommandoen).
- Beslutninger: tærskler for T-023 (20/20) og workflow-gaten (0,95) på baggrund
  af rene tal; T-033-metode; containment (AppContainer + Job Object vs.
  kravspec V5's separate Windows-konto) → låser MCP; ADR-MCP-001; ROADMAP.md
  efter 2.0.11.
- Efter tag: bump main til 2.0.12 (otte kilder, §4) — ikke før.

**Sol:** T-033-probe med eksplicit campaign-id (ét brugerskift i stedet for
fire, jf. 20/8) — Anders afgør om den accepteres som evidens; DevControl-
opdeling mod ADR-DC-001 (#338/#395); egne #296-fund.

**Claude:** intet der kan landes under et freeze-vindue. Denne §9-opdatering
lander FØR næste freeze. Ikke nu: MCP (park til containment-beslutningen),
DevControl trin C, nye gate-matricer.

---

**[18/8 — status. main = `45d39b13`, VERSION 2.0.9, seneste tag v2.0.8.
`v2.0.9` er IKKE sat. Se rig-dagsnoten nedenfor FØR du rører riggen.]**

### Rig-dagen: kandidaten er ikke det main ville udsende

`#614` er den gældende 2.0.9-kandidat (`84ee1ca2`, 16/8). **`#605` er afløst af
den** — de ligger 50 mod 3 commits fra hinanden. Køres begge, bevises to
forskellige ting under samme versionsnavn.

Kandidaten bærer korrekt VERSION 2.0.9, har alle fem 16/8-landinger og er
internt konsistent. Men den er 13 commits bagud, og fem af dem er produktkode
fra 18/8: `WorkerCapabilities.kt`, `IngestCapability.kt`, `VoiceCapability.kt`,
`ModelRigClient.workerCapabilities()`, `AppUi`-wiringen og `/capabilities`'
pptx/html. Konkret: **kandidatens `/capabilities` returnerer fem nøgler, mains
returnerer syv.**

**Anbefaling: bevis og tag kandidaten som den står; 18/8-arbejdet går i 2.0.10.**
Frysningen findes præcis for at evidens binder til én eksakt SHA, og intet fra
18/8 retter noget der er i stykker — capability-gatingen fjerner knapper der
fejler, pptx/html er additivt. Et recut ville gøre al evidens på `84ee1ca2`
værdiløs og kræve hele kørslen om.

**Rækkefølgen holder uanset valget:** klientens `supports()` blokerer kun på et
UDTRYKKELIGT `false`, så en fem-nøgle-rig ser ud som "pptx ukendt" = tilladt.
Worker-ændring og klient-gating kan derfor udsendes i hver sin release i
vilkårlig rækkefølge. Det var derfor defaulten blev valgt sådan.

### Flåden driver — mål den før du rydder op

`scripts/pr_drift_report.py` (#628) besvarer lektie 36 for ALLE åbne PR'er, ikke
kun den man har i hånden. Måling 18/8: **9 af 50 har revert-risiko.** De
stablede agent4-baser er **151 commits bagud main** — det er ikke risiko i sig
selv, men det er dér den materialiserer sig den dag stakken rebases.

Anledningen var dependabot `#359`: 23 commits bagud, rørte
`desktop/composeApp/build.gradle.kts` og bar `packageVersion = "2.0.7"`. Et
merge ville have rullet desktop to bump tilbage i stilhed. Fanget i hånden,
lukket uden merge; bumpet taget alene i `#627`.

**Fem landinger står paa main uden at være udsendt:** per-kilde til/fra
(#604), Del til Kaliv (#606), Svar-citater (#607), Onboarding (#608),
Offline-kø (#609). Næste naturlige skridt er **2.0.9** — se §4 for hvad et
bump rent faktisk rører.

**Landet 17/8, efter denne blok blev skrevet:** #615 (denne fils §0/§4/§9/§10
+ READMEs 2.0-afsnit og arkitekturdiagram), #616 (bump til 2.0.9), #617 (§8
lektie 37-38 + READMEs backend-linje), #618 (CAPABILITIES-hullet + DEVICE_TESTs
2.0-runde K1-K7), #619 (`/capabilities` rapporterer pptx og html).

**Hos Claude: intet.** Docs-arbejdet er kørt til bunds på nær tre ting, og alle
tre venter på Anders — ikke på arbejde:

- **§2's hardware-liste** (12/7) kan ikke skrives herfra. Hardware-bekræftelse
  er en observation, ikke noget der kan udledes af repoet. Skriver en session
  "QR-parring hardware-bekræftet" på hukommelsen, er det opdigt med en dato på.
- **`ROADMAP.md`** skrives ikke om uden en retningsbeslutning fra Anders — det
  er hans dokument at disponere.
- **`v2.0.9`-tagget.** Se advarslen nedenfor.

**TAGGET ER IKKE SAT, OG DET ER MED VILJE.** 2.0.9 er en TOSIDET release:
per-kilde til/fra og svar-citater kræver også den opdaterede worker
(`POST /rag/source/enabled` og turens `context`-felt findes ikke i en
2.0.8-rig). Tagges den før riggen er opdateret, tilbyder in-app-updateren den
til telefonen af sig selv, og to funktioner står og svarer ikke. Betingelsen er
**at riggen er opdateret** — ikke at nogen har sagt god for det. En besked der
blot lyder "kør" er ikke den betingelse.

**`STATUS.md` skrives ikke om.** Den er en log der vokser, ikke et dokument der
holdes ajour. **`TESTGUIDE.md` heller ikke** — den bærer sit eget
HISTORISK-banner fra 9/7 og peger videre; et arkiv der opdateres holder op med
at være evidens.

**Hos Sol:** v2-analysens tre #296-fund (grant delvist request-bound,
query-validation uden om faste fejlbodyer, write-modeller ikke strict);
protected writer accepterer ikke-finite timestamps; weak-reference
ownership-lifecycle; attempt-semantik + timeline-metrics; agent3-flaken i
`worker_agent3_task_surface.py` (KeyError 'run' — grøn lokalt med
`PYTHONPATH=.` fra `worker/`). Dertil opdelingen af #338 i slices mod
ADR-DC-001.

**Kræver riggen:** #230's okhttp-major (een chat-tur + een stemme-tur fra
Pixel'en), T-016's Pixel-bekræftelse + første workflow-baseline, og
bekræftelse af CodeQL-alertens lukning i code-scanning-visningen (PAT-scopet
kan ikke læse alerts-API'et).

**Aabent æstetisk valg:** paletten (#6F665C mod #5A4831) står stadig
tosidet gated og træffes med begge apps foran sig.

**MCP-adapter — bolden er hos Anders, ikke hos nogen af os.** Oplæg leveret
18/8: serverretningen (Kaliv udstiller read-flader) først, klientretningen
(Kaliv forbruger fremmede MCP-servere) udskudt. Sol har svaret teknisk i
`SOL-CLAUDE-SAMARBEJDE.md` og er enig i retningen.

**Stopregel i kraft — ingen containment-kode før Anders har afgjort:**
(a) om AppContainer + Job Object må erstatte kravspec'ens krav om separat
Windows-konto med NTFS-ACL (Sol: de er IKKE kontraktmæssigt ækvivalente, og
Tier-A er desuden bygget til én reviewet kommando uden netværk og uden
bidirektionel kanal — en MCP-host kræver en ny containment-kontrakt);
(b) hvilken neutral containment-grænse der i så fald er autoritativ, så
workeren ikke importerer `kaliv_dev_control` og bryder DevControls isolation.

Sols paritetskrav er accepteret som bindende: OpenAPI-overfladen skal bevise at
Agent 3/4-ruter og kontraktmarkører er uændrede med et MCP-mount til OG fra.
Importgraf alene er ikke nok.


**[30/7, aften — Android-palettens divergens PINNET. claim: Claude 30/7
23:20 — scope: token-JSON'ens `platformOverrides`, `Theme.kt`-kommentar,
`tests/workflow_android_palette_divergence.py` (ny).]**

Den tredje af Anders' beslutninger. Divergensen er lys-temaets dæmpede tekst:
tokenets `color.light.muted` er `#6F665C`, Androids `textMuted` er `#5A4831`.

**Målingen gør den til en beslutning og ikke en smagssag.** Androids værdi
giver **7,96:1** mod appens lyse baggrund — AAA. Tokenets ville give **5,13:1**
på samme baggrund — kun AA. Telefonen læses i dagslys, desktoppen sjældent, så
et "løft" ville koste læsbarhed præcis dér hvor den betyder mest.

**Hvorfor den kunne forsvinde tavst:** `KalivTokens.kt` genereres og ligger
allerede i Android-temaets pakke, men `Theme.kt` bruger stadig håndskrevne
`Color(0x…)`-værdier, og *ingen test sammenlignede de to*. En velmenende
oprydning — "migrér Theme.kt til KalivTokens" — ville have ændret udtrykket
uden at noget blev rødt.

Gaten er tosidet med vilje: den fælder både hvis Theme.kt migreres til
tokenets værdi, OG hvis tokenet løftes til Androids (det sidste ville ændre
desktoppens udtryk uden at nogen bad om det). Begge snubletråde er
sabotage-prøvet. Det æstetiske valg træffes stadig på rig-dagen med begge apps
foran sig; når det er truffet, opdateres `platformOverrides` og testen sammen.

**[30/7, aften — Computer Use I3/I4 REDDET fra `#163`. claim: Claude 30/7
22:55 — scope: `worker/app/desktop_*` (nye), `worker/app/main.py`
(gated registrering), `tests/worker_desktop_*` (nye), ROADMAP-milepæl.]**

`#163`s brugbare del er løftet i en frisk branch mod main — kun A-filer, ingen
af de fire tavse overskrivninger. Tre ting måtte gøres, og de er værd at kende:

1. **Registreringshooket lå i branchens `main.py`.** Det var en af de fire
   overskrivninger, og den bar også `browser_research`-registreringen. Kun
   desktop-delen er løftet, oven på mains udgave. Registreringen bor i
   `main.py` og ikke i entrypointet, fordi vision-broen skal wrappe
   `_run_tool_loop` i selve implementeringsmodulet: en flade monteret senere i
   ASGI-laget ville lade et enkelt tool-loop slippe uden om broen.
   `tests/worker_desktop_screenshot_entrypoint.py` prøver præcis det i en
   frisk proces.
2. **Versionsrodet er fladet ud.** `desktop_win32.py` var en 14-linjers shim
   over `_v2` — kollapset til ét modul. `desktop_action_preview_tool.py` var
   en facade, der rettede én closure-binding-fejl i ToolGate-installeren
   (screenshot- og preview-wrapperne delte én closure-celle, så den anden
   tildeling fik screenshot-wrapperen til at kalde sig selv rekursivt);
   rettelsen ER nu implementeringen, og `_legacy` er slettet. Tolv moduler
   blev til ti.
3. **Testene er kørt mod MAINS `capability_schema`** — den todelte model, uden
   branchens forkastede `external`-klasse. Alle grønne. Det var den måling,
   der afgjorde om redningen overhovedet var mulig.

Milepælen er defineret i `ROADMAP.md` som Computer Use (Tier B) med tre slices:
I3 (se) og I4 (foreslå) er landet **dvalende** bag `KALIV_COMPUTER_USE`; I5
(handle) er ikke bygget, og dens fysiske gate kan ikke bevises af CI. Navnet
`F5` er ikke genoplivet.

**[30/7, aften — D7 trin 1 LANDET. claim: Claude 30/7 22:32 — scope:
`worker/app/web_research_tool.py` (ny), `web_research_capability.py`,
`web_research_mount.py`, `tool_child.py`, `tests/worker_web_research_tool.py`
(ny), paritetsgatens del E.]**

Anders traf de tre åbne beslutninger (§0 nr. 7–9). Denne blok er trin 1 af
dem; de to andre venter stadig i køen.

*Hvad der landede:* `web_research` er nu henterens ene produktionskaldested,
registreret i `REGISTRY` bag `KALIV_WEB_RESEARCH_ENABLED` — samme flag som
ruten, monteret fra samme selvvagtende sted (`mount_web_research`).

Tre fund undervejs, som ikke stod i oplægget:

1. **Kontrakten fandtes allerede.** `web_research_capability.py` landede
   `WEB_RESEARCH_SPEC` før featuren, dvalende med `run=None`. Værktøjet
   **arver** den med `dataclasses.replace` frem for at deklarere en næsten
   ens kopi (lektie 29). Kontrakten forbliver dvalende, og en test pinner at
   de to ikke kan glide fra hinanden.
2. **Kontrakten manglede `purpose`.** Henteren kræver et formål —
   `build_intent` afviser et tomt — så specen som landet kunne kun producere
   blokerede kald. `purpose` er tilføjet med `additionalProperties: false`.
   Formålet er desuden præcis det, mennesket godkender på kortet.
3. **`isolate=True` var en halv sandhed.** Et isoleret barn bygger sin EGEN
   `REGISTRY` og kendte derfor ikke et gate-registreret værktøj: kaldet ville
   svare `unknown tool` på noget forælderen lige havde fået et ja til — og
   først den dag nogen satte `KALIV_TOOL_ISOLATION=process`. `tool_child`
   bootstrapper nu de gatede registreringer, og værktøjet navngiver sit eget
   flag i `env_allow` (`child_env` filtrerer alt andet væk). Bevist
   ende-til-ende: med flag hentede barnet en rigtig side (200, 559 bytes,
   ægte binding og opløst IP); uden flag `unknown tool`.

*Verificeret lokalt før landing:* CI's `ruff`-kommando ren, hele
`tests/worker_*.py` + `tests/workflow_*.py` grøn, paritetsgatens del E flippet
til at pege på det ene kaldested, `ACTIVATION_READINESS.md` +
`CURRENT_STATE.md` regenereret med deres egne generatorer (flaget dukkede op
som switch nr. 14 — det literale `os.getenv` på registreringsstedet er
grunden; mount-modulets konstant var en blind plet).

*Stadig i Claudes kø:* desktop-redningen (§0 nr. 8) og palette-pinnen
(§0 nr. 9). Rig-dagens form (c) er uændret og hører til rig-dagen.

**[29/7, sent — Anders har truffet beslutningerne. Otte PRs lukket, fire
beslutninger registreret, t021 STOPPET af ejerskabsaftalen.]**

*Lukket efter beslutning, hver med egen-delta målt umiddelbart før lukning:*
**#98/#140/#133** overhalet af main (kapaciteten ligger der, og main's udgaver
er de hærdede: versionsbundet loader med fail-closed resume for #140, +47
linjer inkl. *authoritative time terms* for #133). **#115** lukket som
beslutning — dens to filer ER nye, men modulet ville være det fjerde
peer-binding-modul med syv duplikerede hjælpere (§8 lektie 29).
**#138** lukket som beslutning: seks reelt nye filer, men en konkurrerende
besvarelse af samme spørgsmål som den landede #136-barriere; launcheren og
easy-entry-UX'en kan genimplementeres oven på barrieren hvis rig-dagen viser
behov. **#144** lukket: main's wizard vinder (fail-closed `ea7d593e`,
lint-gated, bundet i den retained loader).

*Afgjort og registreret i `ROADMAP.md`:* **D7 = vej 1** (scriptet skal kalde
henteren; frys det nuværende som `.retained`, paritetsgate som supplement) ·
**WCAG delt** — `semantic.warning` rettet `#B9823F` → `#AA773A` (samme kulør
og mætning, kun lyshed; 2,66 → 3,11), de to brandfarver bliver stående båret
af guidens *"farve er aldrig eneste signal"* · **fase-signalet: ja**, workeren
sender sin fase med, som planlagt opgave · **Android-paletten er STADIG
ÅBEN** — se nedenfor.

**To ting hvor målingen omgjorde anbefalingen — læs dem før du handler:**

1. **t021 er IKKE "en gammel og en ny generation".** Jeg anbefalede at lukke
   25/7-generationen. Målingen siger nej. #183-kæden (3 PRs, skåret 27/7, 175
   commits bag main) er en **port af kernen** — dens 31 filer er alle med i
   #167-kædens 45, hvoraf 26 er byte-identiske. #167-kæden (16 PRs, skåret
   25/7, 607 commits bag) bærer **14 filer som #183-kæden slet ikke har**:
   `Agent3ValidationScreen.kt`, `Agent3ValidationDevApp.kt`,
   `Agent3ReadonlyTaskClient.kt`, `agent3_test.go`, kampagne- og
   task-UI-valideringen. Ingen af kæderne er ancestor af den anden. At lukke
   #167-kæden ville kassere den halvdel.
   **Og vigtigere:** begge kæder rører `worker/app/agent3/**` og
   `tests/*agent3*` — **Sols domæne**. Hverken landing af #183 eller lukning
   af #167-kæden er vores at gøre alene. Sat på Sol-agendaen.

2. **Android-paletten kunne ikke løftes som anbefalet.** `#5A4831` (Android)
   og `#6F665C` (token) adskiller sig ikke bare i lyshed: S = 29,5% mod 9,4%
   — en varm brun mod en næsten neutral varmgrå. At løfte tokenet ville ændre
   desktops udtryk, ikke rette en kontrast. Tre reelle veje står i `ROADMAP`,
   ingen af dem gratis. Kræver en skærm.

**Sol-agenda (næste fælles session):** t021-knuden (begge kæder), #165/#166/#167
(små, 3-5 egne filer hver — de store afvigelsestal var lektie 31-artefakten),
og `external` som adgangsklasse (`_V2_RISK` i Sols kode; gaten afviser korrekt
indtil da).

**Sporene:** t022 og t033 er levende (PRs oprettet mens der blev arbejdet 29/7)
— behold. t023 er et ægte produktvalg, anbefalet behold men efter rig-dagen.

**[29/7 — tre landet, seks lukket som allerede landet, resten klassificeret.]**
Main = `2f8b4d8`. Landet gennem fuld CI: **#162** (Stage A-operatør-UX;
ps1'ens `-BackendHost` forenet med loopback-advarslen fra `c3a3ef2d`,
param-default ærer `MODELRIG_HOST`; phone-testens pin opdateret til den
flettede kontrakt + gate mod usynlig loopback), **#136** (T-019
pilot-barrier + operator; `schedule_runner.py` installerer nu BÅDE T-018
single-flight og barrieren, som er dormant uden
`KALIV_SCHEDULER_PILOT_BARRIER_DIR`), **#156** (read-only Control Center i
alle fire lag; `mount_web_research` bevaret i entrypointet, desktop
`App.kt` håndvævet mod main's nyere udgave, `ROUTE_INVENTORY.md`
regenereret — gaten fangede selv det nye endpoint). **#149+#151–#155
lukket** som beviseligt landet (ancestry, lektie 31). Klassificeret til
retning med evidens på PR'erne: **#138** (konkurrerende hold-mekanisme til
den landede barrier; dens ps1 er ældre end #162-foreningen), **#144**
(`schedule_api`-regression + afvigende 844-linjers wizard mod main's
fail-closed ~125), **#133**. Nyfundne **#165/#166/#167** er store
base=main agent3-udgaver — **Sols domæne**, rør dem ikke uden aftalen.
Autoritativt: **56 åbne PRs**; t033 og t022 er aktive (#215/#216 oprettet
29/7, mens der blev arbejdet). Tallene i blokkene nedenfor er historik pr.
27/7.

**[29/7, sent — t021 er målt igennem, og bolden ligger hos Sol.]** Retningen er
valgt: **byg på `#183`-kæden**, kør ikke `#167`-stakken færdig. Målt: kæderne
deler 31 af 45 filer, 26 byte-identisk; `#183` er strengt supersæt på
testfladen, og dens `production_mount.py` composer selv current mains flade.
Dormans (invariant 11) er verificeret **empirisk** intakt i `#183` — flag usat
eller `0` giver `mount_agent3() == False` og nul ruter, `=1` giver ni; se
lektie 32 for hvorfor tællingen først pegede den anden vej. Suite 171/171 på
tippen.

**Blokeret på ét svar fra Sol:** `#183` indfører en anden `mount_agent3` i
`agent3/production_mount.py`, som wrapper `api.mount_agent3` og sætter
`agent3_full_surface_mounted`. Kontraktpunkt 1 udpeger `mount_agent3` som
eneste ejer med `agent3_mounted`. Hvilken funktion og hvilken state-nøgle der
er kontrakten efter landing, er hans kald — spørgsmålet står i
`SOL-CLAUDE-SAMARBEJDE.md` under 29/07.

**Når svaret findes:** merge `#183`-kæden mod nuværende main (**ikke**
fast-forward — grenen mangler 28 testfiler main har, heriblandt web-research,
Control Center, Stage A-operatørerne og kontrast-gaten; alle skal være grønne
på resultatet), port de 7 task-UI-valideringsfiler fra `#181`/`#182`, luk
`#168`–`#180` med evidens pr. PR. **`#167` røres ikke** — den ændrer
`agent3/task_readiness.py`.

**Port IKKE `#167`s `/confirm`-linje.** Den erstatter mains approval-aware
handler med en plain forward og ville fjerne invariant 5 fra host-laget. Se
lektie 32.

**[29/7, aften — Agent 4 findes, og T-numrene kolliderer. Autoritativt: 62
åbne PR'er (`#143`–`#228`), ikke 58.]** En ekstern read-only repoanalyse
(29/7, uden lokal klon) fangede en stak jeg selv havde misset — se lektie 33.

**Agent 4, `#220`–`#228`, verificeret lokalt:** ni stakkede PR'er skabt mellem
17:22 og 20:15 samme dag. 35 filer: 16 moduler i `worker/app/agent4/**`, 7
tests, 11 docs. **Dormant og standard-library-only** — dens `agent4/README.md`
siger eksplicit at runtime-aktivering, API-ruter og baggrundstråde er bevidst
fraværende, og at `import app.agent4` er bivirkningsfri og ikke kan starte
Agent 3-arbejde. **Nul filoverlap** med t033-stakken. Håndværket matcher resten
af repoet.

**KOLLISION — skal afklares før flere slices.** Agent 4 bruger milepælene
`T-030` → `T-034`. De numre er optaget:

| Nummer | Betyder allerede | Agent 4 bruger det til |
|---|---|---|
| `T-030` | lukket med evidens (Agent 3) | foundation/lifecycle |
| `T-031` | Windows-isolationen `[RIG]` | durable checkpoint store |
| `T-032` | **D6 — data-sharing policy, afgjort 27/7** | resource lease kernel |
| `T-033` | memory-beskyttelse (`#143`, `#202`–`#212`, `#214`) | retry-klassifikation |
| `T-034` | **D7 — web-research-orkestreringen, afgjort 27/7** | health watchdog |

To af dem er *afgjorte beslutninger* i `ROADMAP.md`, og `agent/t033-*` dækker
nu to urelaterede spor samtidig. Enhver `T-03x`-reference i ROADMAP, HANDOFF
eller en commit-besked er dermed tvetydig. Kollisionen er dokumentationsmæssig,
ikke i kode — og derfor billig at rette nu og dyr at rette senere.
**Anbefaling: omdøb Agent 4's milepæle til et eget rum (`A4-01` … `A4-05`) og
branch-prefixet til `agent/a4-*`, før der lægges flere slices ovenpå.** Det er
Anders' kald.

**Hvad den eksterne analyse ellers ramte og missede.** Ramte: PR-tallet (62,
vores eget var stale), og dens t021-dom er uafhængigt den samme som vores —
`#183` supersederer, port kun det unikke, luk resten. Missede: dens
*"aktuel head-CI kunne ikke verificeres"* var et værktøjsforbehold, ikke en
kendsgerning — der ligger **tre grønne runs** på `06859e0` (`ci` + `codeql`,
20:36 og 20:40Z), så dens dom om "svag integreret sandhed" hviler delvis på et
hul der ikke findes. Og dens RAG-påstand (*"bevidst small-scale indtil 1k/10k
benchmark er kørt"*) er forældet: benchmarket ER kørt — recall@5 = 1,0 ved
10.000 chunks, query p95 3.671 ms, ingest >35 min ved 39% GPU. Der mangler ikke
måledata; der mangler en beslutning om batching af embedding-kaldene. Dens head
var én landing bagud (verificeret som ancestor af main).

**Beslutningsreglen er værd at adoptere** (analysens skarpeste bidrag): *en PR
må kun stå åben, hvis den er **aktiv**, **bevidst parkeret med et
genstartskriterium**, eller **evidence-only for den valgte kandidat**.*
Historiske og supersederede branches lukkes med en præcis pointer til
afløseren. 62 åbne PR'er er symptomet på at reglen ikke har været håndhævet.

**[30/7, eftermiddag — Sol-agendaen er gennemført, og fem PR'er er landet.
Autoritativt: 35 åbne PR'er, ned fra 62 i går.]** Sol reviewede og godkendte
mount-kontrakten, lukkede `#165`/`#166`/`#167` (t021 dermed helt lukket),
forkastede `external` til fordel for den stærkere todelte model
(`access` **plus** `network.mode=public`), tog eksplicit ejerskab af Agent 4 og
omnummererede `T-030`–`T-034` → `A4-01`–`A4-05` med prefix `agent/a4-*`.
**Claim-reglen er accepteret** i formen: præcist scope før arbejdet, fire
timers udløb uden aktivitet, Anders kan altid overstyre.

Landet i dag, hver med sit eget grønne run og bekræftelse ad to veje:
`#242` (`3dc1e86`, ægte fast-forward), `#243` (`b948a27`), og hele
`#251`-stakken nedefra — `#246` (`88e9ba0`), `#250` (`b2b4810`), `#251`
(`d6f2459`).

**To ting er værd at bære videre fra de landinger.** For det første: `#251`
så ud som seks filer i sin egen diff, men dens reelle delta mod main var 66
filer i tre lag. Mål altid tre-punkts mod main, aldrig PR-diffen mod dens base
(lektie 31). For det andet: stale-tjekket (lektie 36) fandt **syv bagudliggende
filer i hvert eneste lag** — begge `CapabilityDescriptorV2.kt`,
`capabilityschema/schema.go`, `capability_schema.py`, `routing_preview.py` og
to tests. I `#246` var en af dem en revert, der skulle rettes i hånden; i
`#250` og `#251` var de blot gamle og gik rigtigt af sig selv. Samme overflade,
modsat udfald — det er præcis derfor tjekket skal køres.

**Til protokollen:** landingerne flytter Milestone 3-kandidaten til main; de
beviser den ikke. Intet fysisk er kørt, ingen kampagne udført,
`production_activation` er uændret.

**[30/7, sent — oprydningen er færdig. Autoritativt: 19 åbne PR'er, ned fra
62 i går.]** Ti dependabot-PR'er behandlet (otte landet, `#232` lukket på et
rødt `android-compile`, `#239` lukket til fordel for at bringe desktops Gradle
op på Androids 8.14.4 frem for et 8→9-spring på kun den ene klient), og
t023-stakken `#190`–`#196` lukket: klassifikationen viste nul unikke filer, og
diskriminatoren fandt præcis **én** afvigende fil — hele stakkens resterende
bidrag var én sætning i `AGENT3_CANCELLATION_CONTRACT.md`, porteret ordret som
`1308a554`. Invarianten var allerede håndhævet i `_TERMINAL_RUNS`; dokumentet
sagde det bare ikke.

**Fælde værd at kende:** "nul unikke filer" betyder kun *ingen nye* filer. Både
t023-stakken og `#235` (browser-use-bumpet) blev stemplet sådan af den første
klassifikation — men `#235` er et versionsbump til en eksisterende fil, ikke en
skal. Diskriminatoren i lektie 36 er den rigtige test, ikke fil-optællingen.

**De 19 tilbage er arbejde, ikke oprydning:** 13 t033 (Sols aktive spor), fire
Agent 4 (`#253`–`#256`, Sols), `#235` (parkeret til D7's trin 1 er afgjort) og
`#163`.

**`#163` er den eneste PR, der hviler på "bevidst parkeret"-klausulen — og
klausulen kræver et genstartskriterium, som ikke findes.** Beslutningen fra
24/7 var *"merges ikke; desktop beholdes til F5"*, men PR'en havde **nul
kommentarer**, og **`F5` optræder ikke i hverken ROADMAP eller HANDOFF**.
Begrundelsen er nu skrevet på PR'en: research-delen er en konkurrerende
implementering af mains web-research-sti, mens ti `desktop_*`-moduler er reelt
nyt arbejde, der ikke findes andre steder (28 filer i alt). **Anders' kald:**
definér F5 i ROADMAP, eller omformulér kriteriet til noget, der findes. Et
kriterium, der peger på en udefineret milepæl, er en tidsubestemt udsættelse
med en pænere etiket.

**To udestående verifikationer fra dagens landinger**, begge noteret på deres
PR'er og i commit-beskederne: `#230`s okhttp-major bærer ti klienter i
`android/.../net/` — CI beviser compile og mockwebserver, ikke en rigtig
forbindelse, så én chat-tur og én stemme-tur fra Pixel'en mod riggen mangler.
Og `#231`s attest-build-provenance kan slet ikke bevises af CI, fordi
`build-and-release.yml` ikke kører på push: **første rigtige tag er prøven.**

**[30/7, morgen — t021 er AFSLUTTET, og vi kørte om kap med Sol undervejs.]**
Convergence-merget landede som `4e8acd33` (Sols kontrakt overlevede, verificeret
linje for linje; `#183` auto-lukkede som merged), task-UI-halen som `c858cea4`
med main's fil som core — branchens 25/7-snapshot ville stille have rullet
`CAMPAIGN_PROOF_COUNT` tilbage — og en sti-baseret sibling-loader, fordi fire
gates loader kampagnefilen med `spec_from_file_location`. `#168`–`#182` lukket
som superseded med egen-delta-bevis pr. PR. **Kun `#167` står åben i t021 — den
er Sols.**

**Race-fundet:** en parallel session (Sols, `agent3:`-titlen) eksekverede samme
"Næste"-plan samme morgen: lukkede `#184`/`#185` kl. 06:04-06:05 og åbnede
`#241` kl. 06:02 med **samme port** — samme core-valg, samme sti-baserede
loader, uafhængigt fundet. 7 af 8 filer byte-identiske med det landede. Den
landede wrapper står (registrerer i `sys.modules`, så monkey-patch-gates og
normal import rammer samme objekt); `#241` lukket med fuld kreditering.
Konvergensen validerer løsningen — men racet koster dobbeltarbejde.

**Foreslået koordinationsregel (Anders' kald):** den der tager et
"Næste"-punkt fra §9, skriver *claim: <navn> <tidspunkt>* ved punktet og lander
claimen, før arbejdet startes. HANDOFF er den eneste fælles hukommelse; et
uclaimet punkt er frit, et claimet er optaget.

**[27/7 — status på køen.]** Alt der kunne afgøres uden hardware, uden en skærm
og uden en beslutning fra Anders er ryddet. Det der står tilbage er blokeret på
netop de tre ting:

- **Riggen:** workflow-baselinen (projektets første completion rate), T-031's
  fysiske Windows-isolation, og de fysiske Agent 3-pilotter. *(PR #135 stod her
  først; den blev lukket samme dag som overhalet — single-flight ligger på main,
  se #71.)*
  Baselinen har nu ét indgangspunkt: `scripts/workflow_baseline_one_click.py`.
  `--check` svarer på om riggen er klar uden at køre eller skrive noget, og hver
  blokering bærer rettelsen i beskeden frem for i gate-tabellen.
- **En skærm:** guidens tilstande (hover 4-6%, focus-ring 2 px, pressed 8%),
  breakpoints og 200% zoom. Alt tekstuelt, semantisk og kontrastmæssigt er
  derimod målt og lukket. **Bemærk:** de kræver den *kørende* app, ikke bare
  øjne — designpakkens to mockups er begge 1491×1055 enkeltskærme, og et
  statisk billede viser ikke en hover-tilstand.
**[27/7, sent — research er valgt, og fem stykker er landet.]** D6's
fladebeslutning er truffet: `research` først. Landet siden: capability-
kontrakten (dvalende, bevidst **ikke** i `REGISTRY`, fordi `ToolGate.is_enabled`
bruger en deny-liste og en import derfor ville åbne fladen), flag-vagten
`mount_web_research` (kun præcis `"1"` tæller), bekræftelseskortet udvidet til
udadgående læsninger (`network == "public"`, inert for alle ni eksisterende
værktøjer), `build_intent` fra URL med fem sikkerhedsvalg, og en selvopdagende
paritetstest over de fire `_public_address`-kopier.

**De fem designvalg er truffet 27/7 og står som D7 i ROADMAP:** registrering
sidst (det er den handling der tænder fladen), et menneskes afvisning
efterlader intet spor i v1, `blocked` for vores egne grænser og `failed` for
modpartens fejl, 2 MB-loftet afviser frem for at afkorte, og ét ja rækker til
ét kald. Orkestreringen skal altså ikke længere beslutte noget — kun bygge.

**Tilbage: orkestreringen.** `prepare → claim → issue → pin → prepare → execute
→ complete`. Den er udelelig — hver fejlsti skal stadig kalde `complete()` — og
den skal skrives i sammenhæng.

**Fælde til den der skriver den:** `ResearchPeerAuthorizationBridge` har
`prepare` og `verify`. Den har **ikke** `authorize` eller `evidence`. Jeg skrev
et helt modul mod de to opfundne navne 27/7; det importerede fint og ville have
braget ved første kald. Kasseret, ikke merget. Læs broen før du kalder den.

- **Anders:** tre tokenpar under WCAG AA som er brandfarver eller semantik; Politikken er besluttet og pinnet (`public` automatisk,
  `operational`/`private` bekræftet, `secret` forbudt, 300 s, kategori-kun), og
  `research` håndhæver allerede — men `agent_v2`, `agent3` og `connector` er
  slukkede, og at tænde en er en ny beslutning. **Fire tasks venter på præcis
  den ene:** T-034, T-036, T-037, T-038. Dernæst: tre tokenpar under WCAG AA
  som er brandfarver eller semantik;
  Android-paletten i `theme/Theme.kt`, der har egne værdier med *bedre* kontrast
  end tokenet (7,28 mod 4,50) — så valget er konsistens kontra kontrast, ikke
  en rettelse; og fase-signalet i chat-streamen. Alle tre står i `ROADMAP.md`
  under Åbne beslutninger med tallene.

**Dependabot er tom.** Fra elleve åbne PR'er til nul. Kun to af dem var
blokeret af deres eget indhold; resten hang på to infrastrukturrødder ingen PR
pegede på — Kotlin-versionen (adskilt for desktop og Android) og
Android-platformen (AGP 8.9.1 + compileSdk 36, ikke 8.6.0 som fejlbeskeden
antydede).

**Fem ægte huller i `read_scope.py`** — reserverede DOS-navne (`CON`, `NUL`,
`COM1`), trailing dot/space, 8.3-aliaser og alternate data streams slap igennem
sti-grænsen. Relevant for Sol og for enhver der bygger ovenpå: alle fem ligger
*inde* i roden, så et rod-scoped restricted token ville ikke fange dem. For
netop dem er Python-tjekket ikke bælte til seler — det er det eneste lag. Se
`ISOLATION_DESIGN.md` §4.1.

**`ci.yml` kan nu køres på forlangende** (`workflow_dispatch`). Før kørte gaten
kun på push til main og på pull requests, så en branch kunne ikke få CI's dom
før nogen åbnede en PR — og lokalt grønt er ikke CI-grønt.


**Ingen af disse er blokeret på kode. De er blokeret på rig, telefon,
branch-ejer eller en beslutning.**

**[25/7 — LÆS `RIGDAG.md` FØRST.]** Kørebogen for rig-dagen ligger nu i repoet
og sekvenserer alt hardware-arbejdet i to pas i samme session. Det afgørende
fund den bygger på, som ikke er indlysende:

> **Kandidaten `8e40103` indeholder IKKE dagens arbejde.** Målt: workflow-
> harnessen, Sols completion-kontrakt, Agent 3-cockpittet og desktop-designet
> (titelbjælke/ikon-rail/1240dp) findes ingen af dem på den. Den bærer stadig
> den gamle `KalivScreens.kt` og `1000.dp`.

Ikke en fejl — kandidaten blev frosset 24/7 og alt fra 25/7 landede på main
bagefter. Men rig-dagen på `8e40103` kan altså **kun** validere kandidaten;
dagens arbejde skal med i 1.58.146 og testes i pas 2. To separate rig-dage
ville koste dobbelt, så pas 2 hører til samme session.

**Leveret 25/7, alt på main og CI-grønt:**
- `eval/workflows_v1.json` + `scripts/workflow_{runner,eval,contract_adapter}.py`
  — måler om et workflow bliver FÆRDIGT, ikke om værktøjet blev valgt. Sols
  kontrakt (`worker/app/agent3/workflow_completion.py`) er den autoritative
  dommer; adapteren producerer evidensen. Første baseline kræver riggen.
- `ROUTE_INVENTORY.md` + `scripts/route_inventory.py` — ruteoverfladen aflæst
  fra OpenAPI, ikke fra importgrafer. Dormans-invarianten er nu en test:
  ingen `/experimental/agent3`-rute må serveres uden flaget.
- `KalivAgentCockpitA3.kt` — 1b på Agent 3 bag en persisteret udvikler-kontakt,
  default fra. V2-cockpittet er urørt og stadig standard.
- Desktop-designet genskabt efter mockup'en (titelbjælke 40dp, per-skærm rail,
  1240dp ramme, boblebredder 460/620, Enter sender).
- `impact` på bekræftelseskortet, så klienter ikke gætter DESTRUCTIVE ud fra
  værktøjsnavne.

**PR #135 (T-018 single-flight): PAUSED, besluttet 25/7.** Ikke kvaliteten —
rækkefølgen. T-018 er P2; T-019 er P0 og skal måle præcis den
`schedule_runner.py`/`schedule_runtime.py` som #135 ændrer. Adopteres af
Claude som host-ejer EFTER promoveringen. Se `SOL-CLAUDE-SAMARBEJDE.md`.

**⚠ PR #163 MÅ IKKE MERGES FØR RIG-DAGEN — uanset at den er grøn.** Den hedder
*"browser: activate confirmed read-only research boundary"*, men er reelt hele
computer-use-stakken: **8.671 linjer over 34 filer** (`desktop_action_plan`,
`desktop_capture`, `desktop_contract`, `desktop_input_execution`,
`desktop_physical_gate`, `desktop_vision_bridge`, `desktop_win32` m.fl.). Og
dens base er `agent/unified-candidate-1.58.147` — **den frosne kandidat**.

Tre uafhængige grunde: (1) 8.671 nye linjer i kandidaten ville gøre enhver
rapport fra rig-dagen til evidens for kode der ikke længere findes
(F-1802/F-1503). (2) Computer-use er gated bag T-031 (isolation, `[RIG]`), som
afhænger af T-030 og T-005 — og T-005 er en åben P0; HANDOFF §9 pkt. 5 siger
*"efter gates 1+2"*. (3) `desktop_policy.py`'s tolerance (6) er stadig et gæt.

Samme fejlklasse som #135 — arbejde der ændrer præcis det en ikke-kørt
validering skal måle — bare 14 gange større. **CI-farve er ikke
merge-kriteriet, når basen er frossen.**

**Arbejdsdelingen med Sol er skrevet ned og accepteret** i
`SOL-CLAUDE-SAMARBEJDE.md`: Sol ejer `worker/app/agent3/**`, Claude ejer host,
klienter, scripts og CI. Fem kontraktpunkter kræver paritetstest FØR ændring.

1. **[ANDERS — PORTEN]** Valideringsrunden: `VALIDATION-1.58.49.md` +
   `deploy\validate-rig.ps1` (mekaniske tjek → `logs\validate-rig-latest.md`)
   + RAG-kalibrering (RAG_DESIGN §5: 5 spørgsmål du kender svaret på + 3 du
   ikke gør). Flytter 0 benchmark-point direkte — **men alt over den er
   rabatteret uden hardwarebevis**, og Agent 3's egen evidence-gate kræver den.
2. **[ANDERS — device]** APK 182 (`kaliv-latest.apk`): D7–D10 (toggles synlige,
   overlever genstart, egress kun når TIL) · **E6–E9: klienten er nu STRENGERE
   — fejler noget højlydt, er det et fund, ikke en regression** · #2a trin 3–5
   kun via "test jeg" (to blinde forsøg fejlede før).
3. **[ANDERS — kandidatkæden]** PR #161 `agent/unified-candidate-1.58.147`
   (head `8e40103`, 424 foran / 0 bagud main, alle 4 gates grønne på exact
   head, mergeable clean) er den rig-testede kandidat: preflight ✅, Agent 3
   fysisk ✅, model-eval 30/30+30/30, RAG ✅. **Udestår fysisk:** voice
   (Pixel fik `401 invalid token`) + scheduler-pilot. PR #162 (Stage A
   ét-klik, base=#161) fixer netop operatør-frictionen. Flow:
   `START_STAGE_A_TEST.cmd` → `START_REMAINING_PHYSICAL_TESTS.cmd` → review
   → SEPARAT eksplicit beslutning → ff-merge + tag v1.58.147. **Merges
   ALDRIG autonomt** — PR'en forbyder det selv. De fleste andre åbne PRs
   stacker mod denne kæde; merge dem ikke enkeltvis udenom. PR #1/#3 er
   lukkede (agent3 kom ind via mount, 1.58.131–135).

   **PROMOVERING — main er rykket (24/7, selvforskyldt):** main bar
   `2e2a29a` da kandidaten blev frosset; den er nu `95c1014`+ (rene
   docs-commits på HANDOFF.md, ingen kode). `--ff-only` er derfor IKKE
   længere mulig. **Det rammer ikke rig-kørslen** — `freeze_check`
   sammenligner checkout'ens egen HEAD mod tag-SHA'en (linje 273-274), så
   en clean checkout af `8e40103` fryser grønt uanset hvor main står.
   **Ren løsning: sæt tagget `v1.58.147` direkte på `8e40103`** (build-and-
   release trigger er `v*` på enhver commit) — så peger tagget på præcis
   det træ der blev fysisk testet, og main kan merges bagefter med en
   almindelig merge-commit. Tag ALDRIG en merge-commit her: dens træ ville
   indeholde docs-deltaet og fælde den byte-eksakte attestation (F-1802/
   F-1503). **Lektie: push ikke til main mens en frossen kandidat venter
   på rig-dag** — heller ikke docs. *(Den lektie er brudt igen 25/7:
   main står nu på `961fd61`, ca. 8 commits foran kandidatens base — desktop-
   design, workflow-harness og impact-fixet. Vurderingen hver gang: kørslen
   på riggen er upåvirket, og tag-på-`8e40103` er stadig den rene vej. Men
   omkostningen er reel — merge-arbejdet efter promoveringen vokser, og
   normen bør være at bygge på branches til kandidaten er landet.)*

   **[NÆSTE RIG-HANDLING efter promoveringen] Kør workflow-harnessen.**
   `scripts/workflow_runner.py` kører de 14 workflows i
   `eval/workflows_v1.json` mod en levende worker og optager transcripts;
   `scripts/workflow_eval.py` scorer dem. Første kørsel giver et
   **baseline completion rate** — første gang projektet har et tal for om
   Kaliv faktisk *løser* opgaver, ikke bare vælger rigtigt værktøj:
   ```
   PYTHONPATH=worker python3 scripts/workflow_runner.py \
       --model hermes3:8b --out validation/workflow-run-latest.json
   python3 scripts/workflow_eval.py \
       --transcripts validation/workflow-run-latest.json
   ```
   W-10 godkender aldrig (`never_approve`) — den beviser gaten, den sletter
   ingen model. W-08/W-09/W-11 skriver kun til
   `~/kaliv/workflow-eval-scratch.md`.

   **Model-eval-fixturen (gammel åben sag, nu LUKKET):** basis-fixturen
   `eval/agent3_model_tasks.json` er byte-identisk på main og kandidaten.
   Rig-kørslen viste at problemet IKKE var risk/impact-forveksling i
   fixturen, men at basis-sættet **er ældre end Agent 3's finere
   risk-vokabular**: planneren klassificerer `pull_model`→`admin` og
   `delete_model`→`destructive` (`agent3/integration.py`), mens fixturen
   forventer `write` (som matcher `tools.py`'s grovere `Risk`-type).
   Kandidaten løser det med en versions-bundet, fail-closed override-fil
   (`eval/agent3_model_tasks_stage_a_overrides.json`) der lader det frosne
   basissæt være urørt. **Port den IKKE til main** — den hører til
   kandidatens testede enhed. Den tidligere beslutning om ikke at gætte
   var rigtig: gættet ville have været "skriv impact i fixturen", og det
   er ikke svaret.
4. **[KRÆVER RIG]** I0b: Windows-rettighedslaget (Job Object m. kill-on-close +
   grandchild-reaping, reduceret token, lav integritet). **Uden Job Object
   reaper subprocess-kill ikke børnebørn på Windows** — markeret i koden.
   Dernæst UPDATER_DESIGN §4a (updater self-update).
5. **[KRÆVER RIG]** Computer-use I1→I5 (ISOLATION_DESIGN §5), efter gates 1+2.
   Policy-laget er færdigt; **tolerancen (6) i `desktop_policy.py` er et GÆT
   indtil den kalibreres mod rigtige apps** (§6.2).
6. **[ANDERS — beslutning]** F-006: cloud-reads er ugatede (dokumenteret
   ærligt). Agent 3 er svaret. F-007: desktop-credentials i klartekst
   (DPAPI-handoff klar). F-011: MCP read-only spike — **først efter
   valideringen** (ny capability).
7. **[GÆLD]** Notion-status for 1.58.44–52 OG 1.58.141/142/144 er IKKE
   afleveret. 44–52: connectoren forsvandt (auth-fejl). 141–144: connectoren
   LÆSER fint men afviser ALLE skrivninger med "No approval received" —
   7 forsøg over 2 sessioner (23–24/7), selv en enkelt property-opdatering.
   Paste-klar tekst ligger i outputs (`notion-gaeld-141-144.md`). Prøv ikke
   flere skrivninger før Anders har bekræftet at connectoren virker igen —
   test med en lille property-opdatering før du bygger lange poster.
8. **[SELV-DISCIPLIN — VIGTIG]** **Der er ÉN session. Der er aldrig en
   "parallel session".** Anders retryer timeout'ede svar; containeren beholder
   arbejdet (commits, filer, endda pushes), mens den nye kontekst ikke har det.
   Resultatet: du finder arbejde i dit eget træ som du ikke husker.
   **Konkluder aldrig at en anden har lavet det.** Din sandbox er din alene —
   ingen anden kan lægge ukommitterede filer i dit arbejdstræ.

   **Tjek reflogen FØR du attribuerer noget:** `git reflog --date=iso | head`.
   `commit:` = du skabte den lokalt. `pull:`/`rebase:`/`fast-forward` = den kom
   udefra. 16/7 byggede jeg selv JobStoren (715e06a, 12:59) og I1 read-scope
   (d94577e, 18:09) — og fortalte Anders at "den parallelle session" havde
   gjort det. Det var forkert, det stod i release-noter og i dette dokument, og
   Anders måtte selv fange det. Efter et retry: kør `git status` + `git reflog`
   + `git log origin/main -1` og genopbyg sandheden derfra, ikke fra en
   fortælling.

---

## 10. Dok-kort

`STATUS.md` linje 3 = altid-aktuel one-liner (resten: release-historik) ·
`ROADMAP.md` = retning, lukket-endet ved V15 · `DEVICE_TEST.md` = test-
runbooks (S1–S4 streaming) · `TROUBLESHOOTING.md` = symptom→fix fra faktiske
fejl · `MODELS.md` = modelvalg + voice-modeller · `CLOUD_TOOLS.md` =
cloud-agent-status · `DRIFT.md` = Tailscale/backup/geninstallation ·
`scripts/START_HERE.md` = opstart · `assets/design/kaliv-ui-guide/` =
design-autoritet, og `kaliv-ui-tokens.json` er **eneste** tokenkilde:
`scripts/design_tokens.py` genererer `KalivTokens.kt` til begge moduler, og
desktops `Brand.kt` læser dem frem for at kopiere hex ·
`scripts/workflow_baseline_one_click.py` = workflow-baselinen, `--check` for
preflight alene · `brand/05_handoff-docs/` = **OVERHALET**, ModelRig-era med
safirblå; læs den ikke som gældende · Historiske (bannered): TESTGUIDE,
PLAN_v1.13.0,
ALVA_VOICE_ROADMAP_DELTA, CLIENT_BUILD_AND_TEST, KRAVSPEC_V5 (leveret).

**Tilføjet i 2.0-æraen:** `docs/design/DDR-001*` = designbeslutning efter
ADR-mønsteret, og `assets/design/kaliv-ui-tokens.json` er fortsat eneste
tokenkilde · `docs/agent3/ADR-A3-001_CHAT_AGENT_SURFACE.md` = chattens
adgang til Agent 3 · `AGENT_4_ARCHITECTURE_DECISIONS.md` = det KOMPLETTE
ADR-indeks for Agent 4 · `ROUTE_INVENTORY.md` = genereret ruteliste (prober
workerens OpenAPI) · `docs/devcontrol/dc-l*/` = evidens pr. DevControl-slice.
**Advarsel, præciseret 17/8** (den tidligere udgave slog fire dokumenter
sammen og var upræcis om alle fire):

- `CAPABILITIES.md` — **aktuel.** Opdateret 17/8; capability-tabellen har alle
  syv nøgler efter #619.
- `DEVICE_TEST.md` — **aktuel** og den levende testrunbook. 2.0-runden K1-K7
  dækker QR, per-kilde, citater, deling, offline-kø og onboarding.
- `TESTGUIDE.md` og `HISTORY.md` — **arkiver med eget banner.** De er
  optegnelser, ikke gældende. Opdatér dem ikke; de mister deres værdi som
  evidens i samme øjeblik.
- `ROADMAP.md` (31/7) og `STATUS.md` (28/7) — **før 2.0-æraen.** ROADMAP venter
  på en retningsbeslutning fra Anders; STATUS er en log der vokser og skal ikke
  skrives om. Læs begge som historik.
