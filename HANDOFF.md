# ModelRig / Alva — handoff til ny chat

**Dato:** 2026-07-09 · **Version:** v1.12.1 · **Repo:** `github.com/Ternedal/ModelRig` (privat)

Copy/paste dette som første besked i en ny chat.

---

## 0. Læs først: hvad der er akut

1. **⚠️ GitHub PAT'en er stadig aktiv** og er brugt til ~15 releases i dag.
   Revokér den: `github.com/settings/tokens`. Dette er højeste prioritet.
2. **Der er en åben fejl** (se §5): worker'en returnerer 501 på voice, men
   ASR-modellen loader fint isoleret. Næste skridt er at teste TTS isoleret.
3. **Anders har flere kopier af repoet** (`modelrig`, `modelrig-new`,
   `modelrig-mono`) med forskellig kode-alder. Det har forårsaget flere falske
   fejlspor. Ryd op: behold én mappe.

---

## 1. Hvad projektet er

**ModelRig** er en selvhostet LLM-platform. **Alva** er Android-appen (samme
kodebase; motoren hedder stadig ModelRig).

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

## 3. Hvad der VIRKER (hardware-bekræftet)

| Feature | Bevist |
|---|---|
| Alva-ikon + navn | ✅ i launcheren |
| PDF-ingest → RAG | ✅ svarede grounded om PDF-indhold |
| DOCX-ingest → RAG | ✅ inkl. tabel-indhold |
| TTS (Piper dansk) | ✅ forståelig dansk tale |
| ASR (faster-whisper dansk) | ✅ høj kvalitet |
| **Voice ende-til-ende på telefonen** | ✅ tale → ASR → LLM → TTS → afspilning |
| **Hybrid voice (cloud-LLM)** | ✅ kimi-k2.6 svarede på tale |
| Markdown strippes fra tale | ✅ læser ikke "stjerne" op |
| Local→cloud-fallback | ✅ set utilsigtet |
| **CUDA / GPU-ASR** | ✅ `large-v3` loader på 3060 (verificeret isoleret 9/7) |

## 4. Hvad der IKKE er testet

- **Barge-in** (v1.12.0) — kompileret, aldrig prøvet. `rmsThreshold = 1500.0`
  er et gæt der skal kalibreres. **Prøv headset først** (intet ekko).
- **Model-chip på stemme-svar** (v1.11.0) — `◈ 🎙 hermes3:8b` / `☁ 🎙 kimi-k2.6`
- **PDF/DOCX-upload fra telefonen** (kun testet på rig'en)
- **Vision** (v1.1.0) — kræver `ollama pull llama3.2-vision`
- **Desktop**: samtale-panel (søg/omdøb/kopiér) + soft-lock-fix

---

## 5. ÅBEN FEJL — det næste skridt

**Symptom:** `POST /voice/converse/upload` → `501 Not Implemented` i
worker-loggen. Appen viser "Stemme-fejl: Software caused connection abort".

**Hvad vi ved:**
- ASR loader fint isoleret: `device: cuda, model: large-v3, MODEL LOADED OK`
- Så 501'eren handler **ikke** om ASR-device
- 501 returneres når **enten ASR eller TTS** ikke er tilgængelig
- Konklusion: mistanken er nu **TTS (piper)** eller pipelinen

**Næste kommando at køre** (fra repo-mappen):
```cmd
python -c "import sys; sys.path.insert(0,'worker'); from app import voice_tts; print('TTS available:', voice_tts.is_available()); voice_tts._get_voice(); print('TTS VOICE LOADED OK')"
```

**Sandsynlige årsager:**
- Den danske stemme ligger i `~\.alva\piper-voices`, men `ALVA_TTS_VOICES_DIR`
  peger et andet sted
- `piper-tts` installeret i en anden Python end den worker'en kører i
- Anders kørte fra en mappe med gammel kode (det har sket to gange i dag)

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

**Kræver Anders' test:**
- Barge-in-kalibrering (rmsThreshold)
- De resterende tests i §4

**Kræver Anders' beslutning:**
- **Wake word** ("Hey Alva") — openwakeword, valgfri mode
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
