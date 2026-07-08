# ModelRig — Roadmap: V1 → V2 → V3

**Gældende version:** 0.15.5 · **Dato:** 2026-07-04 · **Ejer:** Anders
**Estimat-enhed:** "byggesession" = én autonom arbejdsblok med Claude; leverer typisk 1 tagget release.

---

## 1. Formål og vision

ModelRig er Anders' personlige **Local AI Control Surface**: én privat, selv-hostet
platform (Go-backend + Python RAG-worker + Kotlin-klienter) der styrer lokale og
cloud-modeller på hans præmisser. Roadmappen bringer projektet fra "virker og er
on-brand" (0.15.x) til **stabil daglig driver (V1)**, derefter **fuld kontrolflade
(V2)** og til sidst **udvidet platform (V3)**.

Principper der gælder hele vejen: SQLite-first, minimale afhængigheder, ingen
Docker/cloud uden begrundelse, dansk UI, ærlig skelnen mellem compile-verificeret
og runtime-verificeret, alle leverancer tagget og released på GitHub.

---

## 2. Status ved 0.15.5

### Verificeret
- **Server:** 90 test-assertions grønne. Parring → hashede tokens, rotation,
  rate-limit, streaming chat-proxy, RAG-endpoints, deep health, request-ID-logging,
  Ollama Cloud-auth (Bearer-injektion bevist mod fake-cloud).
