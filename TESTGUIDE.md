# Alva / ModelRig — trin-for-trin testguide

> **⚠️ HISTORISK DOKUMENT (9/7).** Dette var dagens test-/plan-dokument og er
> bevaret som optegnelse. Det AKTUELLE testgrundlag er **DEVICE_TEST.md** (runbook)
> + **TROUBLESHOOTING.md** (symptom→fix) + **STATUS.md** linje 3 (aktuel version).

**Version:** v1.8.0 · **Dato:** 2026-07-09

Syv ting er bygget men ikke bekræftet på din hardware. Denne guide tager dem i
den rækkefølge der giver mest svar for mindst besvær.

**Sådan bruger du den:** følg trinnene i rækkefølge. Hver test har et klart
✅-kriterie. Noter hvad der fejler — særligt fejlbeskeder — og rapportér tilbage.

---

## Trin 0 — Opsætning (gør dette først, ~10 min)

### 0.1 Installér de valgfrie rig-pakker

På rig'en (Windows), i en terminal:

```cmd
pip install faster-whisper piper-tts soundfile pymupdf python-docx
```

(`faster-whisper`, `piper-tts` og `soundfile` har du allerede fra i går —
`pymupdf` og `python-docx` er nye.)

### 0.2 Bekræft den danske stemme er hentet

```cmd
dir "%USERPROFILE%\.alva\piper-voices"
```

✅ Du skal se `da_DK-talesyntese-medium.onnx`. Hvis ikke:

```cmd
cd /d "%USERPROFILE%\.alva\piper-voices"
python -m piper.download_voices da_DK-talesyntese-medium
```

### 0.3 Start Ollama med en GOD model

```cmd
ollama serve
```

I en anden terminal, bekræft du har `hermes3:8b`:

```cmd
ollama list
```

> ⚠️ **Brug `hermes3:8b`, ikke `llama3.2:1b`.** 1b-modellen gav vrøvl-svar i går
> ("PersonerwithDisability") — det er modellen, ikke Voice.

### 0.4 Start rig-serveren

Download og kør `modelrig-server-windows-x64.exe` fra v1.8.0-releasen:
`github.com/Ternedal/ModelRig/releases/tag/v1.8.0`

### 0.5 Verificér at rig'en har alt (hurtigt sundhedstjek)

Med serveren kørende:

```cmd
curl http://localhost:8099/voice/asr/status
curl http://localhost:8099/rag/ingest/pdf/status
curl http://localhost:8099/rag/ingest/docx/status
```

✅ Alle tre skal svare `{"available":true}`. Siger en `false`, mangler den pakke
(se 0.1).

### 0.6 Installér Alva v1.8.0 på telefonen

Hent `modelrig-v1.8.0.apk` fra samme release. Den installerer henover den gamle
(samme signatur). Telefonen skal være på samme netværk som rig'en og være paret.

---

## Test 1 — PDF-ingest på rig'en (nemmest, beviser mest med det samme)

**Hvorfor først:** ingen telefon, ingen lyd — bare én kommando. Beviser hele
PDF→RAG-kæden.

```cmd
cd /d "%USERPROFILE%\Desktop\modelrig"
python tools\rag_pdf_test.py
```

Laver en dansk test-PDF, udtrækker teksten, ingesterer den, og spørger
"Hvilken GPU har rig-maskinen?"

✅ **Består hvis:** svaret nævner **RTX 3060**.
❌ **Fejler typisk med:** worker ikke kørende (`:8099`) eller Ollama nede.

---

## Test 2 — DOCX-ingest på rig'en (ét minut mere)

```cmd
python tools\rag_docx_test.py
```

Laver en dansk .docx med afsnit **og en tabel**, ingesterer, og spørger om
GPU'en — som kun står i **tabellen**.

✅ **Består hvis:** svaret nævner RTX 3060 (beviser at tabel-indhold er søgbart).

---

## Test 3 — Alva Voice på telefonen ⭐ (den vigtigste)

**Hvorfor:** hele stemme-kæden telefon→rig→telefon. Rig-siden er bevist; dette
er det utestede lyd-lag på Android.

**Trin:**

