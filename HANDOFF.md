# ModelRig / Kaliv — handoff til ny chat

**Dato:** 2026-07-12 (aften) · **Version:** v1.55.0 · **Repo:** `github.com/Ternedal/ModelRig` (**PUBLIC** — gratis CI)

Copy/paste dette som første besked i en ny chat.

---

## 0. Læs først: hvad der er akut

1. **⚠️ GitHub PAT'en er stadig aktiv** og er brugt til 50+ releases.
   Revokér den: `github.com/settings/tokens` → ny token → opdatér origin-URL
   + Notion. Dette er højeste prioritet og har været flagget siden 9/7.
2. **Streamende voice (v1.54.0-1.55.0) afventer on-device-test.** Kaliv skal nu
   tale første sætning mens resten genereres. Testpunkter: (a) taler den før
   hele svaret er færdigt, (b) opdateres RMS-meteret under tale, (c) fyldes
   assistent-boblen sætning for sætning, (d) virker barge-in stadig midt i
   streamen, (e) pauser/overlap mellem sætninger? Det gamle bufrede endpoint
   er urørt som fallback.
3. **Anders har flere kopier af repoet** (`modelrig`, `modelrig-new`,
   `modelrig-mono`) med forskellig kode-alder. Det har forårsaget flere falske
   fejlspor. Ryd op: behold én mappe. **"Compiled ≠ shipped" og "editing the
   tree ≠ shipping"** er standing rules af samme grund.
