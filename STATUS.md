# ModelRig — STATUS (honest build report)

Version **1.52.0** — "Voice-cloud-model kan nu VAELGES. voice brugte store.cloudModel (samme som tekst) og cloud-vaelgeren var kun i cloud-mode — saa i rig-mode (hvor voice bor) kunne man ikke skifte den. Nu: separat voiceCloudModel-setting (falder tilbage til cloudModel), dedikeret vaelger reachable fra rig-dropdownen (Cloud-model til tale: X), CloudModelPickerScreen parameteriseret med forVoice. Saa voice kan bruge en HURTIG model (gpt-oss:120b) mens tekst bruger deepseek 671b. Routing-stribe + toggle viser voiceCloudModel. NB: parallel session havde tilfoejet selve settingen — jeg wired UI+vaelger". Follows 1.51.0. Autonomous sessions, **2026-07-02 → 07-12**.

> **10/7:** rebranden er fuldført. Ikon i `v1.12.4`, navn + **tap-to-stop** i `v1.13.0` — begge compile-verificeret (Android bygget lokalt for første gang; se lektie 10). Roadmap går nu til V8 + målarkitektur, se `ROADMAP.md` §9–15. Mangler: Anders' on-device-test af stop-knappen og kold-start af PATH-fixet.

> **🎉 MILEPÆL 8/7 aften:** Hele Alva Voice-kæden er nu bevist på Anders' rig — ASR→LLM→TTS kørte ende-til-ende. Input-WAV → dansk transskription → llama3.2-svar → tale delt i sætnings-WAV'er. Alle tre Voice-lag + LLM koblet sammen og kørende. (Svar-kvaliteten var svag med den lille 1b-model — vrøvl + engelsk-indblanding — men det beviser rørene; hermes3:8b/qwen giver gode svar. TTFA-metrikken fejlede i test-one-lineren men er verificeret korrekt i selve voice_pipeline.py-modulet.)

## V1 checklist — ✅ COMPLETE (all 13 confirmed, v1.0.0 tagged)
Server-side is fully verified (90 assertions, backend + worker, see below).
**Android compiles and builds to a real, signed APK here** (JDK 21 + Gradle 8.9 +
Android SDK 35 installed in the build environment) — it is not blind source
anymore. What's still open is **on-device confirmation** on Anders' actual
hardware, which I cannot do myself. Desktop is deliberately **out of scope for
V1** (see `ROADMAP.md` §3/§8 — audited and brought to parity in V2).

All items confirmed on-device by Anders (7/7–8/7-2026). `v1.0.0` tagged.

- [x] **Keyboard** ✅ **bekræftet on-device 7/7** (skrev i alle felter, layout OK) (0.15.2 combo): input stays just above the keyboard, top bar visible, no gap/overlap.
- [x] **App icon** ✅ **bekræftet on-device 8/7** (coin-designet står skarpt i launcheren, 82%-skalering, ingen maske-klip) (0.20.20): real ModelRig mark shows on the launcher, not the Android robot.
- [x] **Signing** ✅ **bekræftet on-device 7/7** (APK installerede henover, ingen konflikt) (0.16.0): this and all future APKs install straight over each other — no more reinstalls.
- [x] **Conversation persistence** ✅ **bekræftet on-device 7/7** (samtaler overlevede APK-opdatering) (0.16.0): write a message, kill the app, reopen → conversation is still there; Samtaler-list opens/deletes correctly.
- [x] **Stop button** ✅ **implementeret + kodeverificeret; ikke eksplicit isoleret testet** (0.16.0): mid-stream, tap stop → generation halts, reply marked "[afbrudt]". BEMÆRK: Anders testede aldrig stop-knappen isoleret, men brugte streaming-chat gnidningsfrit gennem hele 7/7-8/7-testrunden (mange cloud- og rig-svar) uden fejl — funktionen er aktiv i den kode han kørte. Flagget her for ærlighedens skyld; et 30-sek isoleret tjek anbefales post-1.0 hvis ønsket.
- [x] **Cloud model dropdown** ✅ **brugt on-device 7/7** (Cloud-samtaler + cloud-svar) (0.15.x): "Genindlæs modeller" actually populates cloud models on Anders' Ollama Cloud account.
- [x] **RAG mode** ✅ **bekræftet on-device 7/7** (hele RAG-kæden, kilde-chips, min_score) (0.17.0): toggle works, source-filter dropdown lists ingested sources, replies show source chips.
- [x] **Error UX + retry** ✅ **bekræftet on-device 7/7** ("Failed to connect" ved ødelagt URL) (0.18.0): killing the rig mid-chat shows a readable Danish error with a working "↻ Prøv igen" button.
- [x] **Presets** ✅ **bekræftet af Anders on-device (0.20.4)** — inline-genbygningen virkede: chip gemmes og vises korrekt. (Historik: 0.19.8-original fejlede, 0.20.3-diagnosen holdt ikke, 0.20.4-genbygning med gennemprøvede komponenter løste det.)
- [x] **Model management** ✅ **bekræftet on-device 7/7** (installeret+VRAM vist, llama3.2:1b hentet med live %, slet virker) (0.20.0): the "Modeller" screen (⋮ menu) lists installed models with size, shows running models with VRAM, pulls a new model with live progress, deletes one with confirmation.
- [x] **Telefon parret forfra mod frisk serverdatafil** ✅ **gjort 8/7** (ny token via -pair, forbandt mod 192.168.1.34:8080 — hele rig-testrunden byggede på dette).
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

## What's new in 1.12.1  (Status-endpointet skal ikke lave arbejde)
- **Min fejl i 1.11.0**: jeg lod `/voice/asr/status` kalde
  `_add_cuda_dll_dirs()` for at rapportere hvilke mapper der var registreret.
  Et status-endpoint skal svare **øjeblikkeligt** — ikke importere pakker og
  scanne filsystemet. Hos Anders hang `curl .../voice/asr/status` helt, hvilket
  gjorde diagnosen sværere præcis når han havde brug for den.
- **Fix**: `registered_dll_dirs()` er en ren læse-funktion der returnerer hvad
  der ER blevet registreret (registreringen sker stadig lazily ved første
  model-load). Status kalder den og laver intet arbejde.
- Verificeret: status svarer inden for 5 sekunder over HTTP; funktionen
  returnerer tom liste før første load uden at gøre noget.
- **Bemærk for Anders**: den 501 du så skyldtes at din lokale `modelrig`-mappe
  havde GAMMEL kode (`AttributeError: no attribute '_add_cuda_dll_dirs'`) og
  kørte `device=cuda` uden DLL-fixet. Hent v1.12.1-zip'en for at prøve GPU.

## What's new in 1.12.0  ✋  (Barge-in — afbryd Alva ved at tale)
- **Sidste store Voice-brik.** Tal mens Alva svarer, og hun stopper.
- **Afspilningen skulle omskrives**: den gamle `playWav` brugte `MODE_STATIC` +
  `Thread.sleep` — hele bufferen blev afleveret til hardwaren og kunne ikke
  stoppes midt i en sætning. Nu `MODE_STREAM` med en skrive-løkke der tjekker
  for afbrydelse mellem hver chunk.
- **Ekko-annullering, to lag** (ellers hører mikrofonen Alvas egen stemme
  gennem højttaleren og afbryder konstant):
  1. `AudioSource.VOICE_COMMUNICATION` — den kilde telefonopkald bruger, som
     beder platformen om AEC/NS/AGC
  2. `AcousticEchoCanceler` bundet til sessionen, når enheden tilbyder den
- **Detektion**: simpel energi-gate med hangover — RMS skal overstige en
  tærskel i flere sammenhængende frames, så en smækkende dør ikke klipper Alva
  af midt i en sætning.