1. Åbn Alva. Vær i **rig-mode** (ikke cloud — Voice kræver rig'en).
2. Vælg **`hermes3:8b`** som model.
3. Find **🎙-knappen** i input-baren (til venstre for tekstfeltet).
4. Tryk. Første gang: **tillad mikrofon-adgang**.
5. Knappen bliver ⏺ og der står "Optager…". **Sig en dansk sætning**, fx
   *"Hej Alva, hvad kan du hjælpe med?"*
6. Tryk igen for at sende. Der står "Alva lytter og svarer…".
7. Vent. Din transskription + Alvas svar dukker op som chat-beskeder, og
   **svaret afspilles som tale**.

✅ **Består hvis:** alle fire dele virker — optagelse, transskription, fornuftigt
svar, hørbar dansk tale.

⚠️ **Mest sandsynlige problemer** (lyd-laget har aldrig kørt på en telefon):

- **Afspilning lyder for hurtig/langsom/forvrænget** → sample rate-mismatch
- **"ingen lyd optaget"** → mikrofon-buffer-problem
- **Crash ved tryk** → AudioRecord-initialisering
- **Timeout** → rig'en er langsom (hermes3 + ASR + TTS tager tid første gang)

**Rapportér:** præcis hvad der skete + evt. fejlbesked. Så retter jeg.

---

## Test 4 — PDF/DOCX-upload fra telefonen

**Trin:**

1. I appen: slå **RAG-mode** til.
2. Åbn kilde-menuen → vælg tilføj dokument.
3. Vælg en **PDF** fra telefonen. Vent på "Ingesteret: … (N chunks)".
4. Gentag med en **.docx**.
5. Stil et spørgsmål om indholdet.

✅ **Består hvis:** begge filtyper ingesteres, og svaret er grounded i
dokumentet (med kilde-chip).

⚠️ Fejler en scannet PDF med "no extractable text" er **det korrekt opførsel**
(ingen OCR endnu), ikke en bug.

---

## Test 5 — Vision (billede → vision-model)

**Forudsætning:**

```cmd
ollama pull llama3.2-vision
```

**Trin:**

1. Vælg vision-modellen i appen (rig-mode, **RAG slået fra**).
2. Tryk **📎**, vælg et billede.
3. Skriv "Hvad er på billedet?" og send.

✅ **Består hvis:** modellen beskriver billedet.
❌ Fejler den med en model-fejl → du mangler vision-modellen (ikke en app-bug).

---

## Test 6 — Local→cloud-fallback

**Trin:**

1. Vær i rig-mode med en fungerende samtale.
2. **Luk rig-serverens exe.**
3. Send en besked.

✅ **Består hvis:** beskeden besvares via cloud med en fallback-markering — i
stedet for bare at fejle.

Start serveren igen bagefter.

---

## Test 7 + 8 — Desktop (kræver kun Java)

Kør `ModelRig-windows-x64-1.8.0.jar` fra releasen.

**Test 7 — samtale-panel:**

1. Åbn samtale-panelet.
2. **Søg:** skriv i søgefeltet → listen filtreres.
3. **Omdøb:** tryk ✎ → skift titel.
4. **Kopiér:** tryk kopiér → indsæt i Notepad (skal være markdown).

✅ Består hvis alle tre virker.

**Test 8 — soft-lock:**

1. Åbn indstillinger i desktop-klienten.

✅ Består hvis indstillingskortet holder sig inden for vinduet og luk-knappen
altid er nåbar.

---

## Rækkefølge og tidsforbrug

| # | Test | Tid | Kræver |
|---|------|-----|--------|
| 0 | Opsætning | 10 min | rig |
| 1 | PDF-ingest (rig) | 2 min | rig |
| 2 | DOCX-ingest (rig) | 1 min | rig |
| 3 | **Voice på telefon** ⭐ | 5 min | rig + telefon |
| 4 | PDF/DOCX fra telefon | 5 min | rig + telefon |
| 5 | Vision | 5 min | vision-model |
| 6 | Cloud-fallback | 2 min | telefon |
| 7-8 | Desktop | 5 min | Java |

**Hvis du kun når tre:** Test 1, 2 og 3. De to første er næsten gratis, og den
tredje er den mest ubeviste og mest værdifulde.

---

## Hvad jeg forventer fejler

Ærlig forudsigelse, så du ikke bliver overrasket:

1. **Test 3 (Voice på telefon)** — højst sandsynligt kræver justering. Lyd på
   Android er OEM-specifikt, og dette lag har aldrig kørt.
2. **Test 4** — file-pickeren kan opføre sig anderledes på din Android-version.
3. Resten burde virke, men "burde" er ikke "gør".

Alt bygget efter v1.5.1 er compile-verificeret, ikke telefon-testet. Det er
derfor denne guide findes.

---

## ⚠️ Sikkerhed

**GitHub PAT'en er stadig aktiv** og blev brugt til alle otte releases i går
(v1.1.0 → v1.8.0). Revokér den nu:
`github.com/settings/tokens` → find token'en → **Revoke**.
