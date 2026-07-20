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

---

## 9. Kø — hvem har bolden (16/7)

**Ingen af disse er blokeret på kode. De er blokeret på rig, telefon,
branch-ejer eller en beslutning.**

1. **[ANDERS — PORTEN]** Valideringsrunden: `VALIDATION-1.58.49.md` +
   `deploy\validate-rig.ps1` (mekaniske tjek → `logs\validate-rig-latest.md`)
   + RAG-kalibrering (RAG_DESIGN §5: 5 spørgsmål du kender svaret på + 3 du
   ikke gør). Flytter 0 benchmark-point direkte — **men alt over den er
   rabatteret uden hardwarebevis**, og Agent 3's egen evidence-gate kræver den.
2. **[ANDERS — device]** APK 182 (`kaliv-latest.apk`): D7–D10 (toggles synlige,
   overlever genstart, egress kun når TIL) · **E6–E9: klienten er nu STRENGERE
   — fejler noget højlydt, er det et fund, ikke en regression** · #2a trin 3–5
   kun via "test jeg" (to blinde forsøg fejlede før).
3. **[BRANCH-EJER]** Agent 3 (PR #1): gate 1 = rebase til clean. Gate 2 ✅
   (linjegennemgang), gate 3 ✅ (CI på main). Merge som ÉN dormant enhed →
   rig-harness → developer preview → write-pilot. **Aldrig auto-produktion.**
   PR #3 kan lukkes: alt nyt derfra er portet til main (1.58.46).
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
7. **[GÆLD]** Notion-status for 1.58.44–52 er IKKE afleveret: connectoren
   forsvandt midt i sessionen (auth-fejl, dukker ikke op i tool-søgning).
   Post dem samlet når Anders re-autentificerer.
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
design-autoritet · Historiske (bannered): TESTGUIDE, PLAN_v1.13.0,
ALVA_VOICE_ROADMAP_DELTA, CLIENT_BUILD_AND_TEST, KRAVSPEC_V5 (leveret).