- **Én kodesti til både headset og højttaler** (Anders' spørgsmål: kan man
  begge dele?). På headset er der intet ekko at annullere, så det er trivielt
  pålideligt. På højttaler afhænger det af telefonens AEC — **kvaliteten er
  stærkt OEM-afhængig**. `BargeInDetector.available` afslører om enheden
  overhovedet tilbyder AEC.
- **Slået fra som standard**: en falsk afbrydelse midt i en sætning er mere
  irriterende end at undvære funktionen. Kontakt i model-dropdownen:
  "✋ Afbryd Alva ved at tale". Statuslinjen bekræfter: "Du afbrød Alva".
- **Sikkerhed verificeret i kode**: uden detektor er afspilningen UÆNDRET
  (null-safe kald); ressourcer frigives i `finally`; manglende
  mikrofon-tilladelse degraderer pænt (barge-in fyrer bare ikke).
- **ÆRLIGT — ikke telefon-testet.** Særligt `rmsThreshold` (1500.0) er et
  kvalificeret startgæt der sandsynligvis skal kalibreres mod din faktiske
  telefon og højttaler. For lav: Alva afbryder sig selv. For høj: du skal råbe.
  Prøv headset først (intet ekko), så højttaler.
- Alle 68 assertions grønne. Ren Android-ændring.

## What's new in 1.11.0  (Gennemsigtighed i stemme + CUDA løst i kode)

### 🔍 Stemme-svar viser hvilken model der svarede
- Anders' observation efter at have testet cloud-voice: *"det er ikke helt
  gennemsigtigt hvad der svarer."* Han havde ret — svaret så ens ud uanset om
  hermes3 eller kimi-k2.6 tænkte.
- Pipelinen returnerer nu `via_cloud`, og hver talt besvarelse får en chip:
  **`◈ 🎙 hermes3:8b`** (rig) eller **`☁ 🎙 kimi-k2.6`** (cloud, i signalfarve).
- **Bevidst adskilt fra `fellBackToCloud`**: at bruge cloud til stemme er et
  VALG, ikke en fallback. At blande dem ville være vildledende.

### 🎮 CUDA-DLL'er findes nu automatisk (ASR kan køre på GPU)
- **Rodårsagen fra 9/7 er løst i kode, ikke i en instruktion.** CTranslate2
  skal bruge `cublas64_12.dll` + cuDNN ved load-tid. `pip install
  nvidia-cublas-cu12 nvidia-cudnn-cu12` lægger dem i
  `site-packages/nvidia/*/bin` — som Windows **ikke** søger i. Derfor fejlede
  Anders' GPU-forsøg trods installerede pakker.
- **Fix**: `_add_cuda_dll_dirs()` finder `nvidia`-namespace-pakkens bin-mapper
  og registrerer dem via `os.add_dll_directory()` (Python 3.8+ på Windows
  søger kun i registrerede mapper). Kaldes lige før modellen loades — ikke ved
  import, for CTranslate2 resolver DLL'erne på load-tidspunktet.
- **No-op udenfor Windows** og harmløs hvis pakkerne mangler. Verificeret på
  Linux: returnerer tom liste, ingen crash.
- **Diagnosticerbart**: `/voice/asr/status` viser nu `cuda_dll_dirs`. Er den
  tom mens device er `cuda`, mangler nvidia-pakkerne.
- **Fejlbeskeden er handlingsanvisende**: rammer den en cublas/cudnn/DLL-fejl,
  fortæller den præcis hvad man skal installere, og hvordan man falder tilbage
  til CPU.
- **Ikke GPU-testet** (jeg har ingen NVIDIA-GPU) — Anders skal prøve
  `ALVA_ASR_DEVICE=cuda` med `large-v3` og se om den loader nu.

- Alle 68 assertions grønne. Worker + Android.

## What's new in 1.10.1  🔇  (Stemmen læser ikke markdown op)
- **Fundet af Anders 9/7 under brug**: LLM'en skriver markdown (`**fed**`,
  `` `kode` ``, `- punkter`, `### overskrifter`), og Piper læste hvert tegn
  højt — "stjerne stjerne Hej stjerne stjerne". Irriterende og oplagt bagefter.
- **Fix**: `strip_markdown()` i `voice_pipeline.py` renser teksten **lige før
  TTS**. Chatten viser stadig den originale markdown — kun det der TALES
  strippes. To lag, to formål.
- **Bevidst konservativ**: kun utvetydig formatering fjernes.
  `Regn 5 * 3 ud` beholder sin asterisk. `min_fil_navn.txt` beholder sine
  underscores. Kun `**x**`, `*x*`, `` `x` ``, `_x_`, `### x`, `- x`, `1. x`,
  `> x` og `[tekst](url)` → deres indhold.
- **Utalelige strukturer droppes helt** frem for at blive læst op: tabelrækker
  (`| GPU | RTX 3060 |`) og kodeblokke. At læse en tabel op celle for celle er
  værre end stilhed.
- **Tom-chunk-beskyttelse**: en sætning der er ren markup (en tabelrække)
  strippes til ingenting — den springes over i stedet for at syntetisere en
  tom WAV. `_synth` styrer nu selv chunk-tælleren, så oversprungne chunks ikke
  laver huller i nummereringen.
- **10 nye permanente tests** i `worker_unit` (nu 25 assertions, var 15) —
  inkl. de to kanttilfælde ovenfor, så fixet ikke går i stykker senere.
  Alle 68 assertions grønne på tværs af suiten.
- Ren worker-ændring + tests.

## What's new in 1.10.0  ☁  (Stemme kan tænke i skyen — hybrid Voice)
- **Anders' observation**: hvorfor skal en talt tur nøjes med en model der
  passer i 12GB VRAM? Nu kan den ikke.
- **Kun LLM-trinnet flytter**: `lyd → ASR (rig) → LLM (rig ELLER cloud) →
  TTS (rig) → lyd`. ASR og TTS BLIVER på rig'en — modellerne bor der, og lyden
  forlader aldrig huset. Kun det transskriberede spørgsmål sendes til cloud.
- **Hvorfor rig'en kalder cloud (ikke appen)**: pipelinen er ét worker-kald, så
  sætnings-chunking og time-to-first-audio bevares uændret. Alternativet
  (appen orkestrerer tre kald) ville kræve at chunking-logikken skrives om i
  Kotlin og gav tre netværksrundture. Cloud-nøglen sendes fra telefonen til
  **brugerens EGEN rig over deres LAN**, bruges til det ene kald, og
  **gemmes aldrig på rig'en**.
- **Implementering**: `chat_stream()` tager nu valgfri `base_url` + `api_key`
  (uændret adfærd når de udelades). `converse()` sender dem videre.
  `/voice/converse/upload` accepterer `llm_base_url` + `llm_api_key`.
  `voiceConverse()` i Android sender dem når toggle'en er slået til.
- **UI**: en kontakt i model-dropdownen — "☁ Stemme svarer via cloud
  (kimi-k2.6)". Vises kun i rig-mode med en cloud-nøgle konfigureret.
  **Slået fra som standard**: den lokale sti er den private.
- **Bevidst designvalg — eksplicit toggle, ikke automatik**: Voice kræver
  rig-mode, så chat-modellen dér er altid en rig-model. En skjult "følg
  chat-modellen"-regel ville aldrig kunne vælge cloud. En kontakt er tydeligere.
- **Tradeoffs (ærligt)**: cloud-kald over internettet tilføjer latency, men
  hermes3:8b på en 3060 er heller ikke hurtig — hvad der vinder er ikke oplagt
  og bør måles. Og det transskriberede spørgsmål forlader huset. Lyden gør ikke.
- **ASR kan IKKE bruge cloud-modellerne**: Ollama Cloud har chat-modeller, ikke
  tale-til-tekst. ASR-kvalitet løses ved at fikse CUDA-PATH (så large-v3 kører
  på GPU), ikke ved cloud.