4. **Appen hedder KALIV** (Anders' beslutning 9/7; før: Alva). Kun BACKEND
   er ModelRig (server/worker/repo/API/exes); ALT brugervendt er Kaliv.
   `applicationId dk.ternedal.modelrig` er permanent og må ALDRIG ændres.
5. **Kør-kommandoer:** "kør" / "kør videre" = fuld autonom eksekvering uden
   check-ins. "test jeg" = Anders tester på hardware. Anders kører flere
   parallelle Claude-sessioner med fuld commit-autoritet — pull/rebase før
   hvert arbejde, og tjek version-sites for kollisioner.
   `Kaliv` (verificeret i den byggede APK), worker-env er `KALIV_*` med
   ⚠️ **Lektie (fra rebranden):** §0 påstod "rebranden er FÆRDIG" efter ikon +
   navn, mens appen indeni stadig var safir-blå. Anders opdagede det. Et ikon
   er ikke et brand. Skriv aldrig "færdig" om noget der ikke er efterprøvet mod
   selve leverancen. (Desktop er siden rebrandet fuldt: Kaliv-navn v1.35.0,
   ikoner v1.39.0, chat-redesign v1.41.0, native tænke-animation v1.47.0.)

   **Åben rest:** brand-fontene (Cinzel/Cormorant + Montserrat) findes ikke
   som filer i pakken — display bruger platform-serif indtil de lægges i
   `res/font`.

---

## 1. Hvad projektet er

**ModelRig** er en selvhostet LLM-platform. **Kaliv** (før 9/7: Alva) er
Android-appen (samme kodebase; motoren hedder stadig ModelRig).

**Anders' opsætning:**
- Rig: Windows-PC, RTX 3060 12GB, IP ændrer sig (var `.34`, så `.5`)
- Telefon: Pixel 6a (`192.168.1.6`)
- Ingen git på rig'en — koden hentes som ZIP fra GitHub
- Ollama-modeller: `llama3.2:1b`, `nomic-embed-text`, `qwen2.5-coder:7b`, `hermes3:8b`
- Cloud: Ollama Cloud, standardmodel `kimi-k2.6`

**Komponenter:**
| Del | Sprog | Port | Rolle |
|---|---|---|---|
| Backend | Go | 8080 | Telefonvendt API, proxer til worker |
| Worker | Python/FastAPI | 8099 | RAG, ASR, TTS, voice-pipeline (loopback) |
| Ollama | — | 11434 | LLM + embeddings |
| Android | Kotlin Compose | — | Alva-appen |
| Desktop | Kotlin Compose | — | Windows-klient (jar) |

---

## 2. Sådan starter Anders rig'en (tre vinduer)

**Vindue 1 — Ollama:**
```cmd
ollama serve
```

**Vindue 2 — worker** (fra repo-mappen):
```cmd
cd /d "%USERPROFILE%\Desktop\modelrig-new"
set PYTHONPATH=%CD%\worker
python -m uvicorn app.main:app --host 127.0.0.1 --port 8099
```

**Vindue 3 — server:**
```cmd
cd /d "%USERPROFILE%\Desktop"
set MODELRIG_HOST=0.0.0.0
modelrig-server-windows-x64.exe
```

**Kritisk:**
- `set MODELRIG_HOST=0.0.0.0` **skal** sættes, ellers binder serveren til
  loopback og telefonen kan ikke nå den. `set` gælder kun i det ene vindue.
- `modelrig-server-windows-x64.exe -pair` **genererer kun en kode og
  afslutter** — serveren startes bagefter uden `-pair`.
- Worker-exe'en (`modelrig-worker-windows-x64.exe`) indeholder **ikke** de
  valgfrie pakker (faster-whisper, piper, pymupdf, python-docx). Voice/PDF/DOCX
  kræver at worker'en køres fra Python-kildekoden.

**Valgfrie pakker på rig'en:**
```cmd
pip install faster-whisper piper-tts soundfile pymupdf python-docx
pip install nvidia-cublas-cu12 nvidia-cudnn-cu12
mkdir "%USERPROFILE%\.alva\piper-voices"
cd /d "%USERPROFILE%\.alva\piper-voices"
python -m piper.download_voices da_DK-talesyntese-medium
```

---

## 3. Hvad der VIRKER (hardware-bekræftet, pr. 12/7)

| Feature | Bevist |
|---|---|
| PDF/DOCX-ingest → RAG (inkl. tabeller) | ✅ grounded svar |
| TTS (Piper dansk) + ASR (faster-whisper, CUDA large-v3) | ✅ |
| Voice ende-til-ende på telefonen | ✅ tale → ASR → LLM → TTS → afspilning |
| **Voice-via-cloud** (LLM-trin til Ollama Cloud) | ✅ deepseek-671b svarede korrekt (12/7, efter keep_alive-fixet) |
| Barge-in + tap-to-stop + RMS-meter | ✅ bekræftet i device-test-arc'en |
| Markdown strippes fra tale | ✅ læser ikke "stjerne" op |
| **Agent-laget** (læse rig-status, skrive noter bag bekræftelseskort) | ✅ on-device 11/7 |
| **qwen3:14b** kender identitet + tools ("Jeg er Kaliv... læse riggens status") | ✅ 12/7 — markant bedre end hermes3 |
| Rig-model-skifter i dropdownen (auto-load, ◈ på valgt) | ✅ 12/7 |
| Emoji-strip (deterministisk, klient-side) + persona | ✅ 12/7 |
| Voice-cloud-model-vælger ("Cloud-model til tale") + retur til rig | ✅ 12/7 |
| Routing-stribe (tekst-/tale-model + cloud-indikator) | ✅ 12/7 |
| Desktop: Kaliv-rebrand, chat-redesign, ikoner, slet-crash-fix | ✅ 12/7 |
| CUDA / GPU-ASR (`large-v3` på 3060) | ✅ |

## 4. Hvad der IKKE er testet (afventer Anders)

- **Streamende voice (v1.54.0-1.55.0)** — DET store åbne punkt. Kaliv skal
  tale første sætning mens resten genereres. Se §0 punkt 2 for testpunkterne.
  Bufret endpoint urørt som fallback.
- **Foto→RAG ("＋ Gem i Viden", v1.42.0)** — kræver `KALIV_VISION_MODEL` sat
  på workeren (fx `llama3.2-vision:11b`); uden den svarer knappen med den
  ærlige 501. VRAM-kabale: ASR + gen + VLM kan ikke alle være resident på
  12 GB — model-swap-latens forventet.
- **Eval-harnessen mod rigtige modeller** — `python -m app.eval_models
  hermes3:8b qwen3:14b` på riggen. Giver TAL på tool-disciplin/dansk/latens.
- **migrate_data på riggen** — `python -m app.migrate_data` (dry-run, så
  `--apply`): samler gamle relative datafiler i data-roden.
- **Desktop native tænke-animation (v1.47.0)** — Canvas-tegnet, kan ikke
  fryse som WebP'en, men om kredsløbet SER rigtigt ud er ikke bekræftet.

---

## 5. LØST 9/7 ~21:50 — CUDA-DLL-søgestien (fixet i v1.12.3)

**Root cause:** `os.add_dll_directory()` er ikke nok på Windows for
CTranslate2. Beviskæden fra riggen: mapperne VAR registreret
(`cuda_dll_dirs` udfyldt), `cublas64_12.dll` LÅ på disken (102 MB) — og
encode fejlede alligevel, fordi CTranslate2 slår cuBLAS op ad den klassiske
søgesti, som kun kigger i PATH. Manuel `set PATH=...nvidia\cublas\bin;...`
→ voice virkede øjeblikkeligt, ende-til-ende på telefonen.

**Fix (v1.12.3):** `_add_cuda_dll_dirs()` prepender nu også bin-mapperne
til `PATH`. Ingen manuelle env-linjer ved normal start.

**Vigtig detalje:** fejlen udløses først ved første `encode()` — IKKE ved
model-konstruktion. Derfor var gårsdagens isolerede "MODEL LOADED OK" falsk
tryghed: konstruktionen rører ikke cuBLAS.

Historik nedenfor bevaret som dokumentation af diagnosen.

**Oprindeligt symptom:** `POST /voice/converse/upload` → `501` i
worker-loggen. Appen viste "Software caused connection abort".

**Udført 9/7 aften (denne + forrige session):**
- ASR isoleret: BESTÅET (`cuda`, `large-v3`, MODEL LOADED OK)
- TTS isoleret: BESTÅET (`available: True`, VOICE LOADED OK)
- Kodegennemgang: 501 var en **catch-all for ALLE RuntimeErrors** fra
  pipelinen — også model-load-fejl. Isolerede tests i et cmd-vindue
  beviser derfor INTET om worker-processen (andet miljø, andre
  env-vars, potentielt anden Python).

**Fixet i v1.12.2:**
- 501 betyder nu KUN "pakke ikke installeret" (`VoiceBackendMissing`)
- Alle andre pipeline-fejl → **503** med samme detail-besked
- **Worker-konsollen logger fejlen med fuld traceback** — appen behøver
  ikke vise noget; svaret står i vindue 2

**Sådan blev den fundet (udført 9/7 aften):** worker startet fra ren
v1.12.2, voice prøvet fra telefonen, fejlen læst i vindue 2
(`pipeline_failure='Library cublas64_12.dll is not found...'` + traceback).
Diagnose-kommandoerne, til reference:
```cmd
curl -s http://127.0.0.1:8099/voice/tts/status
mkdir C:\Temp 2>nul
echo {"text":"hej","out_path":"C:/Temp/t.wav"} > %TEMP%\tts.json
curl -s -X POST http://127.0.0.1:8099/voice/tts/synthesize -H "Content-Type: application/json" -d @%TEMP%\tts.json
```
Sammenlign `voices_dir` fra status med hvor `.onnx`-filen faktisk ligger.

**Hypoteser undervejs** (alle afkræftet af loggen — bevaret som historik):
- `ALVA_TTS_VOICES_DIR`/`ALVA_TTS_VOICE` sat anderledes i worker-vinduet
- `piper-tts`/`faster-whisper` i en anden Python end worker'ens
- Worker startet fra mappe med gammel kode (sket to gange 9/7)

---

## 6. Arkitektur — Voice

```
telefon → [Go-server :8080] → [worker :8099] → ASR → LLM → TTS → lyd tilbage
                                                      ↑
                                          rig-Ollama ELLER Ollama Cloud
```

- **ASR og TTS kører altid på rig'en** (modellerne bor der; lyden forlader
  aldrig huset)
