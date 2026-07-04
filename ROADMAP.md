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

## 3. V1 — "Stabil daglig driver" (mål: tag `v1.0.0`)

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

## 4. V2 — "Kontrolflade" (leveres som v1.1 → v1.x; tag `v2.0.0` når komplet)

Tema: fra chat-app til det, navnet lover — en kontrolflade for hele rig'en.

1. **RAG-administration fra appen.** Upload via Androids filvælger →
   backend → worker-ingest; liste/slet kilder; stats-skærm. Formater: `.txt`/`.md`
   først; PDF kræver ekstraktion i worker (ny dependency, fx pypdf — begrundes når
   vi når dertil, PDF-parsing er notorisk rodet, så scope holdes smalt).
2. **Presets/personaer.** Gemte system-prompts pr. kilde med hurtigskift i chatten
   (SQLite-tabel; UI-chips).
3. **Model-administration.** Pull/slet/kørende modeller via backend-proxy mod
   Ollamas API med streaming download-progress og diskplads-visning. (Endpoints er
   standard Ollama-API; verificeres mod Anders' version ved implementering.)
4. **Samtale-oplevelse.** Omdøb, søgning, markdown-eksport/deling af samtaler.
5. **Desktop-paritet.** ✅ **Audit gennemført** (0.19-sessionen, uden nyt tag —
   ingen kodeændring, kun undersøgelse). Fund:
   - **Kompilerer nu rent** (`BUILD SUCCESSFUL`, Kotlin 2.0.21 + Compose
     Multiplatform 1.7.0-pinningen holder) — opgraderet fra "uverificeret
     kildekode" til "compile-verificeret". Ikke kørt (headless sandbox, intet
     display) — det er stadig åbent.
   - **Netværkskoden er solid**: `ChatRouter`/`OllamaClient` matcher de samme
     verificerede Ollama-API-shapes som Android bruger. Ingen bugs fundet.
   - **Fungerende feature Android mangler**: automatisk local→cloud-fallback
     (Android kræver manuelt Rig/Cloud-skift). Værd at overveje at låne til
     Android i V2.
   - **Reelt gab til Android-featuresættet**: `Brand.kt` har stadig den
     **gamle, opfundne palette** (samme farver Android havde før den blev
     rettet til det verificerede brand) — ikke opdateret. **Ingen** markdown-
     rendering, **ingen** persistens (kun in-memory, som README selv noterede),
     **ingen** system-prompts, **ingen** RAG. Reelt: en fungerende men spartansk
     chat-klient, et helt versionstrin bagud.
   - **Løft til paritet** (næste desktop-session): brand-farver, markdown, SQLite-
     persistens, system-prompts, RAG — samme rækkefølge som Android fik dem,
     minus alt keyboard/inset-arbejdet (irrelevant på desktop).
6. **CI (GitHub Actions).** Tests + APK-build ved tag-push, assets uploades
   automatisk til releasen. Dette er en begrundet cloud-undtagelse: det fjerner
   sandbox-toolchainen som flaskepunkt og gør builds reproducerbare. Gratis-tier
   rækker rigeligt til dette omfang (tjek aktuel kvote ved opsætning).
7. *Evt.* Robolectric-tests for kritisk Android-logik (trimning, persistens) —
   ny dependency, tages kun hvis fejl i praksis retfærdiggør den.

**V2 samlet estimat: 5–8 byggesessioner.**

---

## 5. V3 — "Udvidet platform" (horisont, ikke plan)

Uprioriteret liste — rækkefølge afgøres når V2 nærmer sig:

- **Share-target:** "Del til ModelRig" fra enhver app → RAG-ingest eller chat.
- **Voice-input** (Androids SpeechRecognizer; on-device på nyere Pixels, ellers
  enheds-afhængigt — ærligt forbehold).
- **Vision:** send billeder til multimodale modeller (Ollamas chat-API tager
  base64-billeder; afhænger af modeludvalg).
- **Baggrunds-generering** med notifikation når svaret er klart (foreground service).
- **Multi-rig-profiler** (hjemme/arbejde) med hurtigskift.
- **Widget / Quick Settings-tile** til lynhurtig chat.
- **Biometrisk lås** (BiometricPrompt) foran cloud-nøglen.
- **Agent-tools** (modellen kalder værktøjer via rig'en). Bevidst sidst: kræver
  tool-calling-modne modeller og en gennemtænkt sikkerhedsmodel — størst usikkerhed
  i hele roadmappen.

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
4. **Sandbox-toolchain pr. session:** ~5–10 min reinstallations-overhead og risiko
   for versionsdrift indtil CI (V2 pkt. 6) fjerner afhængigheden.
5. **RAG-kvalitet:** chunking/embedding "virker" men er ikke tunet — forvent
   iteration når den bruges dagligt fra telefonen.
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