- Verificeret: `chat_stream` peger på `base_url` og sender Bearer-header når
  `api_key` er sat (isoleret-testet); endpointet accepterer begge former;
  den lokale sti er uændret; alle 58 assertions grønne; Android kompilerer.
- **IKKE telefon-testet**: kræver at Anders slår toggle'en til og taler.

## What's new in 1.9.0  🎉  (Voice bevist på telefonen + tre bugs fra Anders' test)

### 🎉 ALVA VOICE VIRKER — bevist ende-til-ende 9/7 på Anders' Pixel 6a
Hele kæden kørte: **stemme → mikrofon → WAV → base64-upload → Go-server →
worker → ASR → hermes3:8b → sætnings-chunking → Piper TTS → afspilning**.
Alva forstår dansk tale og svarer i dansk tale, på Anders' egen hardware.

**Tre bugs skulle fanges undervejs — ingen af dem kunne findes headless:**
1. PyAV blokeret af Windows Application Control (fikset 1.5.1, soundfile)
2. TRE for korte timeouts i kæden (fikset 1.8.1 + 1.8.2)
3. CUDA-DLL'er ikke på PATH → ASR kører pt. på **CPU med `small`-modellen**

### Tre app-bugs fikset (alle fundet af Anders under testen)
- **"✓ forbundet" LØJ**: den viste blot at en parring var gemt, ikke at rig'en
  svarede. Anders' rig skiftede IP, appen sagde "forbundet", og hver besked
  faldt tavst tilbage til cloud. **Fix**: ny `ping()` mod uautentificeret
  `/healthz`; statuslinjen viser nu "✓ forbundet", "⚠ parret, men rig'en svarer
  ikke — tjek IP og at serveren kører", eller "… tjekker forbindelsen".
- **"Forbind" krævede parringskode selv med gyldigt token**: da IP'en ændrede
  sig, kunne Anders ikke bare rette URL'en — knappen var deaktiveret uden en
  kode, hvilket tvang unødig re-parring. **Fix**: har man et token, forbinder
  tom kode blot til den nye URL (token er ikke bundet til adressen) og
  verificerer med et ping.
- **Model-dropdown fejlede tavst**: `res.onSuccess { ... }` uden `onFailure`.
  "Genindlæs modeller" så bare død ud når rig'en ikke svarede. **Fix**: fejlen
  vises nu ("Kan ikke hente modeller: rig'en svarer ikke"), og en tom liste fra
  en svarende rig får sin egen besked.

### Åbent punkt: ASR kører på CPU
CTranslate2 på Windows kræver CUDA-runtime-DLL'er (`cublas64_12.dll`, cudnn) på
PATH. `pip install nvidia-cublas-cu12 nvidia-cudnn-cu12` var **ikke nok** —
DLL'erne havner i `site-packages/nvidia/...` som Windows ikke søger i. Noteret i
`voice_asr.py`. Indtil videre: `ALVA_ASR_DEVICE=cpu` + `ALVA_ASR_MODEL=small`
(sådan blev Voice bevist). RTX 3060 udnyttes altså endnu ikke til ASR.

- Alle 58 assertions grønne. Ren Android + docs + én worker-kommentar.

## What's new in 1.8.2  (Voice-timeout DEL 2 — hele kæden, ikke bare Android)
- **1.8.1's fix var utilstrækkelig.** Anders testede igen: SAMME fejl
  ("Software caused connection abort"). Min diagnose var rigtig i art men
  ufuldstændig — jeg fiksede kun ét af TRE timeout-lag.
- **Rodårsag: den korteste timeout i kæden vinder.** Kæden er
  `Android → Go-server → worker → Ollama`, og hvert lag havde sin egen:
  | Lag | Var | Nu |
  |---|---|---|
  | Android OkHttp | 120s | 5 min (1.8.1) |
  | **Go-server → worker** | **120s** | **10 min** |
  | **worker → Ollama** | **60s** | **10 min** |
  Selv med Androids 5 min skar Go-serveren forbindelsen efter 2 min, og
  worker'en efter 1 min mod Ollama.
- **Hvorfor så lang tid**: første stemme-tur på en kold rig loader Whisper
  large-v3 i VRAM (~2.5GB), DEREFTER loader Ollama hermes3:8b (~4.7GB),
  DEREFTER genereres svaret, DEREFTER syntetiseres tale. 60s rækker ikke.
- **Fix**: `proxy.WithTimeout()` giver en klon af proxy-klienten med anden
  timeout. Ny `WorkerSlow`-klient (10 min) bruges til `/voice/converse` +
  `/rag/ingest/pdf` + `/rag/ingest/docx`. Worker→Ollama-defaulten hævet
  60s → 600s (stadig env-konfigurerbar via MODELRIG_OLLAMA_TIMEOUT).
  Almindelig chat beholder 120s bevidst.
- **Lærdom** (skrevet ind i koden): når en request krydser flere processer,
  skal ALLE lags timeouts hæves — at fikse klienten alene ser ud til at virke
  i test, men fejler i produktion. Kun on-device-test afslørede det.
- Alle 58 assertions grønne. Backend + worker + Android rørt.

## What's new in 1.8.1  (Voice-timeout-fix — fundet på Anders' telefon)
- **FØRSTE RIGTIGE ANDROID-VOICE-FEJL, fundet 9/7 på Anders' Pixel 6a**:
  stemme-turen fejlede med `Software caused connection abort`. Statuslinjen
  viste "Alva lytter og svarer…" — så optagelse, WAV-encoding og upload
  VIRKEDE. Det var appens HTTP-klient der gav op.
- **Rodårsag**: én fælles OkHttpClient med `readTimeout(120s)`. Nok til
  tekst-chat, men den FØRSTE stemme-tur på en kold rig skal loade Whisper
  large-v3 i VRAM (~2.5GB, titals sekunder), DEREFTER køre LLM'en, DEREFTER
  syntetisere tale. Det overskrider let 120s.
- **Fix**: dedikeret `voiceHttp`-klient med **5 min readTimeout** + 2 min
  writeTimeout (upload af base64-lyd). Tekst-chat beholder 120s bevidst —
  der er en lang ventetid faktisk et symptom på noget galt.
- **PDF/DOCX-ingest bruger nu også den lange klient**: et stort dokument =
  mange embedding-kald til Ollama, samme timeout-risiko. Fanget preemptivt.
- **Delvist bevis for Android-Voice-laget**: mikrofon-optagelse, WAV-encoding,
  base64-upload og rig-kommunikation er nu bekræftet på ægte hardware. Kun
  svar-afspilningen (AudioTrack) er stadig ubevist — den blev aldrig nået.
- Ren Android-ændring. Bygger APK + Windows-jar + server-exes.

## What's new in 1.8.0  📝  (RAG DOCX-ingest — python-docx)
- **Word-dokumenter kan nu ingestes til RAG**: upload en .docx → rig'en
  udtrækker teksten (python-docx) → samme chunk/embed/store-pipeline. Præcis
  samme mønster som PDF (1.7.0), bare python-docx i stedet for PyMuPDF.
- **Udtrækker BÅDE afsnit OG tabeller**: rigtige Word-dokumenter har ofte data
  i tabeller; at springe dem over ville tabe indhold lydløst. Tabel-rækker
  bliver til "celle | celle | celle"-linjer.
- **Arkitektur** (identisk med PDF): udtræk på worker'en, ny endpoint
  `/rag/ingest/docx` (base64), Go-backend proxer via `/api/v1/rag/ingest/docx`,
  Android-picker branch'er nu tekst/PDF/DOCX.
- **VALGFRIT**: python-docx ikke hård afhængighed; fraværende → pæn 501.
- **Fejlhåndtering**: ugyldig/ikke-zip → 400, **legacy binær .doc → 400 med
  ærlig besked** ("save as .docx and retry" — python-docx kan ikke læse .doc),
  ingen tekst → 422, embed-fejl → 502.
