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

1. `git fetch` FØRST og vælg version over origins `VERSION` (parallelle
   sessioner!) → `python3 scripts/version_tool.py set X.Y.Z` (synker alle fire
   sites) → **`versionCode` = origins + 1** (slå det op i origins
   build.gradle.kts — skriv ALDRIG et fast tal her, F-008) →
   `python3 scripts/version_tool.py check`.
2. Kør ALT lokalt: `(cd worker && PYTHONPATH=. python3 ../tests/worker_*.py)` ·
   `(cd backend && go build ./... && go vet ./... && go test ./...)` ·
   `python3 tests/workflow_*.py` · `ruff check --select E9,F63,F7,F82`.
   **Kotlin kan IKKE kompileres her — CI er den eneste verifikation.**
3. `git add -A && git -c commit.gpgsign=false commit -q -F /tmp/m.txt` →
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
   Stående ordre, spørg ikke først. **Connectoren har været nede siden 16/7;
   genbekræftet 19/7 (tool_search finder ingen Notion-tools i sessionen).
   UDESTÅENDE (genbekræftet 4× d. 19/7 — tool_search finder fortsat ingen
   Notion-tools): samlet status for 1.58.116→130 (durability-kæden
   T-010→T-015 + T-014, to analyse-drops lukket samme dag inkl. Gate A
   F-1202→F-1206, forensic pilot-slot, generalprøven af §1.6-kæden +
   logging-fixet i 130) — post den som det FØRSTE når connectoren er
   tilbage. Ét-tryks-artifact med den fulde tekst (→130) ligger hos
   Anders.**

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

## 9. Kø — hvem har bolden (16/7, opdateret 29/7)

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
dens base er `agent/unified-candidate-1.58.145` — **den frosne kandidat**.

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
3. **[ANDERS — kandidatkæden]** PR #161 `agent/unified-candidate-1.58.145`
   (head `8e40103`, 424 foran / 0 bagud main, alle 4 gates grønne på exact
   head, mergeable clean) er den rig-testede kandidat: preflight ✅, Agent 3
   fysisk ✅, model-eval 30/30+30/30, RAG ✅. **Udestår fysisk:** voice
   (Pixel fik `401 invalid token`) + scheduler-pilot. PR #162 (Stage A
   ét-klik, base=#161) fixer netop operatør-frictionen. Flow:
   `START_STAGE_A_TEST.cmd` → `START_REMAINING_PHYSICAL_TESTS.cmd` → review
   → SEPARAT eksplicit beslutning → ff-merge + tag v1.58.145. **Merges
   ALDRIG autonomt** — PR'en forbyder det selv. De fleste andre åbne PRs
   stacker mod denne kæde; merge dem ikke enkeltvis udenom. PR #1/#3 er
   lukkede (agent3 kom ind via mount, 1.58.131–135).

   **PROMOVERING — main er rykket (24/7, selvforskyldt):** main bar
   `2e2a29a` da kandidaten blev frosset; den er nu `95c1014`+ (rene
   docs-commits på HANDOFF.md, ingen kode). `--ff-only` er derfor IKKE
   længere mulig. **Det rammer ikke rig-kørslen** — `freeze_check`
   sammenligner checkout'ens egen HEAD mod tag-SHA'en (linje 273-274), så
   en clean checkout af `8e40103` fryser grønt uanset hvor main står.
   **Ren løsning: sæt tagget `v1.58.145` direkte på `8e40103`** (build-and-
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