- **Android (on-device, Anders' Pixel):** app starter, cloud-chat streamer
  (glm-5/gpt-oss), Keystore-krypteret nøgle overlever genstart, brand-palette og
  chat-layout renderer korrekt.
- **Android (compile-verificeret her):** markdown-renderer, per-source
  system-prompts, model-dropdowns (rig + cloud), adaptivt ikon med det ægte mærke
  ekstraheret fra brand-pakken.
- **Flow:** in-sandbox Android-toolchain bygger rigtige APK'er; alle releases
  ligger på GitHub med zip + APK.

### Afventer on-device-bekræftelse
1. Tastatur-adfærd med 0.15.2-kombinationen (`adjustResize` + `imePadding`) —
   screenshot med tastatur åbent mangler.
2. Ikonet (0.15.5, det ekstraherede mærke) på launcheren.
3. Om `ollama.com/api/tags` reelt fylder cloud-model-dropdownen på Anders' konto.

### Kendte mangler (ærlig liste)
- **Ingen samtale-persistens** — alt forsvinder når appen lukkes.
- **Ingen stop-knap** — streaming kan ikke afbrydes.
- **RAG bruges ikke fra appen** — hele RAG-stakken (ingest, retrieval, streaming
  RAG-chat med kilder) er bygget og testet server-side, men Android kan kun ren chat.
  Det er det største gab mellem det byggede og det brugte.
- **Hele historikken sendes hver gang** — ubegrænset payload; dyrt mod cloud-kvote
  og æder lokal kontekst.
- **Debug-signering pr. session:** debug-keystoren genereres i sandkassen, som
  nulstilles mellem sessioner → første APK i en ny session har ny signatur, og
  Android nægter at opdatere oven på (kræver afinstallation = mistet nøgle/prompts).
  Reelt drift-problem, skal løses tidligt.
- Fejl vises råt (`⚠️ Fejl: …`), ingen retry.
- Ikonet er let blødt (kilde-PNG i beskeden opløsning; SVG fra kildefil ønskes).
- Desktop-klienten er ikke rørt/auditeret i denne sessionsrække.
- Ingen CI — builds afhænger af sandbox-toolchainen (geninstalleres pr. session).

---

## 3. V1 — "Stabil daglig driver" ✅ **OPNÅET — `v1.0.0` tagget 8/7-2026** (alle 13 tjeklistepunkter on-device-bekræftet)

**Definition of done:** Anders kan bruge appen hver dag mod rig og cloud uden at
miste data, kan afbryde svar, kan stille RAG-spørgsmål mod sit eget indeks fra
telefonen, og kan installere nye versioner oven på gamle uden afinstallation.

### 0.16 — Fundament der ikke smuldrer (1–2 sessioner) — ✅ leveret i `v0.16.0` (afventer on-device-verifikation)
- **Stabil app-signering.** Dedikeret release-keystore med fast signatur på tværs
  af sessioner. Anbefaling: keystore committes i det private repo; password i
  Notion Secrets (hentes pr. session ligesom PAT). Éngangsomkostning: skiftet fra
  debug-signatur kræver **én** afinstallation → cloud-nøgle + prompts indtastes
  igen én gang. Kommunikeres i release-noten.
  *Acceptkriterie:* APK'er bygget i to forskellige sessioner kan installeres oven
  på hinanden.
- **Samtale-persistens.** Android's indbyggede SQLite (ingen ny dependency).
  Skema v1: `conversation(id, title, source, model, created_at, updated_at)` +
  `message(id, conv_id, role, content, created_at)`; versionering via
  `PRAGMA user_version`. Løbende autosave; seneste samtale genåbnes ved start;
  simpel samtaleliste (ny / åbn / slet — omdøb og søgning er V2).
  *Acceptkriterie:* samtaler overlever app-kill og telefon-genstart.
- **Stop-knap.** `call.cancel()` eksponeres i begge klienter (CloudClient har
  allerede hook'en); send-knappen bliver stop-ikon under streaming.
  *Acceptkriterie:* streaming stopper < 1 sekund efter tryk.

### 0.17 — RAG i lommen (1–2 sessioner) — ✅ leveret i `v0.17.0` (afventer on-device-verifikation)
- **RAG-tilstand i appen** (kun synlig når rig er aktiv): toggle Chat/RAG der
  kalder backendens streaming RAG-chat i stedet for ren chat. Kilderne fra
  første NDJSON-linje vises som chips over svaret (kilde-transparens er hele
  pointen med RAG). Præcis endpoint-path verificeres mod koden ved implementering.
- **Historik-trimning:** send system-prompt + seneste N beskeder inden for et
  tegn-budget (start: N=20 / ~24.000 tegn, konstant i koden). Gælder både rig og
  cloud. Ingen summarization i V1 (bevidst fravalg — koster kald og kompleksitet).
- *Hvis let:* kilde-filter-dropdown (fra `rag-sources`) i RAG-tilstand.
  *Acceptkriterier:* RAG-svar med synlige kilder on-device; payload er bounded
  uanset samtalelængde.

### 0.18 — Fejl-UX og drift (1 session) — ✅ leveret i `v0.18.0` (afventer on-device-verifikation)
- Pæn fejlhåndtering: netværk nede / 401 / ukendt model vises menneskeligt, med
  **"Prøv igen"** på sidste besked (manuel retry — automatisk backoff er fravalgt
  i V1 for enkelhed).
- **Driftdokumentation:** Tailscale-opsætning (rig nås uden for hjemmenetværk),
  backup/restore af `modelrig-data.json` + worker-databasen, geninstallations-guide.

### 0.19 — V1-hærdning — ✅ delvist leveret i `v0.19.0` (afventer Anders' bekræftelse for `v1.0.0`)
- Fuld regression: server-suiten grøn (90/90 — bekræftet). ✅
- Docs ajour (README, STATUS, ROADMAP, CLIENT_BUILD_AND_TEST — rettede en
  forældet "intet Android SDK"-påstand i STATUS.md, tilføjede RAG/retry-tjek). ✅
- **Tilbage (kræver Anders, ikke mere kode):** luk V1-tjeklisten i `STATUS.md`
  (8 punkter) → så tags `v1.0.0` med det samme. `v0.19.0` er bevidst *ikke*
  `v1.0.0` — den tag sætter jeg ikke uden bekræftelse; det ville være falsk
  sikkerhed.

### Bevidste fravalg i V1
Multitråds-UI ud over simpel liste, summarization, automatisk retry, desktop-paritet,
CI, RAG-ingest fra telefonen. Alt sammen bevidst skubbet — se V2.

**V1 samlet estimat: 4–6 byggesessioner.**

---

## 4. V2 — "Kontrolflade" (leveres som v1.1 → v1.x; tag `v2.0.0` når komplet) ✅ **KOMPLET — udløser `v2.0.0`** (8/7-2026: alle 6 punkter + begge haleender leveret)

Tema: fra chat-app til det, navnet lover — en kontrolflade for hele rig'en.

1. **RAG-administration fra appen.** ✅ **Leveret i `v0.20.2`** (Android).
   Filvælger (Storage Access Framework) i RAG-kilde-dropdownen, læser
   txt/md-tekst og ingester via `ModelRigClient.ingestText()`. Backend-
   kontrakten var allerede permanent testet (`worker_rag.py`/`e2e.py`); ny
   Android-side kode er compile-verificeret, ikke on-device-testet endnu.
   PDF/DOCX-udtræk fortsat udenfor scope. Desktop mangler samme feature.
2. **Presets/personaer.** ✅ **Leveret** — Android i `v0.19.8`, desktop i
   `v0.19.9` (samme skema, samme UX). Gemte system-prompts pr. kilde med
   hurtigskift (SQLite-tabel, chips). Kørt tidligt, uafhængigt af
   V1-tjeklisten. Ikke on-device-testet endnu.
3. **Model-administration.** ✅ **Leveret** — backend + Android i `v0.20.0`,
   desktop i `v0.20.1` (samme metoder, virker mod begge kilder). Pull/slet/
   kørende modeller via backend-proxy mod Ollamas API, streaming download-
   fremgang. 9 permanente backend-tests (99 assertions total). Ikke
   on-device-testet endnu.
4. **Samtale-oplevelse.** ✅ **Leveret i `v0.20.6`** (Android). Omdøb
   (inline, samme mønster som presets), søgning (live filter på titler),
   markdown-eksport/deling via Androids indbyggede deling. Ikke
   on-device-testet endnu. Desktop mangler samme feature.
5. **Desktop-paritet.** ✅ **Audit gennemført + første løft leveret** (0.19.1,
   kørt sideløbende med V1 mens Anders' bekræftelse afventes). Fund fra audit:
   - **Kompilerer OG pakker nu rent** (`BUILD SUCCESSFUL` for både `build` og
     `packageUberJarForCurrentOS`) — opgraderet fra "uverificeret kildekode" til
     "compile- og pakke-verificeret". Ikke *kørt* (headless sandbox, intet
     display) — det er stadig åbent, og et Linux-bygget jar/installer kan
     ikke bruges på Windows (native Skiko er OS-specifik selv i en uber-jar).
   - **Netværkskoden er solid**: `ChatRouter`/`OllamaClient` matcher de samme
     verificerede Ollama-API-shapes som Android bruger. Ingen bugs fundet.
   - **Local→cloud-fallback: findes nu på begge platforme.** ~~Android kræver
     manuelt Rig/Cloud-skift.~~ **Rettelse (1.0.2)**: Android HAVDE allerede
     automatisk fallback i den primære send-sti (rig-chat prøver rig'en, falder
     transparent tilbage til cloud hvis den fejler før noget emitteres — samme
     "fald ikke tilbage midt-stream"-kontrakt som desktops `ChatRouter`, med et
     `fellBackToCloud`-flag vist til brugeren). ROADMAP var forældet på dette
     punkt. Det REELLE hul var at **retry-stien manglede samme fallback** —
     "Prøv igen" mod en nede rig fejlede i stedet for at falde tilbage. Fikset
     i 1.0.2, så begge send-stier er konsistente.
   Leveret i 0.19.1: **brand-farver rettet** (matcher nu Androids verificerede
   palette), **dansk UI** (matchede ikke tidligere projektets faste regel),
   **system-prompt pr. kilde** (samme mønster som Android, med samme kendte
   forenkling — prompten følger den *foretrukne* kilde, ikke nødvendigvis den
   der reelt svarer efter et fallback).
   Leveret i 0.19.2: **markdown-rendering** portet fra Android (næsten ordret —
   ingen Android-specifikke API'er i den originale fil).
   Leveret i 0.19.3: **SQLite-persistens** (`org.xerial:sqlite-jdbc`, samme
   skema som Android), runtime-verificeret med en midlertidig smoke-test mod
   rigtig SQLite (ikke kun compile-verificeret). Kun stille genindlæsning af
   seneste samtale — ingen samtale-browser endnu.
   Leveret i 0.19.4: **RAG-tilstand** (`net/RagClient.kt`), samme mønster og
   forenkling som Android (enkelt-skud pr. spørgsmål), runtime-verificeret mod
   en rigtig lokal HTTP-server (samme metode som SQLite-testen).
   **Paritetslisten er nu fuldført** (brand, dansk UI, system-prompts, markdown,
   persistens, RAG). Samtale-browser (liste/skift/slet) ✅ **leveret i
   `v0.20.7`** — bevidst afgrænset til Android's oprindelige 0.16.0-scope
   (ikke det nyere 0.20.6 søgning/omdøb/del, som afventer on-device-
   bekræftelse først).
6. **CI (GitHub Actions).** ✅ **Leveret** (`.github/workflows/build-and-release.yml`,
   v0.19.5). Ved tag-push (`v*`): kører hele server-suiten (90 assertions),
   bygger Android-debug-APK, og bygger **genuint cross-platform desktop-jars**
   (Windows/macOS/Linux-runnere hver især — løser det jeg selv flaggede i
   0.19.1: en Linux-bygget jar kan ikke køre på Windows, men en
   **Windows-runner** kan bygge en ægte Windows-jar). Til sidst pakkes
   kilde-zip'en (samme excludes som hele sessionen) og alt uploades automatisk
   til releasen via `softprops/action-gh-release`. Fjerner sandbox-toolchainen
   som flaskepunkt — reproducerbare builds fremover, ikke afhængige af at jeg
   geninstallerer JDK/Gradle/Android SDK hver session. Verificeret ved reelt at
   tagge og observere kørslen (se release-noten for v0.19.5).
7. *Evt.* Robolectric-tests for kritisk Android-logik (trimning, persistens) —
   ny dependency, tages kun hvis fejl i praksis retfærdiggør den.

**V2 samlet estimat: 5–8 byggesessioner.**

---

## 5. V3 — "Alva: personlig assistent" (brand-reframe 8/7-2026)

**Navnehierarki (Anders' beslutning 8/7):** appen hedder nu **Alva**, motoren
forbliver **ModelRig**. Android-appen er rebrandet i `v1.2.0` (app-navn +
UI-titel + ikon → Alva; `applicationId` og backend uændret). Undersystemer:
Alva Voice, Alva Memory, Alva Tools, Alva UI — se `BRAND_IDENTITY.md` og
`ALVA_VOICE_ROADMAP_DELTA.md`.

Flere af undersystemerne findes allerede under andre navne:
- **Alva Memory** = eksisterende RAG + samtale-persistens + presets (leveret).
- **Alva UI** = eksisterende Android/desktop-oplevelse (rebrandet, ikke ny).
- **ModelRig Core** = eksisterende Go-backend + worker + Ollama-routing.

### 🎙️ Alva Voice — PRIORITERET spor (nyt, stort)

Samlet Voice I/O: push-to-talk → VAD → ASR → LLM-streaming → sentence-chunking
→ TTS → audio-queue → barge-in. **Dette er hovedsporet fremad.** Fuld
kvalitetssikring, modelverifikation, licens-flag, MVP-scope og milepæle med
acceptkriterier ligger i **`ALVA_VOICE_ROADMAP_DELTA.md`**. Kernepunkter:
- **MVP holdes smalt**: push-to-talk + Silero VAD + faster-whisper (MIT, let)
  + eksisterende Ollama-streaming + Piper TTS (fri). Beviser latency-kæden med
  mindst mulig ny afhængighed.
- **Parakeet dansk ASR er kandidat, ikke låst**: bedre dansk kvalitet, MEN
  NVIDIA Open Model License + tung NeMo-afhængighed (bryder exe-simpliciteten).
  Verificeret 8/7. Fase 2, som isoleret modelbytte.
- **Nøglemetrik**: time-to-first-audio — Alva taler efter første sætnings-chunk.
- **Barge-in er V1-krav** men teknisk svært (akustisk ekko) — headset-først i MVP.
- **Kræver beslutninger fra Anders før kode**: NeMo-afhængighed ja/nej,
  headset-først ja/nej, Parakeet-licens-accept. Se delta-dok §6.

### Øvrige V3-punkter (uprioriteret, efter Voice-MVP)

- **Vision:** ✅ **Leveret i `v1.1.0`** (Android — billeder til vision-modeller
  via Ollamas images-felt). Compile-verificeret, afventer on-device-test med en
  vision-model.
- **Share-target:** "Del til Alva" fra enhver app → RAG-ingest eller chat.
- **Baggrunds-generering** med notifikation (foreground service).
- **Multi-rig-profiler** ✅ **Leveret i `v0.20.8`**, on-device-bekræftet 8/7.
- **Widget / Quick Settings-tile**; **Biometrisk lås** foran cloud-nøglen.
- **Alva Tools / agent-tools** (modellen kalder værktøjer via rig'en). Kræver
  stadig den gennemtænkte sikkerhedsmodel — størst usikkerhed i hele roadmappen.

---

## 6. Kvalitet og test pr. milepæl

- Server-suiten (90+ assertions) skal være grøn ved hvert tag; nye backend-endpoints
  får tests i samme release.
- Android forbliver **compile-verificeret her + on-device-tjekliste** i hver
  release-note (kort, konkret, afkrydselig). Automatiske UI-tests er bevidst
  fravalgt i V1 (emulator i sandbox er tung/usikker); revurderes i V2 (pkt. 7).
- Backend/worker-versionskonstanter bumpes i takt med app'en, så `/healthz`
  matcher release-tagget (etableret praksis).
- Skelnen **compile-verificeret vs. runtime-verificeret** fastholdes eksplicit i
  STATUS.md ved hver release.

---

## 7. Risici

1. **Signatur-skiftet (0.16):** én planlagt afinstallation; mistes hvis den ikke
   kommunikeres tydeligt → står i release-noten med fed.
2. **Insets/tastatur på andre enheder:** notorisk flaky domæne; verificeret på
   Pixel/Android 15, andre enheder kan afvige.
3. **Ollama Cloud-drift:** endpoints/kvoter/modelnavne kan ændre sig; isoleret i
   `CloudClient` (ét sted at rette).
4. ~~**Sandbox-toolchain pr. session:** ~5–10 min reinstallations-overhead og risiko
   for versionsdrift indtil CI (V2 pkt. 6) fjerner afhængigheden.~~ **Løst:**
   CI (`v0.19.5+`) fjerner afhængigheden — 6+ releases bevist stabilt siden.
5. **RAG-kvalitet:** delvist adresseret i `v0.20.11` (relevans-tærskel så
   irrelevante matches ikke tvinges ind som kontekst; sætningsbevidst
   chunking) — og **tærskel-adfærden er nu live-bekræftet on-device**
   (6/7-2026: "hej" mod en reel kilde gav ærligt "I don't know" uden
   kilder, i stedet for støj-kontekst). Selve 0.3-værdien er stadig et
   udgangspunkt, ikke empirisk tunet — forvent justering ved daglig brug.
6. **PDF-ingest (V2)** er en kendt scope-fælde; startes smalt og udvides kun ved behov.
7. **Ikon-skarphed:** afhænger af SVG fra kildefilen (åbent spørgsmål 2).

---

## 8. Åbne spørgsmål

1. ~~**Desktop i V1 eller V2?**~~ **Afgjort: V2.** Anders sagde "kør efter
   roadmap" uden indsigelse mod anbefalingen; 0.16–0.18 er bygget derefter.
2. **Findes logoets SVG/kildefil?** Delvist afgjort — Anders leverede
   `ModelRig_logo_icon_exports.zip` (rasterexports af det godkendte design,
   ikke vektor), brugt siden 0.16.0. En ægte SVG ville stadig gøre ikonet
   pixel-skarpt, men er ikke blokerende for V1.
3. **CI via GitHub Actions ok** trods "ingen cloud uden grund"? Stadig åbent —
   relevant først i V2 (§4 pkt. 6).
4. **RAG-dokumenttyper:** hvad er vigtigst efter txt/md — PDF? DOCX? Stadig
   åbent — relevant først i V2 (§4 pkt. 1).
5. ~~**Release-keystore-placering?**~~ **Afgjort: privat repo**
   (`android/signing/`), password også i Notion Secrets som backup. Implementeret
   i 0.16.0.

---

## 9. Konkrete næste skridt

1. **Anders:** kør V1-tjeklisten i `STATUS.md` igennem på telefonen (8 punkter,
   ~10 minutter) — det er nu det eneste der står mellem 0.18.0 og `v1.0.0`.
2. **Hvis alt er grønt:** sig det, og `v1.0.0` tagges med det samme (docs +
   tag, ingen ny kode ventet).
3. **Hvis noget fejler:** giv symptom + hvilket punkt, så rettes det målrettet
   (ikke gættet på).
4. **Efter v1.0.0:** V2 starter med RAG-ingest fra appen (0.19/2.0-serien, se
   §4) — først når V1 reelt er lukket, ikke før.
