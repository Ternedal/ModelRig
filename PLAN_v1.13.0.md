# PLAN — v1.13.0 "Tap-to-stop + Kaliv"

**Skrevet:** 2026-07-09 sen aften, efter GPU-voice virkede
**Status:** worker-delen ER lavet (se §2). Android-delen udestår (§3).
**Læs først:** `HANDOFF.md` §0 og §7 (lektierne). `ROADMAP.md` §14 (invarianter).

---

## 0. Rækkefølge i morgen

| # | Opgave | Hvem | Tid |
|---|--------|------|-----|
| 1 | Kold-start-test af v1.12.3 (uden PATH-linjer) | Anders | 2 min |
| 2 | V2-lukketjek: 3 features on-device | Anders | 10 min |
| 3 | Android: tap-to-stop + Kaliv-navn | Claude | 1 session |
| 4 | Byg, compile-verificér, tag v1.13.0 | Claude | — |
| 5 | On-device-test af stop-knappen | Anders | 5 min |
| 6 | Barge-in-kalibrering med headset | Anders | 10 min |

**Punkt 1 og 2 kan køre før alt andet og kræver ingen ny kode.** De lukker
to åbne spørgsmål: virker PATH-fixet ved normal start, og er V2 reelt færdig.

---

## 1. Kold-start-test (punkt 1) — eksakt

Formålet er at bevise at `_add_cuda_dll_dirs()`s PATH-prepend virker uden
manuelle env-linjer. Kun den MANUELLE test er hardware-bevist i dag.

```cmd
:: Hent v1.12.3-zip fra GitHub Releases, pak ud som Desktop\ModelRig

:: Vindue 1
ollama serve

:: Vindue 2 — INGEN set PATH-linje. Det er hele pointen.
cd /d "%USERPROFILE%\Desktop\ModelRig"
set PYTHONPATH=%CD%\worker
python -m uvicorn app.main:app --host 127.0.0.1 --port 8099

:: Vindue 3
cd /d "%USERPROFILE%\Desktop"
set MODELRIG_HOST=0.0.0.0
modelrig-server-windows-x64.exe
```

Tjek `curl -s http://127.0.0.1:8099/healthz` → skal sige `1.12.3`.
Tal én sætning fra telefonen.

- **Svarer hun:** PATH-fixet er bevist. Luk §5 i HANDOFF endeligt.
- **Fejler den:** send fejlen fra vindue 2. Næste kandidat er at preloade
  DLL'erne med `ctypes.WinDLL` før CTranslate2 rører dem.

## 1b. V2-lukketjek (punkt 2)

Tre features er compile-verificerede, aldrig rørt på telefonen:

1. **Filvælger-ingest:** vedhæft en `.txt`/`.md`, stil et spørgsmål der
   kun kan besvares fra filen. RAG-chip skal vise kilden.
2. **Model-administration:** pull `llama3.2:1b` fra appen (progress?),
   se den i listen, slet den igen.
3. **Samtale:** omdøb en samtale → søg på det nye navn → del som markdown.

Alle tre grønne = V2 lukkes med dato i `ROADMAP.md` §4.

---

## 2. Worker — GJORT i aften (skal ikke laves om)

`worker/app/env_compat.py` (ny): `env(suffix, default)` læser `KALIV_<X>`,
falder tilbage til `ALVA_<X>`, ellers default. `legacy_names_in_use()`
rapporterer gamle navne der stadig er i brug.

Koblet ind i `voice_asr.py` (3 kald) og `voice_tts.py` (2 kald).
`_voices_dir()` defaulter nu til `~/.kaliv/piper-voices`, men **bruger
`~/.alva/piper-voices` hvis den findes og den nye ikke gør** — Anders'
stemmefiler ligger i den gamle, og en hård omdøbning ville brække en
fungerende rig uden gevinst.

`/voice/asr/status` og `/voice/tts/status` returnerer nu `legacy_env` med
de gamle navne der stadig bruges, så migrationen er synlig i stedet for
tavs. 63/63 tests grønne (6 nye dækker precedence, fallback, tom streng).

**Ikke ændret:** `MODELRIG_*` hører til motoren og omdøbes ALDRIG.

---

## 3. Android — udestår (næste session)

**Hvorfor ikke i aften:** Kotlin skal compile-verificeres før tag. Lektie 5
i HANDOFF: kode der kun *ser* rigtig ud, er ikke verificeret. At skubbe
utestet UI-kode kl. 00:30 er præcis den fejl dokumentet advarer mod.

### 3a. Tap-to-stop (den egentlige bug)

**Problem, som Anders fandt on-device 9/7:** mens Kaliv taler, findes der
ingen manuel afbrydelse. Eneste vej ud er barge-in, som er ukalibreret.

**Kilder:**
- `android/.../voice/VoicePlayer.kt` — ejer `AudioTrack`
- `android/.../ui/AppUi.kt` — mic-knap og input-bar
- `android/.../voice/VoiceController.kt` — tilstandsmaskinen

**Design (bevidst minimalt):**
1. `VoicePlayer` eksponerer allerede stop-vejen som barge-in bruger —
   genbrug den. Ingen ny afspilningslogik.
2. Mens tilstanden er `Speaking`, skifter mic-knappen ikon til ⏹ og
   kalder samme stop.
3. Stop skal: standse `AudioTrack`, tømme kø af ventende sætninger, og
   annullere den kørende streaming-request (ellers fortsætter workeren
   med at syntetisere sætninger ind i en lukket kø).

**Punkt 3 er det der let bliver glemt.** Verificér at requesten faktisk
annulleres — ikke bare at lyden holder op.

**Acceptkriterie:** tryk under tale → stilhed inden for ~200 ms, appen er
straks klar til ny tur, worker-loggen viser ingen fortsat syntese.

### 3b. Kaliv-navnerebrand

Kun navn. **Ikonet er LEVERET og shippet i v1.12.4** (9/7 sen aften) —
verificeret: forgrund 38,4 % af kanten, transparent, separat baggrund,
monokrom-lag med i adaptive-icon XML'en.

- `strings.xml`: app-navn, UI-titler
- Persona/system-prompt: "Alva" → "Kaliv"
- README/docs hvor det er brugervendt

**Rør ALDRIG:** `applicationId = dk.ternedal.modelrig` (APK-signaturen),
`ModelRigClient` og andre interne klassenavne, `MODELRIG_*`.

### 3c. Byg og verificér

```bash
cd android && ./gradlew :app:assembleRelease
```
CI bygger APK'en ved tag. Husk **fire** versionssteder — det var fejlen der
fældede første v1.12.3-forsøg:
`worker/app/main.py`, `backend/internal/config/config.go`,
`android/app/build.gradle.kts`, `desktop/composeApp/build.gradle.kts`.

---

## 4. Åbne spørgsmål til Anders

1. Skal ⏹ sidde på mic-knappen (færre elementer) eller som separat knap?
   *Anbefaling: på mic-knappen. Under tale er mic'en alligevel optaget.*
2. Skal `~/.alva/piper-voices` migreres til `~/.kaliv/` på et tidspunkt,
   eller lever fallbacken permanent? *Anbefaling: lad den leve. Den koster
   fire linjer og bryder aldrig noget.*
3. Barge-in: skal ✋ være default-til når stop-knappen findes?
   *Anbefaling: nej. Kalibrér først på headset.*