- **LLM-trinnet kan flytte til cloud** (toggle i model-dropdownen). Kun det
  transskriberede spørgsmål sendes ud. Nøglen sendes fra telefon → egen rig,
  bruges én gang, gemmes aldrig.
- **Sætnings-chunking**: LLM'ens svar splittes på `.!?` og hver komplet sætning
  synthesizes med det samme → lav *time-to-first-audio*.

**Endpoints (worker):**
```
GET  /voice/asr/status          POST /voice/asr/transcribe
GET  /voice/tts/status          POST /voice/tts/synthesize
POST /voice/converse            (fil-sti, rig-lokal)
POST /voice/converse/upload     (base64, telefonvendt)
GET  /rag/ingest/pdf/status     POST /rag/ingest/pdf
GET  /rag/ingest/docx/status    POST /rag/ingest/docx
```

**Env-variabler:**
```
ALVA_ASR_MODEL      (default large-v3)
ALVA_ASR_DEVICE     (default cuda)
ALVA_ASR_COMPUTE    (default int8)
ALVA_TTS_VOICE      (default da_DK-talesyntese-medium)
ALVA_TTS_VOICES_DIR (default ~/.alva/piper-voices)
MODELRIG_OLLAMA_TIMEOUT (default 600)
MODELRIG_HOST       (sæt til 0.0.0.0!)
```