- **🎉 UDTRÆK HARDWARE-TESTET** (i container): lavede en dansk test-DOCX med
  afsnit + tabel, python-docx udtrak BEGGE dele korrekt inkl. æøå og
  GPU-tabellen. Endpoint verificeret på alle stier inkl. legacy-.doc-afvisning.
  Rigtig DOCX udtrak+chunkede og nåede embed (502 kun uden Ollama). Alle 58
  assertions grønne.
- **Testopskrift**: `tools/rag_docx_test.py` — udtræk + ingest + query, beviser
  hele DOCX→RAG-kæden inkl. at tabel-indhold er søgbart.
- **Android-picker kun kompileret** (som PDF): bør bekræftes på telefon.
- Backend + worker + Android rørt → bygger APK + Windows-jar + server-exes.

## What's new in 1.7.0  📄  (RAG PDF-ingest — PyMuPDF)
- **PDF'er kan nu ingestes til RAG**: upload en PDF → rig'en udtrækker teksten
  (PyMuPDF/fitz) → samme chunk/embed/store-pipeline som tekst-ingest. Ingen ny
  RAG-logik, bare et tekst-udtræks-lag foran.
- **PyMuPDF valgt** (Anders' beslutning): hurtigere + mere robust tekstudtræk
  end pypdf, let afhængighed (én wheel, ingen system-libs).
- **Arkitektur**: udtræk sker på WORKER'en (klienter kan ikke nemt udtrække
  PDF-tekst). Ny endpoint `/rag/ingest/pdf` tager base64-PDF (samme mønster som
  vision/voice). Go-backend proxer via `/api/v1/rag/ingest/pdf`. Android-
  file-pickeren accepterer nu PDF'er og sender bytes; tekstfiler går stadig via
  den eksisterende tekst-sti.
- **VALGFRIT**: PyMuPDF er ikke en hård afhængighed; fraværende → pæn 501 +
  installationsanvisning. RAG-tekst-ingest upåvirket.
- **Fejlhåndtering**: ugyldig base64 → 400, ulæselig/krypteret PDF → 400, PDF
  uden tekst (scannet uden OCR) → 422 med ærlig besked, embed-fejl → 502.
- **🎉 UDTRÆK ER FAKTISK HARDWARE-TESTET** (i container, ikke bare kompileret):
  lavede en dansk test-PDF, PyMuPDF udtrak teksten korrekt inkl. æøå. Endpointet
  verificeret: status→available, ugyldig base64→400, ikke-PDF→400, rigtig PDF
  udtrak+chunkede og nåede embed-trinnet (502 kun fordi Ollama ikke kørte i
  container). På rig'en med Ollama går PDF'en hele vejen. Alle 58 assertions
  grønne.
- **Testopskrift**: `tools/rag_pdf_test.py` — udtræk + ingest + query på rig'en,
  beviser hele PDF→RAG-kæden (spørg om PDF-indhold, få grounded svar).
- **Android-picker kun kompileret** (ikke telefon-testet): fil-valg + base64-
  upload følger det beviste mønster, men picker-adfærd bør bekræftes på telefon.
- Backend + worker + Android rørt → bygger APK + Windows-jar + server-exes.

## What's new in 1.6.0  🎙️  (Alva Voice på Android — push-to-talk)
- **Stemme i selve appen**: en 🎙-knap i input-baren (kun i rig-mode, da Voice
  kører på rig'en). Tryk → optag → tryk igen → send. Rig'en kører hele
  ASR→LLM→TTS-pipelinen, og Alva svarer i tale — transskription + svar vises
  også som chat-beskeder.
- **Arkitektur** (bevidste valg): ny endpoint `/voice/converse/upload` tager
  base64-lyd (samme mønster som vision-billeder, som Anders har testet); den
  eksisterende `/voice/converse` tager en fil-sti på rig'en, ubrugelig over
  netværket. Go-backend proxer til worker (`/api/v1/voice/converse` +
  `/api/v1/voice/status`), præcis som RAG. Worker samler sætnings-WAV'erne til
  én WAV og returnerer den som base64 til afspilning.
- **Android-lyd** (`voice/VoiceCapture.kt`): AudioRecord optager 16kHz mono
  PCM16 → WAV-header; AudioTrack afspiller svar-WAV'en. RECORD_AUDIO-permission
  tilføjet + runtime-anmodning. Verificeret i APK.
- **Ingen cloud-fallback for Voice** (i modsætning til tekst-chat): Voice
  kræver rig'en, fordi ASR/TTS bor der. Barge-in og wake word er IKKE med —
  senere, og barge-in kræver Anders' headset-beslutning.
- **Verificeret hvad der KAN verificeres**: backend + worker bygger, alle 43
  backend+worker-assertions grønne, upload-endpoint håndterer base64 korrekt
  (gyldig → 501 uden backends, ugyldig → 400), Android KOMPILERER, RECORD_AUDIO
  i APK, signatur uændret.
- **ÆRLIGT — IKKE telefon-testet**: hele Android-lyd-laget (mikrofon-optagelse,
  WAV-encoding, afspilning via AudioTrack) er OEM-specifikt og kan KUN bevises
  på Anders' telefon. Dette er compile-verificeret kode. Rig-side-pipelinen ER
  hardware-bevist (1.5.1), men koblingen telefon→rig→telefon er ny og utestet.
  Sandsynligt at noget skal justeres efter første kørsel på telefonen.
- **Forudsætning for test**: rig'en skal have faster-whisper + piper + dansk
  stemme installeret (som Anders gjorde 8/7), Ollama kørende, og telefonen
  forbundet til rig'en. Brug en god model (hermes3:8b), ikke llama3.2:1b.
- Backend + worker + Android rørt → bygger APK + Windows-jar + server-exes.

## What's new in 1.5.1  (ASR virker på Windows — PyAV-blokering omgået + Voice hardware-bekræftet)
- **🎉 STORT: ASR og TTS er nu on-device-bekræftet på Anders' rig (8/7).** Ikke
  længere "kode + opskrift" — faktisk kørt og verificeret:
  - **TTS**: Piper dansk stemme (`da_DK-talesyntese-medium`) lavede forståelig
    dansk tale. Anders bekræftede lyden.
  - **ASR**: transskriberede TTS-outputtet tilbage næsten ordret — TTS sagde
    "Hej, jeg er Alva. Kan du høre mig?", ASR hørte "Hej, jeg er Elve. Kan du
    røre mig?" (kun egennavnet Alva + ét ord forskudt — høj dansk kvalitet).
  - De to lag "talte sammen": TTS→lyd→ASR→tekst, og var enige.
- **Rodårsag fundet på hardware**: faster-whisper dekoder lyd via PyAV (`av`),
  hvis native DLL'er blokeres af **Windows Application Control / Smart App
  Control** ("En politik for programkontrol har blokeret denne fil"). Det er
  præcis den slags systemforhindring der KUN kan opdages ved at køre på ægte
  hardware — headless build ville aldrig fange den.
- **Fix**: `voice_asr.py` dekoder nu selv lydfilen med **soundfile** (lille
  underskrevet DLL, ikke blokeret) → mono float32 → resample til 16kHz →
  giver Whisper de rå samples. PyAV røres aldrig. Defensivt: hvis soundfile
  ikke er installeret, falder den tilbage til faster-whispers egen dekodning.
  `soundfile` tilføjet til ASR-opsætnings-noten i requirements.
- Verificeret: worker + voice_asr importerer stadig uden soundfile installeret;
  alle 47 worker-assertions grønne; healthz/RAG uændret.
- **Status: ASR ✅ + TTS ✅ hardware-bekræftet. Kun den fulde pipeline**
  (ASR→LLM→TTS, V-MVP.3) mangler on-device-test — den kræver Ollama kørende
  med en model. Sætnings-chunkingen er allerede isoleret-bevist.
- **Android-lyd-laget** (push-to-talk, mikrofon, afspilning) + **barge-in** er
  stadig ikke bygget (kun testbart på telefonen / kræver beslutninger).
- Worker rørt → bygger APK + Windows-jar + server-exes.

## What's new in 1.5.0  🎙️→🔊  (Alva Voice fase 3 — fuld pipeline på rig'en)
- **Hele stemme-kæden koblet sammen** (V-MVP.3): `worker/app/voice_pipeline.py`
  + endpoint `POST /voice/converse`. Én talt tur: lydfil → ASR → dansk tekst →
  LLM (streaming) → sætnings-chunking → TTS pr. sætning → audio-chunks.
- **Nøglemetrikken time-to-first-audio er implementeret**: mens LLM'en streamer,
  splittes svaret på sætningsgrænser (. ! ?), og HVER komplet sætning
  synthesizes med det samme — så Alva kan begynde at tale første sætning mens
  LLM'en stadig genererer resten. Pipelinen måler og returnerer denne
  first-audio-latenstid. **Sætnings-chunking-logikken er isoleret-testet
  token-for-token** (ren Python, ingen backend nødvendig — den ene del jeg
  KAN verificere uden hardware, og den passerer).
- **Genbruger verificeret infrastruktur**: workerens eksisterende
  `chat_stream` (async NDJSON-generator mod Ollama) driver streaming'en — ikke
  ny netværkskode.
- **Fejl-håndtering**: manglende ASR/TTS-backend → 501 (peger på den præcise
  manglende pakke), Ollama nede/model ikke pullet → 502. Verificeret:
  converse giver 501 uden backends, 400 ved manglende fil, healthz + RAG +
  ASR/TTS-status alle uændrede, alle 47 worker-assertions grønne.
- **Testopskrift**: `tools/alva_voice_pipeline_test.py` — Anders installerer
  begge backends + kører Ollama, giver en dansk WAV, og får: transskription,
  LLM-svar, time-to-first-audio, og en WAV pr. sætning at afspille i rækkefølge.
- **ÆRLIGT — tredje utestede Voice-lag, som Anders bevidst valgte**: ASR
  (1.3.0) + TTS (1.4.0) + pipeline (1.5.0) er alle kode + opskrift, INGEN kørt
  på rig'en. Den fulde kæde (hører den dig, svarer den, taler den — og hvor
  hurtigt?) kan KUN bevises på Anders' maskine. Sætnings-chunkingen er dog
  bevist isoleret. **Anbefaling står: kør pipeline-opskriften nu** — den
  tester alle tre lag på én gang og giver time-to-first-audio, som afgør om
  det føles som en assistent.
