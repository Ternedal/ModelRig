# ModelRig — STATUS (honest build report)

Version **0.20.18** — "kosmetiske testfund samlet: kilde-chip-dedup, ærligt ved-ikke-svar, hjælpsomme fejltekster". Follows 0.20.17 (V1 release-candidate — still pending Anders' on-device checklist) ("stable signing, conversation persistence, stop button, official icon"). Autonomous sessions, **2026-07-02 → 07-07**.

## V1 release-candidate checklist (read this first)
Server-side is fully verified (90 assertions, backend + worker, see below).
**Android compiles and builds to a real, signed APK here** (JDK 21 + Gradle 8.9 +
Android SDK 35 installed in the build environment) — it is not blind source
anymore. What's still open is **on-device confirmation** on Anders' actual
hardware, which I cannot do myself. Desktop is deliberately **out of scope for
V1** (see `ROADMAP.md` §3/§8 — audited and brought to parity in V2).

Tick through this on the phone, then `v1.0.0` gets tagged:

- [x] **Keyboard** ✅ **bekræftet on-device 7/7** (skrev i alle felter, layout OK) (0.15.2 combo): input stays just above the keyboard, top bar visible, no gap/overlap.
- [ ] **App icon** (0.16.1): real ModelRig mark shows on the launcher, not the Android robot.
- [x] **Signing** ✅ **bekræftet on-device 7/7** (APK installerede henover, ingen konflikt) (0.16.0): this and all future APKs install straight over each other — no more reinstalls.
- [x] **Conversation persistence** ✅ **bekræftet on-device 7/7** (samtaler overlevede APK-opdatering) (0.16.0): write a message, kill the app, reopen → conversation is still there; Samtaler-list opens/deletes correctly.
- [ ] **Stop button** (0.16.0): mid-stream, tap stop → generation halts immediately, reply marked "[afbrudt]".
- [x] **Cloud model dropdown** ✅ **brugt on-device 7/7** (Cloud-samtaler + cloud-svar) (0.15.x): "Genindlæs modeller" actually populates cloud models on Anders' Ollama Cloud account.
- [x] **RAG mode** ✅ **bekræftet on-device 7/7** (hele RAG-kæden, kilde-chips, min_score) (0.17.0): toggle works, source-filter dropdown lists ingested sources, replies show source chips.
- [x] **Error UX + retry** ✅ **bekræftet on-device 7/7** ("Failed to connect" ved ødelagt URL) (0.18.0): killing the rig mid-chat shows a readable Danish error with a working "↻ Prøv igen" button.
- [x] **Presets** ✅ **bekræftet af Anders on-device (0.20.4)** — inline-genbygningen virkede: chip gemmes og vises korrekt. (Historik: 0.19.8-original fejlede, 0.20.3-diagnosen holdt ikke, 0.20.4-genbygning med gennemprøvede komponenter løste det.)
- [x] **Model management** ✅ **bekræftet on-device 7/7** (installeret+VRAM vist, llama3.2:1b hentet med live %, slet virker) (0.20.0): the "Modeller" screen (⋮ menu) lists installed models with size, shows running models with VRAM, pulls a new model with live progress, deletes one with confirmation.
- [ ] **FØR ALT ANDET — par telefonen forfra**: serveren kører nu fra exe'erne med en FRISK datafil (`modelrig-data.json` i mappen exe'erne startes fra) — telefonens gamle token er dødt. Genstart serveren med `MODELRIG_HOST=0.0.0.0`, mint en kode (`-pair`), og par i appen. Uden dette fejler alle rig-punkter med 401.
- [x] **RAG-ingest** ✅ **bekræftet on-device 7/7** (2 chunks som forudberegnet; kanariefugl "blå-elefant-42" hentet med kilde) (0.20.2, was newest and least-tested — new file-picker API surface): from the RAG source dropdown, "+ Tilføj dokument" opens Android's file picker, picks a .txt/.md file, and it appears in the source list after ingesting.
- [x] **Samtale-oplevelse** ✅ **bekræftet on-device 7/7** (søg live, omdøb inline, del som markdown) (0.20.6): in Samtaler, type in the search field and confirm the list filters live; tap "✎" on a conversation, rename it inline, confirm it sticks; tap "Del" and confirm Android's share sheet opens with a readable markdown version of the conversation.
- [x] **Multi-rig-profiler** ✅ **bekræftet on-device 7/7** (gemt "Hjemme", ødelagt URL, chip genoprettede uden ny parring) (0.20.8, V3): once connected to the rig, tap "+ Gem denne rig" in the Rig card, name it, confirm a chip appears; disconnect/clear and confirm tapping the chip reconnects instantly without re-pairing.

If everything above is green: say so, and `v1.0.0` ships immediately (docs +
tag, no new code expected). If something's off: the exact symptom + which item,
and it gets fixed targeted rather than guessed at.

## Read this first
This repo was rebuilt from architecture after a sandbox reset wiped the earlier
verified code, then pushed toward V1. Structure and design are faithful, but this
was originally a *fresh* build — not byte-for-byte the earliest artifact. Since
then (0.11.0 onward) the full Android toolchain has been installed in the build
environment and every release has been an actually-compiled, signed, real APK —
not blind source. Everything below is labelled by how it was actually verified.

- backend + worker: compiled, run, and tested here (90 assertions).
- android: compiled and built to a signed APK here on every release since 0.11.0.
  On-device behavior (the checklist above) still needs Anders' hardware — that
  part genuinely can't be verified from the build environment.
- desktop: **not touched or audited in this V1 push** — out of scope until V2
  per `ROADMAP.md`. Treat it as unverified legacy source until then.

## What's new in 0.20.18  (kosmetiske fund fra Android-testrunden 7/7 — polish, ikke ny funktion)
- **Baggrund**: Anders gennemførte hele Android-tjeklisten on-device 7/7 —
  alle 4 nye features (RAG-ingest, Modeller, samtale-søg/omdøb/del,
  multi-rig) bestod. Tre kosmetiske svagheder blev observeret undervejs;
  denne release samler dem. Ikon-fixet mangler stadig (afventer Anders'
  billedfil) — det er DERFOR v1.0.0 endnu ikke er tagget: 12/13 grønne,
  ikonet er det sidste.
- **Kilde-chip-dedup (Android)**: en RAG-kilde delt i flere chunks gav én
  chip pr. chunk — "test" optrådte to gange (set on-device). `sources`
  køres nu gennem `.distinct()` før visning. Ren UI-ændring.
- **Ærligt "ved ikke"-svar ved nul RAG-matches (worker, begge klienter)**:
  når `min_score` filtrerede ALT væk, var `matches` tom → synthesize-blokken
  blev sprunget over → intet svar-felt → chat-laget faldt tilbage til
  kontekstfri chat. Det var derfor telefonen svarede "Hej!" på "hej" mens
  desktop (med kontekst) sagde "I don't know" — samme forespørgsel,
  divergerende adfærd. BEGGE RAG-stier (`/rag/query` OG streaming
  `/rag/chat`) returnerer nu et eksplicit, deterministisk ved-ikke-svar ved
  tomme matches — og streaming-stien springer Ollama-kaldet helt over
  (ærligt OG én færre round-trip). 2 nye tests beviser det: svar-feltet er
  ikke-tomt, og streamen indeholder INGEN error-linje (ville optræde hvis
  den forsøgte det døde Ollama). Suite: **110 assertions** (var 108).
- **Hjælpsomme fejltekster i model/ingest/pull-paneler (Android)**: de tre
  paneler viste rå strenge ("Fejl: models failed (401)"). Ny String-overload
  af `friendlyError()` router dem gennem samme statuskode-forklaringer som
  chat allerede brugte — 401 dér fortæller nu også "genpar enheden". (Bed
  Anders live 6/7: Modelstyring viste bar 401 indtil genindlæst; desktops
  tilsvarende fix kom i 0.20.16, dette er Android-pendanten.)
- **Ikke rørt**: al øvrig funktion. Desktop-KODE urørt (kun packageVersion-
  bump). Denne release bygger APK + server-exes (worker ændret) + Windows-jar.


## What's new in 0.20.17  (CI-only — platformliste skåret til virkeligheden)
- **Anders' beslutning 7/7: drop Linux- og macOS-desktop-builds.** Projektet
  kører på præcis to platforme — Windows (rig: jar + server-exes) og Android
  (telefon). Linux/macOS-jars var rene spild-artefakter, og macOS-runneren
  (10x-multiplier) var den suverænt største kvotepost målt over hele
  0.19/0.20-serien.
- **`desktop-build` er nu et enkelt Windows-job** (matrix-strategien fjernet
  helt) og kører KUN når desktop-kode faktisk er ændret, ved milepæle
  (patch=0), eller via workflow_dispatch — samme "komponent genbygges når
  dens kilde ændres"-politik som server-exe'erne. Windows-builden fungerer
  samtidig som CI-compile-check for desktop-koden (når koden er uændret, er
  der intet nyt at checke).
- **Ren-backend-patches bygger nu KUN Android-APK + kilde-zip** — den
  hidtil-obligatoriske Ubuntu-jar er også væk. Jar'en fra seneste
  desktop-ændring forbliver den aktuelle (komponent-versionspolitikken).