---

## 7. Hårdt tillærte lektier (gentag ikke disse fejl)

1. **Den korteste timeout i kæden vinder.** Voice fejlede fordi der var TRE
   timeouts: Android (120s), Go-server (120s), worker→Ollama (60s). At fikse
   klienten alene så rigtigt ud i test og fejlede i praksis. Nu: 5min / 10min /
   600s. Almindelig chat beholder bevidst 120s.

2. **PyAV blokeres af Windows Application Control.** faster-whisper dekoder lyd
   via PyAV, hvis DLL'er Windows afviser. `voice_asr.py` dekoder nu selv med
   `soundfile`.

3. **CUDA-DLL'er er ikke på Windows' søgesti.** `pip install nvidia-cublas-cu12`
   lægger dem i `site-packages/nvidia/*/bin`, som Windows ikke søger i.
   `_add_cuda_dll_dirs()` registrerer dem via `os.add_dll_directory()`.

4. **Et status-endpoint må ikke lave arbejde.** Jeg lod `/voice/asr/status`
   kalde DLL-registreringen; den hang, netop når Anders skulle diagnosticere.

5. **"✓ forbundet" må ikke betyde "en parring er gemt".** Den skal pinge.
   Appen sagde "forbundet" mens alt faldt tilbage til cloud.

6. **Multi-line Python one-liners virker ikke i cmd.** Skriv en `.py`-fil.
   cmd bruger `%USERPROFILE%` ikke `~`, `mkdir` uden `-p`, `cd /d` ved drevskift.

7. **On-device-test er den eneste sandhed.** Alle tre store Voice-bugs
   (PyAV, timeouts, CUDA) var usynlige for headless builds.

7b. **Læs fejlteksten FØR du fikser.** To gange på to dage: 501'eren sagde
   `cublas64_12.dll is not found` mens vi fejlsøgte TTS, og CI sagde
   `Artifact storage quota has been hit` mens jeg opgraderede Node-actions.
   Svaret stod der begge gange.

7c. **At kompilere er ikke at shippe.** v1.20.0 byggede rent og leverede nul
   assets. `release`-jobbet verificerer nu at .apk/.zip/.exe faktisk ligger på
   releasen, og fejler hvis ikke.

9. **Læs koden før du skriver planen.** PLAN_v1.13.0 påstod at stop skulle
   "annullere den kørende streaming-request". Forkert: `/voice/converse`
   er ikke streaming — appen får ét samlet WAV, og sætnings-chunkingen sker
   inde i workeren. Det rigtige stop er et flag som `playWav`s skriveløkke
   tjekker, fordi coroutine-cancel ikke kan afbryde et blokerende
   `AudioTrack.write()`.

10. **Android KAN compile-verificeres i sandboxen.** JDK 21 er der;
   `sdkmanager` + platform-35 + build-tools tager ~4 min, og
   `./gradlew :app:assembleRelease` kører igennem. Ingen grund til at
   skubbe utestet Kotlin ud og håbe på CI. (`local.properties` må ikke
   committes.)

10. **Blokerende arbejde i `async def` fryser hele workeren.** `tools_chat`
   kaldte den synkrone `GATE.propose()` direkte (nvidia-smi, disk, sqlite), og
   `voice_pipeline.converse()` kaldte `transcribe_wav()` — sekunders CUDA-arbejde.
   Målt: et 1-sekunds tool gav **1005 ms** event-loop-stall; med `to_thread` 4 ms.
   Alt blokerende skal i en tråd — men **behold serialiseringen** med en lås,
   for event-loopet serialiserede dem utilsigtet, og modelobjekterne er delte.

9. **En ny gren i et `when` arver ingenting.** Tools-grenen blev sat foran
   normal-vejen og tabte lydløst: samtalehistorik (v1.25.0), RAG-kontekst
   (v1.26.0), vedhæftet billede + persistens af svaret (v1.27.0). Ingen fejl,
   ingen advarsel — bare et svar der manglede noget. Når du tilføjer en gren:
   list hvad de andre grene gør, og forklar for hver ting hvorfor din ikke
   behøver den.