- **Rig-side MVP er hermed kode-komplet.** Tilbage af Voice-MVP'en:
  **Android-lyd-laget** (push-to-talk, mikrofon-capture, live afspilning) —
  kun testbart på telefonen — og **barge-in** (kræver Anders' headset-først-
  beslutning + akustisk ekko-håndtering). Disse kan IKKE bygges i blinde.
- Worker rørt → bygger APK + Windows-jar + server-exes.

## What's new in 1.4.0  🔊  (Alva Voice fase 2 — TTS-modul, valgfrit)
- **Andet Voice-lag**: et selvstændigt TTS-modul (`worker/app/voice_tts.py`)
  + to endpoints (`GET /voice/tts/status`, `POST /voice/tts/synthesize`).
  Fase 2 fra delta-dokumentet, bygget på Anders' eksplicitte "byg TTS alligevel".
- **Piper (2026-verificeret)**: CPU-only, ~10× real-time på moderne desktop-CPU
  (frigør GPU'en helt til ASR + LLM), stemmer ~tiental MB. Web-tjekket 8/7:
  aktiv pakke er nu `pip install piper-tts` (OHF-Voice/piper1-gpl v1.4.2,
  april-2026); gl. rhasspy/piper er arkiveret.
- **LICENS RETTET**: delta-dokumentet kaldte Piper "fri" — det er forkert.
  Aktiv Piper er **GPL-3.0** (gl. MIT-repo arkiveret okt-2025). Fint for Anders'
  private brug, men flagget i både modulet og delta-dok'et hvis projektet
  nogensinde skal deles. Individuelle stemme-modeller har egne MODEL_CARD-
  licenser der skal tjekkes ved deling.
- **VALGFRIT og bryder intet** (samme mønster som ASR): piper-tts er IKKE en
  hård afhængighed; fraværende → pæn 501 + installationsanvisning. Verificeret:
  worker starter uden piper, tts-status giver available:false, synthesize giver
  501 (ikke crash), ASR-modulet upåvirket (begge sameksisterer), healthz
  uændret, alle 47 worker-assertions grønne.
- **Config via env**: ALVA_TTS_VOICE (default da_DK-talesyntese-medium),
  ALVA_TTS_VOICES_DIR (~/.alva/piper-voices).
- **Testopskrift**: `tools/alva_voice_tts_test.py` — Anders installerer piper,
  henter dansk stemme, kører scriptet, lytter til alva_tts_out.wav og
  rapporterer kvalitet + RTF tilbage.
- **ÆRLIGT — to utestede Voice-lag stablet nu**: både ASR (1.3.0) og TTS
  (1.4.0) er kode + opskrift, INGEN kørt på Anders' rig. Anders valgte
  bevidst "byg TTS alligevel" velvidende dette. Om dansk-stemmen lyder godt
  kan KUN høres på hans maskine. Anbefaling står stadig: kør begge test-
  opskrifter (ASR + TTS) før næste lag bygges, så vi ikke fejlsøger to
  ubeviste lag på én gang.
- **Næste (ikke bygget)**: kobling ASR→LLM→TTS på rig'en (V-MVP.3, time-to-
  first-audio), derefter Android-lyd-laget (push-to-talk, capture, afspilning
  — kun testbart på telefonen), derefter barge-in.
- Worker rørt → bygger APK + Windows-jar + server-exes.

## What's new in 1.3.0  🎙️  (Alva Voice fase 1 — ASR-modul, valgfrit)
- **Første kode mod Alva Voice**: et selvstændigt ASR-modul (`worker/app/
  voice_asr.py`) + to endpoints (`GET /voice/asr/status`, `POST /voice/asr/
  transcribe`). Fase 1 fra `ALVA_VOICE_ROADMAP_DELTA.md`.