- **Denne release er selv testen af den slankeste sti**: rører kun
  `.github/` + docs → forventet: desktop-build SKIPPET, server-binaries
  SKIPPET, release udgiver alligevel (apk + zip). Kørslen verificeres
  efter tag-push, som altid. Android-koden er fortsat identisk med
  0.20.15/0.20.16 (kun versionstal) — telefontesten er gyldig på alle tre.


## What's new in 0.20.16  (UX-batch fra desktop-testaftenen 6/7 — desktop + docs, Android kode-identisk)
- **Baggrund**: Anders gennemførte 6/7 hele desktop-testrunden on-device
  (Windows, server-exe'erne). ALT bestod — og tre UX-svagheder blev
  observeret live undervejs. Denne release er præcis dén batch, bevidst
  holdt tilbage til testrunden var slut. **Android-koden er urørt**
  (versionName/Code bump only, badging = release-tag) — telefonens
  tjekliste-run sker på et stillestående artefakt; 0.20.15- og
  0.20.16-APK'en er kodeidentiske.
- **Selvforklarende fejltekster (desktop)**: `apiErrorHint()` dekorerer nu
  alle fem fejl-visningssteder (RAG-kilder, RAG-chat-boble, model-liste,
  Modelstyring-load, model-slet). 401 → "token mangler/ugyldigt + par-igen-
  opskrift"; 404 → "peger du på Ollama direkte? Backend kræver /api/v1/chat
  + token". Rå statuskode bevares først i beskeden (screenshots/logs viser
  stadig fakta). Begge tekster svarer 1:1 til de to fejl Anders faktisk
  ramte.
- **Modelstyring auto-genhenter** ved ændrede forbindelsesindstillinger:
  `LaunchedEffect` nøglet på (baseUrl, isBackend, bearer) i stedet for
  `Unit` — et token indsat EFTER panelet blev åbnet rydder nu selv den
  forældede 401 (bed Anders live 6/7). 400 ms debounce via LaunchedEffect-
  cancellation, da parametrene ændres pr. tastetryk under indtastning.
- **On-device-bekræftet 6/7 (Anders, Windows)** — hele desktop-fladen:
  soft-lock-fixet (0.20.13-layoutet, paneler + scroll + altid-nåbare
  toggles), samtale-browser (0.20.7), Modelstyring inkl. VRAM-visning
  (0.20.1), server-exe'erne + pairing-flow (0.20.15), RAG-kæden end-to-end
  (ingest → kilde-dropdown → svar med kilde-chip), OG **min_score live**
  (0.20.11): "hej" mod test-kilden gav ærligt "I don't know" uden kilder —
  tærsklen filtrerer som designet, nu bevist på rigtig hardware, ikke kun
  i deterministiske tests.
- **Komponent-versionspolitik gjort eksplicit** (fulgt siden 0.20.14's
  matrix-læk-lærdom): hver komponents versionsstreng = versionen af dens
  seneste ÆNDRING, ikke seneste release. Backend/worker står derfor bevidst
  på 0.20.15 her (urørte) — det holder også server-exe-genbygningen
  skippet. **Denne release er første live-kørsel af server_bins=false-
  grenen** (release-jobbet skal udgive assets selvom server-binaries-jobbet
  er skippet — `if: !failure() && !cancelled()` var forberedt, aldrig kørt).
- Ingen backend/worker-kodeændring.

## What's new in 0.20.15  (server-exe'erne, anden ombæring — to CI-fejl fundet og rettet)
- **0.20.14's `server-binaries`-job fejlede på første kørsel** — releasen nåede
  aldrig at få exe'erne (og blev slettet; 0.20.15 er den reelle leverance).
  Rodårsag, bekræftet: `go.mod` ligger i `backend/`, ikke i repo-roden — CI-
  steppet byggede fra roden, hvor der intet Go-modul findes. Hver eneste
  lokale build i denne session har kørt `cd backend &&`; det manglede i det
  nye job. Rettet med `working-directory: backend`.