8. **`os.add_dll_directory` er ikke nok på Windows.** CTranslate2 loader
   cuBLAS ad den klassiske søgesti (kun PATH). Mappen var registreret,
   DLL'en lå på disken — load fejlede alligevel, og først ved `encode()`,
   ikke ved konstruktion (så "MODEL LOADED OK" beviser intet om CUDA).
   Fix i v1.12.3: sæt BÅDE add_dll_directory og PATH.

8. **Fire versionskonstanter bumpes i lockstep:** `worker/app/main.py`
   (VERSION), `backend/internal/config/config.go` (Version),
   `desktop/composeApp/build.gradle.kts` (packageVersion),
   `android/app/build.gradle.kts` (versionName). CI's smoke test fejler
   releasen hvis server-exe'ens /healthz ikke matcher (fanget 9/7, v1.12.2).

---

## 8. Arbejdsform med Anders

- **Svar på dansk.** Koncist, ærligt, direkte. Ingen falsk sikkerhed.
- **Skeln verificeret / kvalificeret gæt / gætværk.** Sig hvad der ikke er testet.
- **"Kør" / "kør videre"** = fuld autonom eksekvering uden check-ins.
- **Hver release tagges `vX.Y.Z`** med CI-verifikation (vent ~5 min, tjek assets).
- **MVP → V1 → V2.** Byg smalt, bevis, udvid.
- **Notion-MCP må ALDRIG kaldes uopfordret.**
- **DKK ved priser.** København/Nørrebro som kontekst.
- Anders sætter pris på ærlig modstand. Sig fra hvis noget ikke kan bygges
  meningsfuldt uden hans test eller beslutning — det er sket flere gange og
  har været den rigtige beslutning.

---

## 9. Toolchain (skal genopsættes i ny session)

Alt ligger i `/tmp`, forsvinder mellem sessioner:
```
JDK 21      /usr/lib/jvm/java-21-openjdk-amd64
Gradle 8.9  /tmp/gradle-8.9    (GRADLE_USER_HOME=/tmp/gradle-home)
Android SDK /tmp/android-sdk   (SDK 35, build-tools 35.0.0)
Go          /tmp/goroot        (GOCACHE=/tmp/gocache GOPATH=/tmp/gopath GOFLAGS=-mod=mod)
```

**Byg:**
```bash
# Android (første build efter stor ændring timer ofte ud — kør igen)
cd android && timeout 160 /tmp/gradle-8.9/bin/gradle :app:assembleDebug --no-daemon --console=plain

# Backend
cd backend && go build -o /tmp/modelrig-server ./cmd/modelrig-server

# Worker-import-tjek
export PYTHONPATH="$PWD/worker" && python3 -c "from app.main import app"
```

**Tests (68 assertions):**
```bash
python3 tests/backend_smoke.py   # 11
python3 tests/worker_rag.py      # 32
python3 tests/worker_unit.py     # 25
```

**APK-signatur SKAL forblive:**
`656392b03a321501ba91769be888ed4c9baa3275479bfbb18e5205824c8ae926`
(`applicationId` = `dk.ternedal.modelrig` — må ALDRIG ændres)

**Release-flow:**
```bash
git add -A
git -c commit.gpgsign=false commit -F /tmp/msg.txt   # commit via fil
git fetch <url> main && git rebase FETCH_HEAD        # ALTID (parallel session)
git push <url> main:main
# opret release via GitHub API, make_latest=true, prerelease=false
# vent ~250s, verificér run + assets
```

---

## 10. Roadmap — hvad der kan bygges

**Kan bygges og verificeres uden Anders:**
- Flere dokumentformater (PPTX, HTML) — samme mønster som PDF/DOCX
- Forbedringer til markdown-strip, chunking, fejlbeskeder

**Agent-laget (V5) — MVP bygget i `v1.18.0`:**
- Spec godkendt af Anders 10/7. `rig_status` (read) + `note_append` (write,
  append-only, én mappe). Bekræftelsesport håndhævet i workeren, append-only
  audit-log, kill switch. **Slået FRA som standard** (`KALIV_TOOLS_ENABLED=1`).
  **Fra v1.28.0 er kill switch-beslutningen persistent** (`kaliv-tools-state.json`,
  sti via `KALIV_TOOLS_STATE`). Env-varen er kun *første-kørsel*-default: slår du
  laget fra i appen, forbliver det slået fra efter en genstart, selv med
  `KALIV_TOOLS_ENABLED=1` i env. Slet statefilen for at nulstille.