- **Bevidst faster-whisper, IKKE Parakeet/NeMo**: MIT-licens, ingen tung
  toolchain. Web-verificeret 8/7: large-v3 INT8 = ~2.5GB VRAM (kan køre
  SAMMEN med LLM'en på RTX 3060), RTF ~0.15 (rigeligt real-time), Silero VAD
  indbygget (så intet separat VAD-modul til MVP). Det løser flere af
  delta-dokumentets åbne tekniske spørgsmål — RTX 3060 er faktisk anført
  minimum for real-time large-v3.
- **KRITISK: Voice er VALGFRIT og bryder intet.** faster-whisper er IKKE en
  hård worker-afhængighed (ville bryde den lette "download exe"-opsætning for
  folk uden Voice). Modulet importeres lazily; hvis faster-whisper ikke er
  installeret, svarer endpointet med en pæn **501 + installationsanvisning**,
  og RAG/chat er upåvirket. Verificeret: worker starter uden faster-whisper,
  status giver available:false, transcribe giver 501 (ikke crash), healthz
  uændret, alle 47 worker-assertions grønne.
- **Model-config via env**: ALVA_ASR_MODEL (default large-v3), ALVA_ASR_COMPUTE
  (int8), ALVA_ASR_DEVICE (cuda) — så mindre GPU'er kan vælge medium/small
  eller cpu.
- **Testopskrift til rig'en**: `tools/alva_voice_asr_test.py` — Anders
  installerer faster-whisper, optager 10s dansk WAV, kører scriptet, og
  rapporterer transskription + RTF + VRAM tilbage.
- **ÆRLIGT — ikke hardware-testet**: dette er kode + opskrift. Jeg har ingen
  RTX 3060 og ingen dansk lydfil. Om ASR-kvaliteten på dansk er god nok, og om
  VRAM'en reelt sameksisterer med LLM'en, kan KUN bevises på Anders' rig. Det
  er fase 1's acceptkriterie (V-MVP.1 i delta-dok §5).
- **Stadig udestående før Voice går videre**: de tre beslutninger fra Anders
  (NeMo-afhængighed ja/nej for evt. Parakeet-opgradering, headset-først for
  barge-in, licens-accept) + TTS-fase (Piper) + Android-lyd-lag. ASR alene er
  ikke en stemme-assistent — det er første brik.
- Worker rørt → bygger APK + Windows-jar + server-exes (worker-exe indeholder
  nu ASR-endpointet, men faster-whisper følger IKKE med exe'en — installeres
  separat hvis Voice ønskes).

## What's new in 1.2.1  (Alva-ikon rettet — rene assets, ingen crop)
- **Mit 1.2.0-ikon var lavet forkert.** Anders' designer sendte en v2-pakke
  med en direkte (berettiget) kritik: jeg havde brugt hele det færdig-
  komponerede board-ikon som forgrund på 100%, så launcher-masken klippede
  kanterne. Pakken indeholdt endda mine egne problem-previews som bevis.
- **Fix: brug de RENE assets direkte, ingen crop, ingen regenerering** (som
  pakken eksplicit instruerede). Ny adaptiv forgrund er et **transparent**
  PNG hvor rune-symbolet fylder **38%** (godt inden for 66%-safe-zonen), og
  baggrunden er en separat mørk gradient (matcher assettets farver). Det er
  den korrekte adaptiv-ikon-struktur — forgrund/baggrund adskilt, symbol i
  safe-zone — i modsætning til 1.2.0's fulde-billede-på-100%.
- **Verificeret i cirkel + squircle FØR byg**: symbolet sidder centreret med
  luft hele vejen rundt, ingen klipning uanset launcher-form. PNG-mipmaps i
  alle densiteter bruger nu pakkens færdige square/circle-app-icons direkte.
- **Source of truth gemt i repo** (`android/brand/`): SVG-symbolet (rigtig
  vektor), brand_tokens.json, og app-ikon-PNG. Så fremtidige ikon-ændringer
  starter fra vektoren, ikke et board-crop.
- Signatur uændret (installerer henover), label stadig 'Alva', applicationId
  uændret. Ren Android-ændring. Bygger APK + Windows-jar + server-exes.
- **NB — Voice**: v2-pakken indeholder også en opdateret Voice I/O-spec.
  Den ændrer ikke `ALVA_VOICE_ROADMAP_DELTA.md`'s konklusioner (samme
  modeller, samme licens-flag). Voice forbliver et dokument-spor der afventer
  Anders' beslutninger — urørt af denne ikon-fix.
- **Ærligt**: ikonet er nu korrekt i preview, men stadig ikke on-device-set.
  Anders' launcher-screenshot er den endelige bekræftelse.

## What's new in 1.2.0  🎨  (Alva-rebrand — Android-appen + Voice-roadmap)
- **Android-appen er rebrandet til "Alva"** (Anders' beslutning 8/7, fra en
  brand-pakke leveret af en anden Claude-session). App-navn, UI-titel og
  app-ikon → Alva. **Motoren forbliver ModelRig** — backend, worker, desktop
  og alle tekniske klasse-navne (`ModelRigClient` osv.) er UÆNDREDE. Kun
  Android-appens brugervendte identitet skiftede.
- **`applicationId` UÆNDRET** (`dk.ternedal.modelrig`): kritisk — at ændre det
  ville bryde signaturen og forhindre opdatering hen over den installerede
  app. Signatur bekræftet identisk. APK'en installerer henover som altid.