- **Selvforskyldt matrix-læk fundet på samme kørsel**: 0.20.12 gjorde
  `desktop/composeApp/build.gradle.kts` til en del af versionsbump-rutinen —
  hvilket betød at HVERT release nu "rørte desktop/" og stille gen-udløste
  den dyre fulde 3-OS-matrix (0.20.14 byggede alle tre OS'er uden grund).
  Desktop-tjekket ekskluderer nu netop dén fil; en reel desktop-ændring
  udover bumpet giver stadig fuld matrix.
- Denne kørsel er den dobbelte live-test: `server-binaries` skal være grøn
  på Windows-runneren (backend rører config.go → jobbet kører), og desktop
  skal være ubuntu-only (kun gradle-bumpet rørt → ekskluderet).
- Indholdsmæssigt identisk med 0.20.14 i øvrigt (run_worker.py,
  run-windows.ps1-exe-detektion, docs-hurtigvej).

## What's new in 0.20.14  (færdigbyggede server-exe'er — Anders' ønske under Windows-opsætning)
- **Baggrund**: Anders ramte den fulde toolchain-mur under rig-opsætning
  ("go build" kræver Go, worker kræver Python+pip) og bad om ét pakket
  artefakt. En .jar giver teknisk ikke mening (backend er Go, worker er
  Python — .jar er JVM-format; desktop-klienten ER allerede en jar), men
  behovet bag er legitimt: **kør uden toolchain**.
- **Leverancen**: to enkeltfils Windows-exe'er på releasen —
  `modelrig-server-windows-x64.exe` (native Go-build) og
  `modelrig-worker-windows-x64.exe` (PyInstaller onefile via ny
  `worker/run_worker.py`, som importerer app-OBJEKTET statisk så
  PyInstaller ser hele afhængighedsgrafen).
- **CI-røgtestet på ægte Windows før release**: nyt `server-binaries`-job
  (windows-latest) bygger begge, starter dem, poller `/healthz` (onefile-
  exe'er selv-udpakker ved første start — polling frem for gæt-sleep), og
  kræver at serverens rapporterede version matcher taggets præcist, før
  filerne når release-assets. Fejler smoke, fejler releasen.
- **Kvotebevidst**: jobbet kører kun når det taggede commit rører
  `backend/`, `worker/` eller `deploy/` (samme diff-tree-mekanik som
  desktop-reglen), samt på milepæle. Release-jobbet blokeres ikke af et
  legitimt skippet binaries-job (`!failure() && !cancelled()`).
- `deploy/run-windows.ps1` foretrækker nu automatisk en
  `modelrig-worker*.exe` i worker-mappen over python; ellers uændret
  fallback. `CLIENT_BUILD_AND_TEST.md` §1 fik hurtigvejen dokumenteret,
  inkl. standalone-kørsel helt uden repo.
- **Ærlig grænse**: exe'ernes healthz-røgtest beviser at de starter og
  svarer på ægte Windows — ikke den fulde RAG-runde mod en rigtig Ollama
  (findes ikke på runneren). `doctor --deep` hos Anders er stadig dommeren.
- Ingen funktionel kodeændring i backend/worker udover versionsbump.

## What's new in 0.20.13  (desktop-soft-lock rettet — fundet af Anders på Windows)
- **Første rigtige desktop-on-device-fund**: Anders kørte v0.20.9-jaren på
  Windows og kunne "ikke komme længere" — indstillingskortet fyldte hele
  vinduet, og **knappen til at lukke det lå i layoutet UNDER kortet**, uden
  nogen scroll. Kortet er vokset gennem sessionen (presets 0.19.9, inline-
  gem-felt 0.20.5) og oversteg standardvinduets 720dp → alt nedenunder,
  inkl. luk-knappen og chat-inputtet, var uden for skærmen. En ægte
  soft-lock. **Denne fejlklasse (layout-overflow) kan headless smoke-tests
  aldrig fange** — præcis derfor on-device-test er gaten.
- **Fix, strukturelt**: (1) panel-toggle-knapperne (Indstillinger / Samtaler
  / Modelstyring) er samlet i én række ØVERST — altid nåbare uanset panel-
  højde. (2) Panelerne bor nu i en **scrollbar zone** der bytter plads med
  chat-listen (præcis ét weighted barn ad gangen — `verticalScroll` omslutter
  aldrig `LazyColumn`, så ingen nested-scroll-konflikt). Input-feltet er
  altid synligt i bunden. (3) Standardvindue hævet 980x720 → 1000x820.
- **CI-reglen lærte af det**: patch-releases byggede kun Ubuntu (0.20.10's
  besparelse) — men et patch der ÆNDRER desktop-kode er præcis undtagelsen.
  `determine-matrix` tjekker nu om det taggede commit rører `desktop/` og
  kører i så fald fuld 3-OS-matrix. **Dette release er selve testen** af den
  nye regel (det rører desktop → Windows/macOS-jars skal dukke op, korrekt
  navngivet 0.20.13).
- **Ærlig grænse**: layout-fixet er compile-verificeret + strukturelt
  ræsonneret, ikke renderet her (ingen skærm). Bruger kun mønstre der
  allerede kører (verticalScroll = Androids SetupScreen-mønster, samme
  Compose Foundation-kode). Anders' næste Windows-kørsel er den reelle test.
- Ingen backend/Android-kodeændring udover versionsbump.

## What's new in 0.20.12  (slut-audit — sidste omgang oprydning, ingen ny feature)
- **Desktop-jar-navnene fortæller nu sandheden**: alle CI-byggede jars har
  heddet `...-1.0.0.jar` uanset faktisk version (hardkodet Compose
  `packageVersion`). Rodårsag fundet **empirisk**, ikke antaget: Dmg-formatets
  konfigurations-tids-validering afviser enhver 0.x-version og fældede hele
  builden — men Dmg/Msi var template-rester der aldrig bygges (kun uber-jars).
  Fjernet dem; Deb accepterer 0.x. Verificeret lokalt:
  `ModelRig-linux-x64-0.20.12.jar`. **Bump-rutinen omfatter nu også
  `desktop/composeApp/build.gradle.kts`.**
- **`DRIFT.md` fik en API-oversigt** (fandtes ikke — endpoints var kun spredt
  i changelogs). Skrevet fra hukommelsen først, derefter **verificeret mod
  `server.go`s faktiske route-registrering — hvilket fangede 5 manglende
  endpoints** (pair/start, status, devices, devices-revoke, token/rotate) i
  første udkast. Inkluderer `min_score`-dokumentation (0.20.11).
- **`CLIENT_BUILD_AND_TEST.md` bragt fra 0.19.0-æra til nu**: røgtest-trin
  9–13 tilføjet (presets, model-administration, RAG-ingest,
  samtale-oplevelse, multi-rig-profiler); forældede påstande rettet
  ("desktop uverificeret" → bygges af CI på 3 OS'er; "90 assertions" → 108;
  gaten peger nu på STATUS.md som autoritativ tjekliste).
- **Småting**: forældet sessions-dato i denne fils header rettet
  (02/03 → 02→05); `*.db` føjet til `.gitignore` (blev slettet manuelt før
  hvert commit); `go vet` kørt rent.
- **TODO-audit**: grep for TODO/FIXME/XXX i hele kodebasen — kun falske
  positiver (parringskode-formatet "XXXX-XXXX"). Reelt nul åbne TODOs.
- Fuld regression: **108/108 grønne**. Ingen funktionel kodeændring.

## What's new in 0.20.11  (backend/worker only — RAG-kvalitet, roadmap §7 pkt.5)
- **Baggrund**: roadmappens egen risikoliste sagde det ligeud: "RAG-kvalitet:
  chunking/embedding virker men er ikke tunet." Eneste reelle, substantielle
  tekniske gæld tilbage der ikke kræver telefonen — backend/worker-only.
- **Reel bug rettet, ikke tal-gætteri**: `rag.query()` returnerede altid
  `top_k` matches uanset relevans-score — selv et helt urelateret spørgsmål
  fik `top_k` chunks tvunget ind som "kontekst", hvilket kan få modellen til
  at svare ud fra støj i stedet for korrekt at sige "det ved jeg ikke". Ny
  `min_score`-parameter (default 0.3, eksplicit dokumenteret som et
  fornuftigt udgangspunkt — **ikke** empirisk tunet mod Anders' egne
  dokumenter/forespørgsler) filtrerer nu FØR `top_k`-afskæringen.
- **Chunking forbedret, verificerbart**: `chunk_text()` foretrækker nu
  sætningsafslutning (". ", "? ", "! ", linjeskift) frem for blot mellemrum
  som brudpunkt, når et findes inden for overlap-vinduet — holder chunks
  semantisk mere hele. Falder korrekt tilbage til mellemrum når ingen
  sætningsgrænse findes.
- **9 nye permanente tests, alle grønne**: 6 i `worker_unit.py`
  (sætningsgrænse-brud verificeret med et konkret eksempel, fallback til
  mellemrum bekræftet stadig virker), 3 i `worker_rag.py` (min_score=0.3
  filtrerer en kendt nul-similaritets-match fra; samme forespørgsel med
  min_score=0.0 beviser at det var tærsklen og ikke en anden fejl). Ingen
  regression i e2e/backend_v1 (kørt eksplicit for at udelukke det).
  **Total: 108 assertions** (var 99).
- **Ærlig grænse**: 0.3 er en fornuftig start-værdi for `nomic-embed-text`,
  ikke empirisk valideret mod Anders' faktiske dokumenter. Justerbar via
  API'et uden kodeændring, hvis reel brug viser en bedre værdi.
- Ingen Android/desktop-kodeændring — kun backend/worker.

## What's new in 0.20.10  (CI-besparelse — macOS/Windows kun ved milepæle)
- **Baggrund**: beregnede det faktiske forbrug af GitHub Actions-minutter fra
  ægte job-tider (ikke gæt): ~446 af 2000 gratis minutter/måned brugt over
  denne sessions 15 kørsler. macOS-runnere koster 10x multiplier, Windows 2x
  — kun 23 faktiske macOS-minutter kostede 229 minutter af kvoten, mere end
  Ubuntu og Windows tilsammen.
- **Fix**: ny `determine-matrix`-job beregner om et tag er en "milepæl"
  (patch-version = 0, fx `v0.20.0`, `v1.0.0`) eller en almindelig
  patch-release (`v0.20.10` osv.). Milepæle bygger stadig alle tre OS'er;
  patch-releases bygger kun Ubuntu (server-tests, Android-APK,
  Linux-desktop-jar). Windows/macOS-jars udelades kun fra release-assets på
  patch-releases — ikke fra selve builden ved milepæle.
- **Manuel override**: `workflow_dispatch` tilføjet med et
  `force_full_matrix`-flag, hvis en patch-release specifikt rører
  desktop-kode og bør fuld-testes alligevel. **Ærligt forbehold**: dette er
  ikke selv testet — hvis det dispatches fra en branch uden et tag, kan
  release-jobbet fejle (ingen tag at hænge assets på). Mindre risiko, da det
  ikke er hovedstien.
- **Denne release ER selve testen**: v0.20.10 er bevidst en patch (ikke en
  milepæl), så CI-kørslen for denne tag bekræfter reelt at kun Ubuntu bygges
  — ikke bare antaget.
- Ingen Android/desktop-kodeændring. Kun `.github/workflows/build-and-release.yml`.

## What's new in 0.20.9  (proaktiv audit — ingen ny feature, kun risikoreduktion)
- **Baggrund**: i stedet for at stable endnu et ubekræftet V3-punkt oveni de
  allerede ventende (RAG-ingest, 0.20.6, 0.20.8), blev denne omgang brugt på
  at auditere RAG-ingest (0.20.2) — den feature med mindst indblik (bygget i
  et hul i denne sessions kontekst) — specifikt for samme bug-klasse som
  ramte presets (hardkodet UI-tilstand der ikke afspejler faktisk logik).
- **Betryggende fund**: RAG-ingests trigger ("+ Tilføj dokument" i
  kilde-dropdownen) bruger `ModelChip`+`DropdownMenu` — **strukturelt
  identisk** med det allerede bekræftede model-dropdown-mønster
  ("Genindlæs modeller"), ikke det `AlertDialog`-mønster der fejlede.
  Netværkskontrakten (`ingestText()` → workerens `/rag/ingest`) blev
  krydstjekket felt-for-felt mod workerens faktiske Pydantic-model
  (`IngestDoc`, `IngestReq`) — matcher præcist.
- **Reelt fund, rettet**: "+ Tilføj dokument"-menupunktet manglede
  `enabled = !ingesting`-spærring — et andet tryk mens en ingest allerede
  kører kunne udløse et konkurrerende, overlappende forsøg. Rettet
  defensivt (samme "farve følger faktisk tilstand"-princip som
  preset-fixet: grå+"Ingesterer…" mens aktiv, i stedet for at forblive
  altid-blå).
- **Selv-tjek af egen nyere kode**: grep'et 0.20.6/0.20.8's kode for samme
  hardkodet-farve-vs-enabled-mønster — ingen fund, begge er allerede
  konsekvente.
- **Ærlig grænse, uændret af denne audit**: selve fil-læsningen
  (`ContentResolver`/`openInputStream`) er stadig kun compile-verificeret,
  ikke on-device-testet — det kan kodegennemgang ikke afgøre.
- Kompilerer rent. Ingen backend-kodeændring udover versionsbump.

## What's new in 0.20.8  (roadmap V3 — multi-rig-profiler, Android, første V3-punkt)
- **Første V3-punkt bygget, bevidst valgt for lavest risiko**: af V3-listen
  (share-target, voice, vision, baggrunds-generering, multi-rig, widget,
  biometrisk lås, agent-tools) kræver denne **ingen ny Android OS-API**
  overhovedet — modsat de øvrige (fil/foto-vælger, mikrofon, intent-filters,
  App Widget, BiometricPrompt), som alle ville lægge endnu en ubekræftet
  UI-flade oven på de to der allerede afventer bekræftelse (RAG-ingest,
  0.20.6-søgning/omdøb/del).
- **Navngivne rig-forbindelser** ("Hjemme", "Arbejde", osv.) med
  hurtigskift: chip-række øverst i Rig-kortet, samme bekræftede inline-
  mønster som presets (0.20.4/0.20.5) — ingen `AlertDialog`.
  "+ Gem denne rig" gemmer **server-URL + det allerede opnåede token**
  (IKKE parringskoden — den er engangsbrug og aldrig gemt); kun aktiv når
  man reelt er forbundet. Tryk på en chip sætter URL+token direkte og
  markerer forbundet, uden ny parring.
- Ny `rig_profile`-tabel, skema-version 2→3 (efter preset-tabellens 1→2).
  SQL + hele migrationskæden (v1→v2→v3, bekræfter at ældre
  samtale/preset-data overlever begge trin) verificeret mod ægte SQLite.
- **Ikke on-device-testet endnu**.
- Desktop mangler samme feature — bevidst ikke rørt endnu (samme
  forsigtighed som alt andet UI-arbejde denne session: vent på
  bekræftelse først).
- Ingen backend-kodeændring udover versionsbump.

## What's new in 0.20.7  (desktop: samtale-browser — lukker desktops sidste separate gap)
- **Desktop havde ingen samtale-browser overhovedet** — kun stille
  genindlæsning af seneste samtale ved opstart (siden 0.19.3). Ny
  "Samtaler"-panel (toggle-knap ved siden af indstillinger): liste over alle
  samtaler med kilde + tidsstempel, tryk for at åbne, "+ Ny" for en frisk
  samtale, "Slet" pr. samtale.
- **Bevidst afgrænset scope**: kun liste/åbn/ny/slet — Android's *oprindelige*
  0.16.0-funktionssæt, ikke det nyere 0.20.6 (søgning/omdøb/del), som endnu
  ikke er on-device-bekræftet. At kopiere et ubekræftet UI-mønster til en
  anden klient var præcis fejlen i preset-sagaen (0.19.8→0.20.4) — undgås
  bevidst her.
- Genbruger udelukkende allerede kørte-verificerede DB-metoder
  (`listConversations`, `loadMessages`, `newConversation`,
  `deleteConversation` — alle runtime-testet i 0.19.3's smoke-test). Ny kode
  er ren UI-wiring oveni, ingen ny databaselogik at verificere.
- Kompilerer rent. Ingen backend-kodeændring udover versionsbump.

## What's new in 0.20.6  (roadmap V2 pt.4 — samtale-oplevelse, Android)
- **Søgning**: felt i Samtaler-skærmens header filtrerer titler live, mens du
  skriver (client-side, ingen ny SQL-forespørgsel pr. tastetryk).
- **Omdøb**: "✎" pr. samtale folder titlen ud til et redigerbart felt inline
  — samme bekræftede mønster som preset-gem (0.20.4/0.20.5): ingen
  `AlertDialog`, "Gem" farvekodet efter faktisk enabled-state.
  `ChatDb.renameConversation()` tilføjet, SQL verificeret mod ægte SQLite.
- **Del/eksport**: "Del" pr. samtale bygger en markdown-gengivelse af hele
  samtalen (titel som H1, **Du:**/**Assistent:**-præfiks pr. besked) og
  åbner Androids indbyggede deling (`Intent.ACTION_SEND`, tekst — ingen
  fil, ingen `FileProvider`-kompleksitet). Kan sendes til hvad som helst:
  Notion, mail, Keep, etc.
- **Ikke on-device-testet endnu** — kompilerer rent, SQL verificeret, men
  UI-flowet (særligt "Del" — Android-deling er ny API-overflade i denne
  session) afventer din test.
- Desktop mangler samme feature (naturlig fortsættelse — bevidst ikke rørt
  denne gang, samme forsigtighed som presets: vent på bekræftelse først).
- Ingen backend-kodeændring udover versionsbump.

## What's new in 0.20.5  (preset-fixet bekræftet af Anders — mønster portet til desktop)
- **Anders bekræftede 0.20.4 on-device**: inline-gem-flowet virker — preset
  gemmes og chip vises (screenshot med chip "ny" + ✕). Preset-punktet i
  V1-tjeklisten er hermed afkrydset. Rodårsagen til at det oprindelige
  dialog-baserede flow fejlede forbliver uidentificeret (kan ikke
  reproduceres uden enheden) — men den fejlende komponentkombination er nu
  helt ude af kodebasen.
- **Mønstret portet til desktop** — bevidst FØRST efter bekræftelsen
  (0.20.4-beslutningen): samme inline-flow, TextButtons i stedet for
  clickable-Box'e, AlertDialog fjernet, samme synlige fejlhåndtering.
  Preset-databaselaget på desktop var allerede runtime-verificeret
  (0.19.9's smoke-test), så kun UI-mønsteret er nyt — og det er nu det
  on-device-bekræftede.
- Kompilerer rent. Ingen backend-kodeændring udover versionsbump.

## What's new in 0.20.4  (preset-gem genbygget — ærlig omgang: 0.20.3-diagnosen holdt ikke)
- **Anders gentestede 0.20.3: fejlen består** — "Gem" reagerer slet ikke.
  Det falsificerer 0.20.3's diagnose (deaktiveret knap uden visuelt signal):
  fejlen ligger tidligere i flowet, sandsynligvis ved at dialogen aldrig
  åbner, eller at den åbner usynligt.
- **Rodårsagen er IKKE endeligt identificeret** — det siges ligeud.
  Kodegennemgang kunne ikke afgøre den: chip-mønsteret (Surface+clickable)
  er identisk med ModelChip, som beviseligt virker på enheden (cloud-model-
  dropdownen); temaets colorScheme er korrekt; logikken er triviel. Uden at
  kunne køre UI'en kan fejlen ikke reproduceres herfra.
- **Strategiskift i stedet for tredje gæt**: hele gem-flowet er genbygget
  med udelukkende komponenter der beviseligt virker på Anders' enhed i denne
  app: `TextButton` (bruges i overflow-menu, "Genindlæs modeller", "Til chat
  →") og `OutlinedTextField` (bruges i alle setup-felter). `AlertDialog` er
  **helt fjernet** — gem-flowet er nu inline: tryk "+ Gem som preset" →
  navnefelt folder ud direkte under chipsene → skriv navn → "Gem" bliver blå
  → tryk → chip dukker op. Hvert trin giver synlig feedback, så et evt.
  fortsat fejlpunkt kan udpeges præcist.
- Preset-chipsene (anvend/slet) er også konverteret til TextButtons — de
  var aldrig blevet testet (gem virkede jo ikke), så samme forsigtighed.
- Desktop er bevidst IKKE ændret endnu — den venter på Anders' bekræftelse
  af at dette mønster virker, før det kopieres (modsat 0.19.8/0.19.9 hvor
  en bug blev kopieret til begge klienter).
- Kompilerer rent. Ingen backend-kodeændring udover versionsbump.

## What's new in 0.20.3  (bugfix: preset "Gem"-knap fandt af Anders' on-device-test)
- **Reelt bug-fund**: Anders rapporterede at "Gem"-knappen i preset-dialogen
  (introduceret 0.19.8) ikke reagerede. Kodegennemgang fandt årsagen: knappens
  tekst var hardkodet til Signal-blå **uanset** om den var aktiveret
  (`enabled = newName.isNotBlank()`) — så en deaktiveret knap (tomt navnefelt)
  så visuelt identisk ud med en aktiv knap. Trykkede man "Gem" før man havde
  skrevet et navn, skete der (korrekt) ingenting — men UI'en gav intet visuelt
  signal om hvorfor.
- **Fix**: knappens tekstfarve følger nu faktisk `enabled`-tilstanden (dæmpet
  grå når deaktiveret). Samme fix i både Android og desktop (samme bug var
  kopieret til begge i 0.19.8/0.19.9).
- **Defensiv fejlhåndtering tilføjet oveni** (ikke kun den fundne bug): gem/
  anvend/slet-preset-kald er nu wrappet i `runCatching`, og eventuelle fejl
  (fx en database-fejl) vises som synlig rød tekst i stedet for at fejle
  stille — så *enhver* fremtidig fejl i denne flow er synlig, ikke kun den
  specifikke jeg fandt.
- **Ikke on-device-bekræftet endnu** — afventer at Anders tester igen.
- Kompilerer rent på begge klienter. Ingen backend-kodeændring udover
  versionsbump.

## What's new in 0.20.2  (roadmap V2 pt.1 — RAG-ingest fra appen)
- **Filvælger i Android** (Storage Access Framework,
  `ActivityResultContracts.OpenDocument()`) tilgængelig fra RAG-kilde-
  dropdownen ("+ Tilføj dokument"). Læser filens tekst + filnavn, POST'er til
  `POST /api/v1/rag/ingest` via ny `ModelRigClient.ingestText()`. Status/fejl
  vises inline i top-baren; kildelisten genindlæses automatisk efter succes.
- **Ny API-overflade for denne session** (fil-vælger/ContentResolver) — ikke
  brugt tidligere, så lidt højere risiko end de foregående features.
- **Backend-kontrakten var allerede verificeret**, ikke gættet: `ingestText()`
  sender præcis den JSON-form (`{"documents":[{"text","source"}]}`) som
  `tests/worker_rag.py` og `tests/e2e.py` allerede tester end-to-end (direkte
  på worker'en og gennem backend-proxyen via CLI). Solidt fundament selvom
  selve Android-koden kun er compile-verificeret.
- **Kendt begrænsning** (uændret, ikke ny): kun txt/md-tekstindhold — ingen
  PDF/DOCX-udtræk, hverken på Android eller worker-siden.
- Kompilerer og bygger til signeret APK (samme nøgle). Ikke on-device-testet.
- Ingen backend-kodeændring udover versionsbump; alle 99 assertions fortsat
  grønne.

## What's new in 0.20.1  (model-administration på desktop — lukker parity-gap)
- **Samme feature som 0.20.0, nu på desktop**: nye metoder i `OllamaClient.kt`
  (`listModelsDetailed`, `listRunningModels`, `pullModel` med streaming
  progress, `deleteModel`), plus et "Modelstyring"-panel i UI'en (toggle-knap
  ved siden af RAG-tilstand).
- **Virker mod begge kilder** (lokal Ollama direkte eller via backend) —
  samme sti-udledningsmønster som `loadModels()` allerede brugte
  (`/api/v1/...` via backend, `/api/...` direkte mod Ollama).
- **Ægte runtime-verifikation** (samme metode som RAG-klientens smoke-test):
  midlertidig test der startede en rigtig lokal HTTP-server, bekræftede
  detaljeret model-liste (med størrelse), kørende modeller (VRAM),
  streaming pull-progress (4 linjer, korrekt rækkefølge, request-body
  uændret), og DELETE-kald (metode + body korrekt). Testfil fjernet efter.
- Kompilerer rent (`BUILD SUCCESSFUL`).
- Ingen backend-kodeændring udover versionsbump.

## What's new in 0.20.0  (roadmap V2 pt.3 — model-administration)
- **Tre nye backend-endpoints**, alle bag samme bearer-auth som resten af
  API'et: `GET /api/v1/models/running` (Ollamas `/api/ps` — kørende modeller +
  VRAM), `POST /api/v1/models/pull` (Ollamas `/api/pull` — streamer download-
  fremgang som NDJSON), `DELETE /api/v1/models/delete` (Ollamas
  `/api/delete`). Genbruger den eksisterende, generiske `proxy.Forward()` —
  ingen ny proxy-logik, samme mønster som chat/RAG.
- **Ollamas faktiske API-kontrakt verificeret** (ikke gættet) før
  implementering: feltnavnet er `model` (ikke det ældre `name`) i
  pull/delete-body, og `/api/ps`-svarets `size_vram`/`expires_at`-felter er
  bekræftet mod officiel dokumentation.
- **Permanent regressionstest tilføjet** (`tests/backend_v1.py`, ikke en
  engangs-smoke-test): udvidede den falske Ollama-server med `/api/ps`,
  streaming `/api/pull`, `/api/delete`. 9 nye assertions — bekræfter
  NDJSON-progress-rækkefølge, at request-body videresendes uændret, og at
  auth håndhæves på alle tre nye endpoints. **Total: 99 assertions, alle
  grønne** (var 90).
- **Ny "Modeller"-skærm i Android** (tilgængelig fra ⋮-menuen, kræver rig):
  installerede modeller med størrelse + slet-knap (med bekræftelses-dialog,
  da sletning er irreversibel), kørende modeller med VRAM-forbrug, og et felt
  til at hente en ny model med **levende download-fremgang** (status + %).
- **Verificeret**: backend-endpoints er runtime-testet mod en fake Ollama-
  server (ikke bare compile-verificeret). Android-appen kompilerer og bygger
  til en signeret APK (samme nøgle — installerer oven på). UI'en er ikke
  on-device-testet endnu.
- Desktop mangler samme feature (naturlig fortsættelse, ligesom presets var).

## What's new in 0.19.9  (presets/personaer på desktop — lukker parity-gap)
## What's new in 0.19.9  (presets/personaer på desktop — lukker parity-gap)
- **Samme feature som 0.19.8, nu på desktop**: preset-tabel i
  `DesktopChatDb.kt` (plain JDBC, samme skema som Android), chips under
  system-instruktion-felterne i `SettingsCard` for både lokal og cloud.
  Tryk for at anvende, "✕" for at slette, "+ Gem som preset" for at gemme
  den aktuelle tekst.
- **Ægte runtime-verifikation** (samme metode som 0.19.3/0.19.4): midlertidig
  smoke-test kørt via `gradle run` mod en rigtig SQLite-fil — gemte 3
  presets, bekræftede kilde-filtrering, sletning, og at eksisterende
  samtale/besked-funktionalitet ikke er brudt (regressionstjek). Testfil
  fjernet efter verifikation.
- Kompilerer rent (`BUILD SUCCESSFUL`).
- Ingen backend-kodeændring udover versionsbump.

## What's new in 0.19.8  (roadmap V2 pt.2 — presets/personaer, kørt tidligt)
- **Gemte system-prompt-presets pr. kilde** (Android): ny `preset`-tabel i
  `ChatDb.kt` (skema-version 1→2, med korrekt migration — eksisterende
  samtaler/beskeder rører den ikke). Chips under system-instruktion-feltet i
  både Rig- og Cloud-kortet på setup-skærmen: tryk for at anvende, "✕" for at
  slette, "+ Gem som preset" for at navngive og gemme den aktuelle tekst.
  Presets er scoped pr. kilde (en rig-persona roder ikke i cloud-listen).
- **Verificeret**: appen kompilerer og bygger til en signeret APK (samme
  nøgle som 0.16.x — installerer oven på uden afinstallation). SQL-skemaet og
  migrationsvejen (v1→v2, inkl. at gamle samtaler/beskeder overlever) er
  kørt mod ægte SQLite via et Python-script med de nøjagtige SQL-strenge fra
  `ChatDb.kt` — men det tester kun selve SQL'en, ikke Androids
  ContentValues/Cursor-lag omkring den (kræver Robolectric eller en enhed,
  ingen af delene er til rådighed her).
- **Ikke on-device-testet endnu**: dette er V2-arbejde kørt tidligt (ligesom
  desktop-løftet og CI), uafhængigt af den ventende V1-tjekliste. Tilføj det
  til en fremtidig test-runde.
- Ingen backend-kodeændring udover versionsbump.

## What's new in 0.19.7  (CI-fix #2: desktop-jar artifact path — found via artifacts API, not step status)
- v0.19.6 ran green on every job, but only delivered 1 of 4 expected release
  assets (the APK; no desktop jars). Caught by checking the actual
  `GET .../actions/runs/{id}/artifacts` endpoint rather than trusting green
  step icons: "Found 1 artifact(s)" at download time, "No files were found"
  in every desktop-build matrix job's upload step.
- **Root cause**: "Locate the packaged jar" ran with `working-directory:
  desktop` and recorded a path relative to that directory
  (`composeApp/build/...`). The following `upload-artifact` step runs from the
  repo root instead, so the recorded path was missing the `desktop/` prefix
  and matched nothing. `upload-artifact` doesn't hard-fail on an empty match
  (just a warning), so the job still showed `conclusion: success` despite
  uploading nothing real.
- **Fix**: the recorded path now includes the `desktop/` prefix.
- **Re-verified properly this time**: checked both the artifacts API and the
  actual release asset list, not just job status. All 5 assets present:
  `modelrig-v0.19.7.apk`, `modelrig-v0.19.7.zip`,
  `ModelRig-linux-x64-1.0.0.jar`, `ModelRig-windows-x64-1.0.0.jar`,
  `ModelRig-macos-arm64-1.0.0.jar` — the last two built natively on real
  Windows/macOS GitHub-hosted runners. **CI pipeline now genuinely works
  end-to-end.** Lesson kept in mind going forward: a green job conclusion only
  means no step errored, not that it produced the expected output.
- No backend/worker/Android source changed beyond the workflow file itself.

## What's new in 0.19.6  (CI-fix #1: zip-step case-sensitivity)
- v0.19.5's workflow run revealed a real bug, caught by actually tagging and
  observing the run rather than assuming it worked: `server-tests`,
  `android-build`, and all three `desktop-build` matrix jobs
  (ubuntu/windows/macos) succeeded, but `release` failed at the zip step:
  `zip warning: name not matched: modelrig` / `zip error: Nothing to do!`.
- **Root cause**: GitHub Actions checks out into a directory named after the
  exact repo name (`ModelRig`, capital R) — the workflow incorrectly assumed
  the local sandbox's lowercase convention (`modelrig`).
- **Fix**: resolve the checkout directory name dynamically via
  `basename "$GITHUB_WORKSPACE"` instead of hardcoding either case.
- v0.19.5 is left as-is on GitHub — an honest record of the run that found the
  bug, not deleted/hidden.

## What's new in 0.19.5  (CI via GitHub Actions — first live test, found a bug)
- Added `.github/workflows/build-and-release.yml`: on tag push (`v*`), runs
  the full 90-assertion server suite, builds the Android debug APK, builds
  genuinely OS-native desktop jars on real Windows/macOS/Linux runners (fixes
  the caveat from 0.19.1 — a jar built in the Linux sandbox can't run on
  Windows, but a Windows-hosted runner can build a real Windows-native one),
  and publishes everything to the release automatically.
- Verified the external actions used (`android-actions/setup-android@v4`,
  `softprops/action-gh-release@v2`) were current before writing them into the
  workflow, rather than guessing versions. YAML syntax validated with a
  parser before committing.
- **First push was rejected**: the fine-grained PAT lacked the `workflow`
  scope needed to add/modify files under `.github/workflows/`. Anders granted
  it; push succeeded on retry.
- **First real run found a genuine bug** (see 0.19.6) — the point of actually
  triggering and checking a live run rather than assuming a workflow file is
  correct just because it's syntactically valid.
- No backend/worker/Android source changed beyond the workflow file itself.

## What's new in 0.19.4  (desktop-parity list complete: RAG mode)
- **RAG mode on desktop** (`net/RagClient.kt`): separate from `ChatRouter` —
  RAG only makes sense against the backend+worker, never local Ollama directly
  or Ollama Cloud. UI toggle + source-filter dropdown + source chips above
  replies, same pattern as Android. Same known simplification as Android:
  single-shot per question (the worker's `/rag/chat` takes one `query` string,
  not a message list).
- **Genuine runtime verification, not just compile**: temporarily pointed
  `mainClass` at a throwaway smoke test that spun up a real local HTTP server
  (JDK's built-in `com.sun.net.httpserver`), pointed `RagClient` at it, and
  confirmed NDJSON sources-header parsing, streaming content deltas, the
  Bearer auth header, and the source-filter request all work correctly. Test
  file removed after verification.
- **Desktop-parity list from `ROADMAP.md` §4 pt. 5 is now complete**: brand
  colors, Danish UI, system prompts, markdown, persistence, RAG all delivered
  and verified. Remaining, out of original scope: a conversation browser UI
  (list/switch/delete), like Android's Samtaler screen.
- No Android/backend code changed. No new APK (unchanged since 0.19.0).

## What's new in 0.19.3  (desktop: SQLite persistence, runtime-verified)
- **SQLite persistence** (`data/DesktopChatDb.kt`): plain JDBC
  (`org.xerial:sqlite-jdbc:3.49.1.0`, version verified against Maven Central),
  same `conversation`+`message` schema as Android's `ChatDb.kt`. DB file:
  `~/.modelrig/modelrig.db`. Latest conversation silently auto-resumes on
  startup; no conversation browser yet (list/switch/delete) — natural next
  increment.
- **New dependency justified**: plain JVM has no built-in SQLite (Android
  does). `sqlite-jdbc` is a single embedded driver — no server, no network —
  in keeping with the project's SQLite-first convention, not breaking it.
- **Genuine runtime verification**: temporarily pointed `mainClass` at a
  throwaway smoke test, ran it via `gradle run` against a real SQLite file,
  confirmed insert/read/latest-conversation/metadata/list/delete **and
  cascade-delete of messages** all correct. Test file removed after.
- No Android/backend code changed. No new APK (unchanged since 0.19.0).

## What's new in 0.19.2  (desktop: markdown rendering ported from Android)
- Ported Android's dependency-free Markdown renderer to desktop
  (`desktop/.../Markdown.kt`) — near-verbatim, since the original used no
  Android-specific APIs (pure Compose Foundation/Material3/UI-text, shared
  across Compose Multiplatform).
- `UiMessage` gained a `streaming` flag so the same plain-text-while-streaming
  / markdown-when-done pattern from Android applies here too.
- Compiles clean (`BUILD SUCCESSFUL`, verified here).
- No Android/backend code changed. No new APK (unchanged since 0.19.0).

## What's new in 0.19.1  (desktop lifted toward Android parity — V2 work, run early)
- **Brand.kt corrected**: replaced an old invented palette (never fixed here
  before) with the same verified brand colors as Android's `Theme.kt` —
  Sapphire `#306CFC`, Champagne `#DEC08A`.
- **Danish UI**: all visible strings translated (was English — didn't match
  the project's standing Danish-UI convention). Header badges RIG/CLOUD
  instead of LOCAL/CLOUD/IDLE.
- **Per-source system prompt** (local + cloud), prepended as `role:"system"`
  before send — same pattern as Android 0.13.0. Documented simplification:
  follows the *preferred* source, not necessarily whichever answers after a
  fallback.
- Confirmed the full build+package pipeline works here: `./gradlew build` and
  `packageUberJarForCurrentOS` both `BUILD SUCCESSFUL` — first real
  verification for desktop, not just written-to-compile source. **Honest
  caveat**: the packaged jar bundles Linux-native Skiko (this sandbox's OS)
  and will not run on Windows — not shipped as a download for that reason;
  the value is confirming the Kotlin/Compose Multiplatform version pairing
  actually compiles+packages.
- No Android/backend code changed. No new APK (unchanged since 0.19.0).

## What's new in 0.19.0  (roadmap milestone 0.19 — "V1-hærdning")
- **Fixed a genuinely stale claim** in this file ("no Kotlin/Gradle/Android
  SDK in the environment") — the full Android toolchain has been installed
  and every release since 0.11.0 has been an actually-compiled, signed APK,
  not blind source. Corrected.
- Added the **V1 release-candidate checklist** above (8 items) — consolidates
  0.16–0.18's on-device-pending items into one place instead of scattered
  across separate release notes.
- `CLIENT_BUILD_AND_TEST.md`: added RAG-mode and error/retry smoke-test steps
  that were missing since those features shipped after the doc was last
  touched; corrected the 1.0-readiness gate to reflect desktop being deferred
  to V2.
- `ROADMAP.md`: resolved 2 of 5 open questions (desktop→V2, keystore→private
  repo — both settled by Anders saying "kør efter roadmap" with no objection
  since); refreshed the stale "next steps" section.
- **Full regression: all 90 assertions green** (smoke 11, v1 17, worker_unit
  9, worker_rag 25, e2e 28). No Android source changed; version bump only.
  Deliberately tagged `v0.19.0`, **not** `v1.0.0` — that tag is withheld until
  Anders confirms the on-device checklist himself.

## What's new in 0.18.0  (roadmap milestone 0.18 — "Fejl-UX og drift")
- **Human error messages** (`friendlyError()`): network unreachable, timeout, 401
  (stale pairing), 404 (unknown model/endpoint), 502/503 (Ollama down), missing
  cloud key, and RAG-specific errors each get a short, actionable Danish message
  instead of a raw exception string.
- **"↻ Prøv igen" (retry) button** on any failed reply. Retries the same user
  message in place — no duplicate user bubble, no duplicate DB row — using the
  mode/model/RAG settings active *at retry time* (documented; usually what you
  want since you just hit retry right after the failure).
- **DRIFT.md**: Tailscale setup (phone ↔ rig off-LAN), backup/restore of
  `modelrig-data.json` (pairing/tokens) and `modelrig-rag.db` (RAG index) with
  copy-paste commands, full-reinstall guide for Android, and a quick health-check
  cheatsheet. Also spells out what's *not* backed up (Android's local
  conversation history + cloud key live only on-device).
- Same signing key as 0.16.x/0.17.0 — installs straight over 0.17.0, no reinstall.

## What's new in 0.17.0  (roadmap milestone 0.17 — "RAG i lommen")
- **RAG mode in the app** (rig only — RAG runs against the worker, not cloud). A
  toggle in the top bar switches the chat between plain chat and RAG; RAG mode
  calls the backend's streaming `/api/v1/rag/chat` (retrieval, then a streamed
  answer). The first NDJSON line's sources are shown as small chips above the
  reply — the whole point of RAG is knowing what it's citing.
- **Source filter**: a dropdown (populated from `/api/v1/rag/sources`) narrows
  retrieval to one ingested source, or "Alle kilder" (all).
- **History trimming** (both rig and cloud, non-RAG chat): sends the system
  prompt + last 20 messages, further trimmed to a ~24,000-character budget from
  the front. Without this, a long conversation resent its *entire* text on every
  turn — slow, and wasteful against cloud quota.
- **Known limitation, by design of the existing worker endpoint**: RAG mode is
  single-shot per question (query in, sources + answer out) — it does not feed
  prior conversation turns into the model as context. The transcript still
  displays and persists locally; the model just doesn't see earlier turns while
  in RAG mode. This isn't a new restriction I introduced — the worker's
  `/rag/chat` was already built this way (`QueryReq.query` is one string, not a
  message list); the app now simply exposes it. Multi-turn RAG (folding recent
  turns into the retrieval query) is a reasonable V2 follow-up if it turns out
  to matter in practice.
- Same signing key as 0.16.x — installs straight over 0.16.1, no reinstall.

## What's new in 0.16.1
- **Icon background now sampled from Anders' own delivered asset**
  (`modelrig_app_icon_final.png`), not an invented gradient — averaged the inner
  background corners (excluding one sample that caught the gold border bevel):
  `#0F1422` → `#020713`. Foreground (the symbol) was already his real artwork
  since 0.16.0. Same signing key — installs straight over 0.16.0, no reinstall.

## What's new in 0.16.0  (roadmap milestone 0.16 — "Fundament der ikke smuldrer")
**⚠️ ONE-TIME REINSTALL REQUIRED:** this release switches from the session-local
debug signature to a **stable release keystore** (committed under
`android/signing/`, password in keystore.properties — keep a backup copy in
Notion Secrets). Android refuses to update across a signature change, so
**uninstall the old app once**, then install this APK. Cloud key + system
prompts must be re-entered once. Every future APK installs over the top, from
any session or machine.

- **Stable signing** (both debug and release build types use the repo keystore).
  Cert: CN=ModelRig, SHA-256 `6563 92B0 3A32 1501 …` — verified with apksigner.
  Ships as a **release** build from now on (`versionCode 16`, `versionName 0.16.0`).
- **Conversation persistence** (`data/ChatDb.kt`, Android built-in SQLite, no new
  dependency): conversations + messages survive app kill and phone restart; the
  latest conversation reopens on launch; a **Samtaler** screen lists all
  (open / new / delete). Assistant replies are written once on completion — an
  in-flight reply is lost on a crash (accepted V1 tradeoff).
- **Stop button**: the send button becomes a stop square while streaming;
  cancels the underlying OkHttp call (<1 s), keeps the partial text with an
  "[afbrudt]" marker, and persists the partial.
- **Error hygiene**: failed replies are shown in red but are **never persisted
  and never sent back to the model as history** (previously an error bubble
  leaked into the next request's context).
- **Official app icon**: foreground extracted from the approved
  `modelrig_app_icon_final.png` export (755 px source — sharp), background
  gradient sampled from the same icon. Exports preserved under `/brand/`.

**Verified here:** compiles; signed release APK; signature fingerprint matches
keystore; versionCode/Name correct; server suite smoke green (11/11) after the
version bump.
**Needs on-device:** persistence round-trip, conversation list UX, stop button,
icon on the launcher, and the still-open 0.15.2 keyboard check.

## What's new in 0.15.5
- **Icon now uses the REAL brand mark**, not a hand-drawn approximation. The
  designer's actual symbol (an M-truss whose diagonals **cross** in the centre with
  a stem to a bottom node) was extracted straight from the brand PNG by keying out
  everything except the sapphire+champagne artwork, then placed on the obsidian
  background. Shape verified before shipping.
- Caveat: the source art in the handoff is modest resolution, so the extracted mark
  is a little soft; for pixel-perfect crispness, export the symbol as SVG from the
  source file and drop it in as `ic_launcher_foreground`.

## What's new in 0.15.4
- **Icon refined to match the real brand mark.** The 0.15.3 icon was a simplified
  M. Looked closely at the designer's actual symbol and reproduced it faithfully:
  an M-truss with a central sapphire **hub**, a **stem** down to a **champagne**
  node at bottom-centre, and a **champagne** node top-left (sapphire elsewhere).
  Still a geometric interpretation, not a pixel-trace of the source art.

## What's new in 0.15.3
- **Real app icon.** The app had no `android:icon`, so it showed the default
  Android robot. Added a proper **adaptive icon** (vector, crisp at every size):
  the ModelRig **"M" drawn as a node-graph** — one continuous sapphire stroke
  through four corner nodes with a **champagne accent node** in the centre, on an
  obsidian gradient. Matches the brand mark direction. Wired via
  `android:icon`/`android:roundIcon`. (A PNG preview ships with this release.)

## What's new in 0.15.2
- **Keyboard/inset, take 2 (correct this time).** Pinned down from two on-device
  data points: with no `softInputMode` the window *resized* (so ime-padding
  double-lifted the input); with `adjustResize` the window does *not* resize (so
  removing the padding hid the input behind the keyboard). The correct, documented
  edge-to-edge combo is **`adjustResize` (window doesn't resize) + `imePadding`**
  (lifts the input by the keyboard height). Both are now in place.

## What's new in 0.15.1
- **Fix: input field jumped to the top when the keyboard opened.** Classic
  edge-to-edge double-inset — the window already resizes for the keyboard, so the
  extra `ime` padding on the input bar pushed it up by the keyboard height. The
  input now uses only the navigation-bar inset, and the activity declares
  `windowSoftInputMode="adjustResize"` so the resize behaviour is deterministic.
  On-device check: keyboard-up should keep the input just above the keyboard.

## What's new in 0.15.0
- **Real brand applied** (Android). The theme now uses the **ModelRig brand
  handoff v3** palette (now committed under `/brand/` so it can't be lost again),
  sampled from the brand board: sapphire `#306CFC`, champagne `#DEC08A`, obsidian/
  graphite base, cloud-white text. Earlier builds used an invented palette; this
  matches the brand direction (premium dark, sapphire actions, champagne accent).
  Source badge is now a champagne/sapphire pill; send is a clean sapphire arrow.
- **Cloud model dropdown**: `CloudClient.listModels()` (tries `/api/tags`, then
  `/v1/models`) populates a dropdown for cloud — same UX as the rig model picker.
  Manual model entry in settings remains as a fallback.
- Compile-verified + APK built.

## What's new in 0.14.0
- **Chat UX overhaul** (Android). Fixes the status-bar collision (targetSdk 35
  forces edge-to-edge; the app now calls `enableEdgeToEdge()` and applies status /
  ime / navigation-bar insets) and turns the chat into a real messaging layout:
  **right-aligned blue user bubbles, left-aligned surface assistant bubbles**
  (~82% max width, tail corner), a blinking streaming cursor, a circular send
  button (Canvas-drawn arrow, no icon dep), model chip + source badge + Skift in
  the top bar, and a centered empty state. Compile-verified + APK built; the
  layout/insets are the on-device check.

## What's new in 0.13.0
- **Per-source system instructions** (Android): rig and cloud each get an optional
  multiline system prompt (`TokenStore.rigSystem` / `cloudSystem`), sent as the
  first `role:"system"` message on every request for that source. Set on the setup
  screen (saves as you type). Compile-verified + APK built; runtime is the usual
  on-device check (the prompt is just prepended to the existing, working message
  flow, so low risk). 0.12.0's cloud path was confirmed working on-device.

## What's new in 0.12.0
The point: **use the phone with cloud when the rig is off.**
- **Android direct Ollama Cloud** (`net/CloudClient.kt`): streams from
  `https://ollama.com/api/chat` with your account key — no rig needed. Setup screen
  now offers **rig and/or cloud**; if both are set, chat has a Rig/Cloud toggle.
- **Cloud key encrypted at rest** via AndroidKeystore AES-256-GCM (`data/Crypto.kt`),
  no external dependency.
- **Backend can also use cloud** (bonus): `MODELRIG_OLLAMA_KEY` → the proxy sends
  `Authorization: Bearer` to Ollama, so pointing `MODELRIG_OLLAMA_URL` at
  `https://ollama.com` makes the whole rig cloud-backed.

**Verified here:**
- The Android app **compiles and builds to a real APK** (full toolchain: JDK 21,
  Gradle 8.9, Android SDK 35). Compile-clean.
- The backend cloud path: with `MODELRIG_OLLAMA_KEY` set, a fake cloud that
  requires the bearer header received `Authorization: Bearer …` and the chat
  streamed through. Existing suite still green (90 assertions unchanged; proxy
  auth is a no-op when no key).

**NOT verified (needs your device + a real key):**
- That the app *runs* the cloud path end to end (streaming from ollama.com).
- That the **Keystore encrypt/decrypt** round-trips on a device (least-tested code
  — it compiles, but crypto only runs on-device). Failure is caught, not crashy:
  a save error shows a message rather than killing the app.
- Actual cloud model names / availability on your account.

## What's new in 0.11.0
- **Android UI overhaul** (source only, **not compiled here** — like all the
  Kotlin). Material 3 dark theme with the shared brand palette; custom top bar
  (model dropdown + overflow: clear / unpair); chat bubbles with auto-scroll and a
  streaming spinner; multiline input; Danish UI strings.
- **Dependency-free Markdown renderer** (`android/ui/Markdown.kt`): headings,
  bold/italic, inline code, fenced **code blocks with a copy button**,
  bullet/numbered lists, blockquotes, rules, styled links. No tables / deep
  nesting / images (swap `MarkdownText` for a CommonMark lib if needed). Chosen
  over a library specifically because it compiles deterministically without a
  version/API to get wrong — which matters since it can't be built here.
- Streaming + markdown interact deliberately: **plain text while streaming**, then
  **markdown once complete** (no re-parse per token, no half-open code fences).
- No new dependencies; backend + worker unchanged (version const bumped to 0.11.0
  so `/healthz` matches the release tag). **This is the biggest single chunk of
  unverified code in the repo — its first real test is your local Android build.**

## What's new in 0.10.0
- **Streaming RAG chat** — `POST /rag/chat` (proxied at `/api/v1/rag/chat`,
  CLI: `rag-chat`) retrieves context and then **streams** the answer, instead of
  the blocking synthesis path. The first NDJSON line is `{"sources":[…]}` (what
  context was used); the rest are Ollama chat deltas. Retrieval failure returns a
  clean 502 before the stream starts; a chat failure mid-stream is surfaced as a
  final `{"error":…}` line. Verified: worker reassembles the streamed answer, and
  the whole chain streams through the backend to the CLI (`stream-ok`, sources on
  stderr).
- Tests: **90 assertions**.

## What's new in 0.9.0
- **Token rotation** — `POST /api/v1/token/rotate` (CLI: `rotate`) re-issues the
  calling device's token without re-pairing; the old token stops validating
  immediately. For when a token leaks. Verified: new token works, old → 401, same
  device id.
- **Deep health** — `GET /api/v1/health/deep` (CLI: `doctor --deep`) actively
  round-trips: it lists Ollama models *and* asks the worker to embed a token
  (which calls Ollama), reporting `ok` + per-check latency. Proves the models
  respond, not just that ports are open. Verified both paths: all-green, and a
  dead Ollama surfaced as `worker error: cannot reach Ollama at … All connection
  attempts failed` with exit 1.
- Tests: **86 assertions**.

## What's new in 0.8.0
- **Source-filtered RAG query** — `POST /rag/query` accepts `source` to restrict
  retrieval to one source (CLI: `rag-query --source X`). Filtered in SQL.
- **CLI `doctor`** — one command checks backend reachability, token validity, and
  Ollama + worker health (via `/api/v1/status`), then prints a verdict and a
  concrete fix per failure. Exit code reflects health (0 green, 1 problem).
- **Request IDs + structured logging** — every request gets an `X-Request-ID`
  (or reuses an incoming one), returned to the client, **forwarded to upstreams**,
  and logged as `level=info req=… ip=… method=… path=… status=… dur_ms=…`. The
  worker logs the same id, so one request traces across both services. Verified in
  the e2e: a custom id appears in both the backend and worker logs.
- Tests: **76 assertions**. Both `doctor` paths (all-green and upstreams-down) and
  cross-service tracing are covered.

## What landed in 0.7.0
- **RAG source management** — the RAG is now operable, not just write-and-query:
  - `GET /rag/sources` — sources with chunk counts + last-ingested time.
  - `GET /rag/stats` — corpus totals (distinct sources, total chunks).
  - `DELETE /rag/source?source=X` — remove every chunk for a source (404 if none).
  - All proxied through the backend (`/api/v1/rag/*`) and exposed in the CLI
    (`rag-sources`, `rag-stats`, `rag-delete --source`).
- **Proxy now forwards query strings** to upstream (needed for the DELETE above);
  general fix, benefits any query-param endpoint.
- Tests grew to **69 assertions**; the e2e now ingests two sources, lists, deletes
  one, and confirms it's gone — through the CLI against live processes.

## What landed in 0.6.0
- **Reference CLI** (`tools/modelrig-cli.py`) — a dependency-free client: pair,
  streaming chat, models, RAG, device list/revoke. A real client you can run today
  while the Kotlin clients await a local build.
- **End-to-end integration test** (`tests/e2e.py`) — starts the **real** backend +
  **real** worker + a fake Ollama and drives the whole flow through the CLI
  (12/12). This is the first test that exercises the modules *together*.
- **Proxy bug found and fixed by that test**: the reverse proxy forwarded upstream
  request bodies with chunked transfer encoding and no `Content-Length`. Real
  Ollama (Go) decodes that fine, but stricter upstreams don't — the proxy now
  preserves `Content-Length`. Exactly the class of bug unit tests miss.
- **Ops** (`deploy/`): env reference, a Windows launcher (`run-windows.ps1`), and
  systemd units for worker + backend.
- **Test suite bundled** (`tests/`, `sh tests/run_tests.sh`) — 55 assertions.

## What landed in 0.5.0 (the V1 push)
**Backend (verified):**
- **Streaming** chat passthrough proven end to end (NDJSON, `/api/v1/chat`).
- **Device management**: `GET /api/v1/devices` (no token hashes) and
  `DELETE /api/v1/devices/{id}` (revoke → token dies immediately).
- **Rate limiting** on `pair/claim` (`MODELRIG_CLAIM_MAX`/5 min per IP) against
  code brute-forcing.
- **`-pair` footgun fixed**: it now detects a running server and mints the code
  over HTTP (single writer), falling back to a direct file write only when no
  server answers.

**Worker (verified):**
- **Chunking** with overlap before embedding; matches now carry `source` +
  `chunk_index` + `score`. `chunk_size`/`overlap` are request params.

**Clients (source only, NOT compiled here):**
- **Streaming** replies token-by-token (desktop `java.net.http` line reader,
  Android OkHttp source reader).
- **Model picker** — desktop pulls `/api/tags` or `/api/v1/models`; Android pulls
  `/api/v1/models`; choice persists on Android via `TokenStore`.

## Verified (ran here)
| Item | How |
|------|-----|
| Backend compiles / vets | `go build ./...` + `go vet ./...` clean |
| Backend behaviour | **28** assertions: core smoke (11) + V1 (17, incl. token rotation) |
| Backend persistence | store JSON inspected: token hash stored, pairings emptied after single use |
| Worker imports & runs | FastAPI app loads; `/healthz` 200 |
| Worker logic | **34**: cosine, validation, 502, chunking, retrieval, source mgmt, source-filtered query, streaming RAG chat |
| **Integrated stack** | **28** e2e assertions: real backend + real worker + fake Ollama via the CLI; request-id tracing, `doctor --deep`, token rotation, streaming RAG chat |

**90 assertions total** via `sh tests/run_tests.sh`.

**Backend V1 test highlights:** streamed chat reassembled from 3 chunks ("Hej fra
ModelRig") · model-list proxy · devices list without `token_hash` · revoke →
revoked token returns 401 · `-pair` HTTP path (code from running server is
claimable) · rate limit (allowed up to limit, then 429).

**Worker V1 test highlights:** chunk_text (empty/short/long, size bounds, no word
loss) · chunk→embed→store→retrieve with stubbed embeddings returns the nearest
source with `chunk_index` + `score`.

**Integration (e2e) highlights:** pair via CLI → `whoami` → models proxy →
**streaming chat reassembled** ("stream-ok") → rag-ingest → rag-query (matches
only, then synthesis) → devices → revoke → a call after revoke correctly fails
401. All through the reference CLI against live backend + worker processes.

## NOT verified here (source only — build locally)
| Item | Why | What to do |
|------|-----|-----------|
| desktop compiles/runs | no JVM-desktop/Gradle toolchain | `cd desktop && gradle run` |
| android compiles/APK | no Android SDK | Android Studio, or `./gradlew assembleDebug` |
| client streaming + model picker | Kotlin not compiled here | exercise against a live rig |
| Kotlin/Compose versions | couldn't resolve deps here | bump if Gradle complains |
| Any live Ollama call (local or cloud) | no Ollama in env | test against your rig |

## Versions & assumptions
- **Go**: module targets `go 1.23`; built with 1.23.4. Still **zero external Go
  deps** (net/http only).
- **Desktop**: Kotlin `2.0.21`, Compose Compiler plugin `2.0.21`, Compose
  Multiplatform `1.7.0`. Plausible, **unverified** — use the current matched pair
  if the build fails.
- **Android**: AGP `8.5.2`, Kotlin `2.0.21`, Compose BOM `2024.09.03`, OkHttp
  `4.12.0`.
- **Ollama Cloud** (desktop fallback): host `https://ollama.com`, header
  `Authorization: Bearer <OLLAMA_API_KEY>`, `/api/chat` (same shape as local),
  `:cloud`-suffix models. Confirmed from docs, not exercised with a real key.
- **Brand palette** invented (graphite/signal/amber) — retune if a real one exists.

## Known limitations (V1)
1. **JSON file store, not SQLite.** Still dependency-free and fine for a handful of
   devices. The `-pair` dual-writer footgun is now handled (HTTP-first). SQLite
   (`modernc.org/sqlite`, pure Go) remains the path once device count / write
   frequency grows.
2. **RAG retrieval is a linear cosine scan.** O(n) per query. Swap in `sqlite-vec`
   / Qdrant past a few thousand chunks.
3. **Streaming fallback is pre-stream only.** If the local source dies mid-stream,
   the error surfaces (we don't restart on cloud and double the output).
4. **`pair/start` is open in dev mode** unless `MODELRIG_ADMIN_KEY` is set (logged
   at startup). `-pair` sends the key automatically when set.
5. **Android stores the token in plain SharedPreferences** and ships
   `usesCleartextTraffic=true` (LAN HTTP). Fine for home LAN; harden with
   Tailscale/HTTPS + DataStore/Keystore.
6. **No Gradle wrapper jar shipped.** Run `gradle wrapper --gradle-version 8.9`
   once, or use a system Gradle.

## Suggested next steps (toward a real 1.0 tag)
1. Build desktop + android locally; fix version drift; confirm streaming + model
   picker against a live rig.
2. Confirm LOCAL→CLOUD fallback by killing Ollama with a cloud key set.
3. Persist desktop settings; add token/sec + per-message source history.
4. Decide SQLite vs JSON for the backend store before scaling device count.
5. Only tag **1.0** once both clients are built and smoke-tested on real hardware.