- 27 tests grønne, inkl. T7/T8 (prompt injection). Kører nu i CI.
- **v1.19.0:** modellen kan foreslå tools (`POST /tools/chat`), og Go-serveren
  proxy'er hele laget.
- **v1.20.0:** cloud må foreslå tools (Anders' beslutning). Reglen: **risiko
  afgør, ikke oprindelse** — se `tools.requires_confirmation()`. Skrivning
  kræver kortet uanset hvem der foreslog; læsning kører frit. Cloud-nøglen
  parkeres aldrig med en ventende handling; appen gensender den med
  beslutningen.
- **v1.21.0: bekræftelseskortet er i appen.** ⋮-menu → "🛠 Tools" slår
  tools-tilstand til (fra som standard; riggens `KALIV_TOOLS_ENABLED` er den
  anden lås). Et skrivende forslag parkerer som et kort over inputfeltet —
  intet er udført mens det står der. Afvis og Godkend er lige store.
- **v1.22.0:** tools virker også i cloud-tilstand — men kun ved at rute
  cloud-modellen GENNEM riggen (`/tools/chat` med `cloud_key`), for det er dér
  gaten bor. Appens direkte `CloudClient`-vej har slet ingen tools: intet at
  omgå, for der er ingen dør på den vej. Kortet siger "Cloud-modellen
  foreslår:", og `origin` står på audit-rækken.
- **v1.23.0: handlingsloggen kan læses** (⋮ → Handlingslog). Viser de sidste
  50 rækker fra `/tools/audit`, farvet efter udfald, ☁ for cloud-oprindelse.
  Read-only — appen kan ikke ændre eller rydde loggen.
- ⚠️ **Ikke on-device-testet.** Kort + log er compile-verificeret, ikke prøvet
  på Pixel'en. Kræver `KALIV_TOOLS_ENABLED=1` på riggen.
- ⚠️ **Betingelsen står ved magt:** vilkårlige filstier eller 3.-parts
  MCP-servere kræver separat Windows-konto + ACL'er FØRST (kravspec §5b).

**Testdækning (10/7):** worker 236 tests (unit 52 · rag 48 · tools 119 · backup 17) +
Go `internal/httpapi` 4 tests. CI kører nu `go vet` og `go test ./...` —
det gjorde den ikke før v1.23.1, så Go-koden var reelt utestet.

**Light/dark (v1.32.0):** Manuel toggle i ⋮-menuen, gemt i TokenStore (`dark_mode`,
default true). Paletten er nu `KalivTheme.colors.X` (CompositionLocal), ikke
globale `val`'er. **Platform-grænse:** launcher-ikonet og OS-splashens første
frame følger *systemets* tema (via `-night`-ressourcer), IKKE in-app-toggle'en —
OS'et vælger dem før app-processen kører. Toggle'en styrer alt Compose tegner.

**Diagnose først (v1.31.0):** `GET /api/v1/health/full` (eller `/health/full`
på workeren direkte) giver én samlet status — worker, Ollama, ASR+device, TTS,
tools-kill-switch, disk — hver med grund. `?deep=true` tester også en embedding.
Kig her FØRST når en device-test driller, før du gætter på hvilken del der fejler.

**Kræver Anders' test:**
- Tap-to-stop + Kaliv-navnerebrand (bygges som v1.13.0)
- Barge-in-kalibrering (rmsThreshold)
- De resterende tests i §4

**Kræver Anders' beslutning:**
- **Wake word** ("Hey Kaliv") — openwakeword, valgfri mode
- *(v1.14.0 tilføjede PPTX- og HTML-ingest. PPTX kræver `pip install python-pptx`
  på riggen; HTML kræver intet — stdlib.)*
- **Agent-tools** — modellen kalder værktøjer via rig'en. Kræver en gennemtænkt
  sikkerhedsmodel (hvad må kaldes, bekræftelse, prompt injection). Størst
  usikkerhed i hele roadmappen.
- **OCR** til scannede PDF'er (i dag: ærlig 422 "no extractable text")

---

## 11. Licenser at kende

- `faster-whisper` — MIT ✅
- `piper-tts` — **GPL-3.0** (aktiv `OHF-Voice/piper1-gpl`; gl. `rhasspy/piper`
  arkiveret okt-2025). Fint privat; tjek ved deling.
- `PyMuPDF` — AGPL/kommerciel
- Parakeet (dansk ASR, ikke brugt) — NVIDIA Open Model License + tung NeMo