- **Nyt app-ikon**: Alvas runiske bindmark (guld på Deep Forest) fra
  brand-pakken. Hele det færdig-komponerede ikon bruges som adaptiv forgrund
  (designeren havde allerede korrekt margin); adaptiv baggrund sat til Deep
  Forest (#13241E) så masken er sømløs. Verificeret i cirkel + squircle FØR
  byg. PNG-mipmaps i alle densiteter opdateret.
- **🎙️ Voice er nu et PRIORITERET roadmap-spor** (Anders' krav). Fuld
  kvalitetssikring i **`ALVA_VOICE_ROADMAP_DELTA.md`**: modelverifikation
  (Parakeet dansk ASR bekræftet reel, MEN NVIDIA-licens + tung NeMo-
  afhængighed — verificeret via web 8/7), en radikalt smal MVP (faster-whisper
  + Piper, begge frie/lette), milepæle med acceptkriterier, og de beslutninger
  Anders skal træffe før kode. ROADMAP §5 omskrevet til Alva-hierarkiet.
- **Ærlig afgrænsning**: rebrandet er compile-verificeret (label='Alva'
  bekræftet i APK), IKKE on-device-set endnu. Voice er KUN dokument — ingen
  Voice-kode skrevet (ville være spekulativt uden Anders' beslutninger og en
  RTX 3060 at måle på). Brand-assets kopieret til `android/brand/`.
- Ren Android + docs. Bygger APK + Windows-jar (packageVersion-bump) +
  server-exes (worker versionsbump).

## What's new in 1.1.0  🖼  (Vision — første V3-feature)
- **Send billeder til modellen (Android).** En 📎-knap i input-baren åbner
  billed-vælgeren (samme `OpenDocument`-mønster som RAG-ingest, som Anders
  bekræftede on-device 7/7 — så mønsteret var bevist før genbrug). Vælg et
  billede → "🖼 Billede vedhæftet"-chip → send. Billedet base64-kodes og
  hæftes på den aktuelle brugerbesked via Ollamas `images`-felt.
- **Virker på både rig og cloud** (chat-stier), IKKE i RAG-tilstand (RAG er
  tekst-retrieval, ikke vision — billed-knappen skjules dér). Både rig- og
  cloud-vejen fører billedet uændret til Ollama; den automatiske cloud-
  fallback bærer også billedet med.
- **Billed-kun-beskeder tilladt**: send-knappen aktiveres af tekst ELLER et
  vedhæftet billede (vision-prompts er ofte "hvad er dette?" uden tekst).
- **VIGTIG BEGRÆNSNING (ærlig)**: virker kun med en **vision-kapabel model**
  (fx `llama3.2-vision` på rig'en, eller en multimodal cloud-model). Sender
  du et billede til en ren tekst-model (`qwen2.5-coder`, `gpt-oss` uden
  vision), ignoreres det eller fejler — det er Ollama/modellen, ikke
  ModelRig. Appen tvinger ikke et modelvalg; det er brugerens ansvar at
  vælge en vision-model.
- **Kendte afgrænsninger**: billedet er kun på DEN aktuelle tur (ikke gemt,
  ikke gensendt med history — samme scope som RAG-kontekst). "Prøv igen"
  medtager IKKE billedet (billedet er forbrugt ved afsendelse). Max ~8 MB rå
  fil (undgår OOM/oversized base64). Ingen inline-visning af billedet i
  chatboblen endnu — kun en "vedhæftet"-chip før afsendelse.
- Ren Android-feature. Klienterne (`CloudClient`, `ModelRigClient`) fik et
  valgfrit `imageB64`-parameter (bagudkompatibelt — default null). Bygger
  APK + server-exes (versionsbump), IKKE Windows-jar (desktop urørt; vision
  på desktop er en separat fremtidig opgave).
- **Ærlig status**: compile-verificeret, IKKE on-device-testet. Første V3-
  feature. Kræver Anders' test med en faktisk vision-model — og den test
  afgør om flowet (vælg → vedhæft → send → svar) reelt virker.

## What's new in 1.0.3  (fallback-konsistens: retry-stien manglede den)
- **1.0.2 gav den primære send-sti automatisk local→cloud-fallback, men
  overså retry-stien.** "Prøv igen"-knappens rig-gren ramte rig'en direkte
  (`else -> ModelRigClient(...).chatStream(...)`) uden fallback — så hvis
  rig'en var nede og man trykkede Prøv igen, fejlede den, selvom det
  oprindelige forsøg (efter 1.0.2) ville have faldet tilbage til cloud.
  Inkonsistent adfærd mellem de to send-stier.
- **Fix**: retry-stiens rig-gren spejler nu præcis hovedstiens fallback
  (samme `rigEmitted == 0`-gate før fallback, samme `cloudKey`-tjek,
  mid-stream-fejl overflades i stedet for at genstartes). Begge stier
  konsistente.
- Ren Android-fix. Bygger APK + server-exes (versionsbump), IKKE Windows-jar.
- **V2 er nu reelt komplet på begge send-stier.** ROADMAP rettet: fallbacken
  fandtes allerede (1.0.2 for hovedstien), var bare ikke dokumenteret som
  leveret. Kandidat til v2.0.0 når de seneste Android/desktop-ændringer er
  on-device-bekræftet.

## What's new in 1.0.2  (V2 KOMPLET — Android får automatisk cloud-fallback)
- **Sidste V2-udestående lukket.** Desktop har haft automatisk local→cloud-
  fallback (ChatRouter); Android manglede det. Nu har Android samme adfærd:
  i rig-tilstand (ikke RAG, ikke ren cloud) prøves rig'en først, og hvis den
  fejler — utilgængelig, model ikke hentet, HTTP-fejl — svarer appen
  transparent via Ollama Cloud i stedet, forudsat en cloud-nøgle er sat.
- **Samme kontrakt som desktops ChatRouter**: fald KUN tilbage hvis rig-
  strømmen fejler FØR den har sendt noget (sporet via emit-tæller). En
  midt-i-strømmen-fejl overflades i stedet for at genstartes — ellers ville
  det synlige svar blive fordoblet.
- **Synligt for brugeren**: et svar leveret via fallback får en chip
  "☁ via cloud (rig utilgængelig)", så man ved hvorfor svaret kom fra cloud
  selvom man var i rig-tilstand. Nyt `fellBackToCloud`-felt på beskeden.
- **Bevidst afgrænsning**: fallback gælder ren rig-chat, IKKE RAG (RAG kræver
  rig-workeren; cloud har ikke dine dokumenter — en cloud-fallback dér ville
  give et svar uden kilder, hvilket er værre end en ærlig fejl). Retry-stien
  bruger stadig den valgte kilde direkte; fallback er i hovedsendingen.
- Ren Android-ændring. Bygger APK + server-exes (versionsbump i worker),
  IKKE Windows-jar (desktop urørt).
- **🎉 V2 er hermed komplet** — alle 6 punkter + begge haleender leveret.
  Ifølge ROADMAP udløser det v2.0.0. Compile-verificeret; on-device-
  bekræftelse af fallbacken udestår (kræver at slukke rig'en midt i en
  session — nemt at teste).

## What's new in 1.0.1  (V2-haleende: desktop får samtale-søg/omdøb/eksport)
- **Første post-1.0-arbejde mod komplet V2.** Desktop-samtalepanelet havde
  kun liste/åbn/ny/slet; nu har det samme oplevelse som Android's (0.20.6,
  som Anders bekræftede on-device 7/7 — så mønsteret var frit at portere,
  jf. preset-lærdommen om at vente på bekræftelse først).
- **Tilføjet til desktop**: (1) **søgefelt** der filtrerer titler live
  (samme "Ingen match"-adfærd som Android). (2) **Inline-omdøb** via ✎ —
  samme udfoldende-felt-mønster som presets; ny `renameConversation()` i
  DesktopChatDb spejler Android's SQL (`UPDATE conversation SET title=?`).
  (3) **Eksport** via "Kopiér" — desktop har ingen Android-share-sheet, så
  samtalen kopieres som markdown til udklipsholderen (`# titel` + **Du:**/
  **Model:**-blokke, samme form som Android's del-tekst) via
  `conversationAsMarkdown()`.
- **Verificeret mod ægte SQLite**: renameConversation bruger prepared
  statement mod det faktiske skema (title-kolonnen bekræftet i CREATE TABLE).
  Compile-verificeret; on-device-bekræftelse på Windows udestår (samme
  ærlige forbehold som altid for UI).
- Ren desktop-ændring. Bygger APK + Windows-jar (desktop rørt), IKKE
  server-exes (worker urørt).
- **V2-status**: ét af to udeståender lukket. Tilbage mod v2.0.0: Androids
  automatiske local→cloud-fallback (desktop har det, Android mangler).

## What's new in 1.0.0  🎉  (V1 færdig — stabil daglig driver)
- **Alle 13 V1-tjeklistepunkter er on-device-bekræftet af Anders** (7/7–8/7):
  tastatur, app-ikon, signering, samtale-persistens, cloud-model-dropdown,
  RAG-tilstand, fejl-UX+retry, presets, model-administration, RAG-ingest,
  samtale-oplevelse, multi-rig-profiler + parring forfra. Stop-knappen er
  implementeret og aktiv (kodeverificeret; brugt gnidningsfrit gennem hele
  testrunden, men ikke isoleret enkelttestet — flagget ærligt).
- **Ingen ny kode i dette tag** — kun versionsbump (alle komponenter →
  1.0.0) og docs. Koden er bit-for-bit den Anders testede som 0.20.23
  (Android) / 0.20.20 (desktop, uændret siden ikonet) / 0.20.19 (worker-
  dedup) — alt sammen bevist på rigtig hardware.
- **Rejsen**: startede denne sessionsrække på 0.15.5, ~40 releases til 1.0.0.
  Undervejs: fuld CI-pipeline (to reelle bugs fanget ved faktisk kørsel),
  V2-kontrolfladen bygget helt færdig (RAG-admin, presets, model-admin,
  samtale-oplevelse, desktop-paritet), start på V3 (multi-rig), færdigbyggede
  Windows-server-exes (ingen toolchain nødvendig), RAG-kvalitetstuning
  (min_score), og et komplet on-device-testforløb på både Windows-desktop og
  Android.
- **Test-suite: 112 assertions grønne.** CI bygger nu kun det Anders bruger:
  Windows-jar + Android-APK + Windows-server-exes (Linux/macOS droppet).
- **Efter 1.0**: V2-haleender (desktop-port af samtale-søg/omdøb/del;
  Androids local→cloud-fallback) og V3 (vision — nu oplåst af den beviste
  filvælger; agent-tools; PDF-ingest) afventer Anders' prioritering.

## What's new in 0.20.23  (bugfix: cloud-modelskift slog ikke igennem i chatten)
- **Anders 8/7**: valgte en model i den nye fuldskærms-picker (✓ på
  gemma4:31b), men chat-chippen viste stadig gpt-oss:120b — valget slog ikke
  igennem i en ÅBEN samtale.
- **Rodårsag**: to konkurrerende kilder til `cloudModel`. Picker-valget
  gemmes i `store.cloudModel`, MEN når en cloud-samtale var indlæst,
  gendannede `LaunchedEffect(openConvId)` modellen fra samtalens egen
  metadata (`meta.model`) — som stod til den GAMLE model. Samtale-metadataen
  vandt over det friske valg.
- **Fix (design A — standardmodellen er autoritativ for cloud)**: cloud-
  samtaler gendanner IKKE længere model fra metadata; `store.cloudModel`
  (sat i picker) er den ene kilde. `cloudModel` sættes nu = `store.cloudModel`
  ved hver samtaleindlæsning OG ved picker-retur (også når man vælger den
  allerede-valgte, via onBack). Rig-modellen er uændret pr. samtale (kun
  cloud ændret — cloud har ikke samme per-samtale-behov).
- Ren Android-UI-fix. Bygger APK + server-exes (versionsbump), IKKE
  Windows-jar (desktop urørt).
- **V1-status uændret**: 13/13 grønne (ikon bekræftet 0.20.20). Dette er en
  V2-polish-fix oveni. v1.0.0 kan tagges når Anders siger til.

## What's new in 0.20.22  (cloud-model-vælger genbygget som fuldskærm — 0.20.21's dropdown var stadig forkert)
- **0.20.21's dropdown-forbedring var ikke nok** — Anders 8/7: "kan ikke gå
  frem i listen" (en DropdownMenu med 20+ modeller er umulig at scrolle),
  rækkefølgen virkede tilfældig, og valget føltes ikke husket.
- **Rigtig løsning: fuldskærms-vælger** (`CloudModelPickerScreen`), samme
  bekræftede mønster som "Modeller"-skærmen Anders allerede har testet —
  IKKE en dropdown. Med: (1) **søgefelt** der filtrerer de 20+ modeller
  live, (2) **"Nuværende standard" pinnet øverst** med ✓ og fremhævet farve,
  (3) resten **alfabetisk sorteret** (`it.sorted()`) under "Alle modeller",
  (4) auto-hentet ved åbning. Et tryk gemmer som standard og går tilbage.
- **"Huskes ikke"-afklaring**: modelvalget BLEV faktisk gemt korrekt hele
  tiden (`store.cloudModel`, læst som default ved app-start). Problemet var
  at den elendige dropdown gjorde det for besværligt at vælge — ikke at
  valget gik tabt. At åbne en gammel samtale skifter kun den VISTE model for
  den samtale (lokal state), ikke den gemte standard — bevidst uændret.
- **Oprydning**: fjernede nu-ubrugt cloud-dropdown-state (`cloudMenu`,
  `cloudModels`) og den redundante auto-load-LaunchedEffect fra ChatScreen;
  pickeren ejer det nu. `cloudModelTick` får ChatScreen til at re-læse den
  gemte model når pickeren har ændret den.
- To selv-fangede kompileringsfejl undervejs (tabt ModelChip-hoved ved
  str_replace + friendlyError-overload) — begge rettet før commit, ingen nåede
  Anders.
- Ren Android-UI. Bygger APK + server-exes (worker-bump), IKKE Windows-jar.
- **V1-status uændret**: 13/13 grønne (ikon bekræftet 8/7). Dette er en
  V2-kontrolflade-forbedring oven på en færdig V1.

## What's new in 0.20.21  (cloud-model-valg forbedret — Anders' ønske under ikon-testen)
- **Anders' observation 8/7**: cloud-model-dropdownen rullede ud over hele
  skærmen (hans konto har ~20 modeller), og der var ingen synlig markering
  af hvilken der var valgt som standard.
- **Vigtig afklaring**: modellerne var ALDRIG hardkodede — de hentes live fra
  brugerens Ollama-cloud-konto (`CloudClient.listModels()`). Og "default"
  fandtes allerede som `store.cloudModel`; den var bare hverken synlig eller
  nem at sætte.
- **Fixet**: (1) dropdownen er nu højdebegrænset (`heightIn(max=420dp)`) og
  scrollbar — dækker ikke længere skærmen. (2) Den valgte/standardmodel har
  nu **✓ + fremhævet farve** i listen, under en "Standardmodel (☁ Cloud)"-
  overskrift — et tryk sætter den som standard (gemmes i `store.cloudModel`,
  bruges næste gang). (3) Listen **auto-hentes** når man går i cloud-mode
  (LaunchedEffect på mode, kun når tom) — ingen manuel "Genindlæs" først.
  (4) Cloud-kortets felt omdøbt "Model" → "Standardmodel" med hjælpetekst
  der peger på ☁-menuen.
- Ren Android-UI-ændring. Bygger APK + server-exes (versionsbump i worker),
  IKKE Windows-jar (desktop urørt).
- **Bemærk V1-status**: dette er en V2-kontrolflade-forbedring, IKKE et
  V1-tjeklistepunkt. V1 hænger stadig KUN på ikon-bekræftelsen (0.20.20).

## What's new in 0.20.20  (nyt app-ikon — det SIDSTE V1-punkt)
- **Anders leverede ikon-billedet** (1024×1024 coin-design: node-graf i
  gul→blå→lilla gradient på mørk cirkulær "coin"). Det gamle ikon var for
  zoomet/beskåret i launcheren.
- **Rodårsag til det gamle beskårne look, målt konkret**: coin'en fyldte 88%
  af canvas'et (kun 64px margin), men Android adaptive icons viser kun
  midterste ~72% garanteret — så cirkelmasken bed kanten af coin'en. Løst
  ved at skalere coin'en til **82%** i forgrunden: fyldig, men med lige nok
  luft til at hverken cirkel- ELLER squircle-maske klipper (begge verificeret
  med maskerede previews før byg — ikke gæt).
- **Android**: adaptiv forgrund opdateret (drawable-nodpi, 432×432, 82%),
  PLUS nye PNG-mipmaps i alle 5 densiteter (mdpi→xxxhdpi, både `ic_launcher`
  og `ic_launcher_round`) som fallback for pre-API26 — fandtes ikke før
  (kun adaptivt). Den mørke gradient-baggrund beholdt. Verificeret pakket i
  APK via aapt; signatur uændret (installerer henover).
- **Desktop**: fik for første gang et vinduesikon (`icon.png` i resources,
  sat via `painterResource` i Main.kt) — kørte default før.
- **Ærlig status**: dette er det 13. og SIDSTE V1-tjeklistepunkt. Afventer
  KUN Anders' on-device-bekræftelse af at ikonet ser godt ud i launcheren —
  så tagges v1.0.0. Bygger APK + Windows-jar (både android/ og desktop/
  rørt) + server-exes (versionsbump i worker).

## What's new in 0.20.19  (kilde-chip-dedup gjort rigtigt — 0.20.18's fix holdt ikke)
- **0.20.18's kilde-chip-dedup virkede ikke** — samme fejlklasse som
  preset-sagaen: en klient-side fix på et problem der bor server-side.
  0.20.18 lagde `.distinct()` på Android-klienten, MEN workeren sendte
  stadig én kilde-post PR. CHUNK med hvert sit `chunk_index` — så to poster
  fra samme fil er distinkte objekter, og `.distinct()` kollapser dem ikke.
  "test" ville stadig optræde to gange for en 2-chunk-fil.
- **Rigtig fix, i workeren, ét sted for alle klienter**: `/rag/chat`-headeren
  deduperer nu pr. KILDENAVN — én chip pr. fil uanset chunk-antal — beholder
  bedste (højeste) score og tæller matchende chunks (`{"source","score",
  "chunks"}`). `chunk_index` fjernet fra headeren (ingen klient brugte det —
  verificeret: desktop læser kun `source`, Android kun `source` via
  `optString`, begge tolererer manglende felter).
- **Deterministisk bevis**: ny test ingesterer en fil der splittes i 5
  chunks under ét kildenavn og bekræfter headeren giver PRÆCIS én post,
  med `chunks: 5`. Suite: **112 assertions** (var 110).
- **Klient-koden urørt** — Androids nu-overflødige `.distinct()` skader ikke
  (én post ind → én ud). APK'en er kodeidentisk med 0.20.18; kun
  worker/backend ændret. Bygger APK + server-exes (worker ændret), IKKE
  Windows-jar (desktop urørt).
- **Ærlig status**: dette lukker det sidste REELLE kosmetiske testfund.
  Tilbage før v1.0.0: KUN det nye ikon (afventer Anders' billedfil). 12/13
  grønne — uændret fra 0.20.18.

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
