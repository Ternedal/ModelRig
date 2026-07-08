# Alva / ModelRig — testguide (verifikation af ubekræftede features)

**Dato:** 2026-07-08
**Aktuel version:** v1.6.0
**Formål:** Ét sted at bekræfte alt det, der er bygget men endnu ikke on-device-testet.

Denne session shippede meget (fra v1.5.1 til v1.6.0 alene: hele Alva Voice).
Noget er hardware-bevist, noget er kun compile-verificeret. Denne guide skiller
de to ad og giver præcise trin + beståelseskriterier for resten.

---

## Verifikationsstatus lige nu

| Feature | Version | Status |
|---|---|---|
| Alva-ikon + navn | 1.2.1 | ✅ on-device-bekræftet |
| TTS (Piper dansk) | 1.5.1 | ✅ on-device-bekræftet |
| ASR (faster-whisper dansk) | 1.5.1 | ✅ on-device-bekræftet |
| Fuld Voice-pipeline på rig (ASR→LLM→TTS) | 1.5.1 | ✅ on-device-bekræftet |
| **Alva Voice på Android (push-to-talk)** | 1.6.0 | ⬜ **kun kompileret** |
| Vision (billede → vision-model) | 1.1.0 | ⬜ kun kompileret |
| Local→cloud-fallback | 1.0.3 | ⬜ ikke bekræftet |
| Desktop samtale-panel (søg/omdøb/kopiér) | 1.0.1 | ⬜ ikke bekræftet |
| Desktop soft-lock-fix | 0.20.13 | ⬜ delvist set |

**Fem ting mangler test.** Prioritetsrækkefølge nederst.

---

## Test 1 — Alva Voice på Android (den vigtigste, nyeste)

**Hvad det beviser:** hele telefon→rig→telefon-stemmekæden i selve appen.

**Forudsætninger på rig'en** (alt gjort 8/7 undtagen tjek Ollama):
- `faster-whisper`, `piper-tts`, `soundfile` installeret ✅
- Dansk Piper-stemme hentet ✅
- Ollama kører med en **god** model — brug `hermes3:8b`, IKKE `llama3.2:1b`
  (1b gav vrøvl-svar; det er modellen, ikke Voice)
- Rig-serveren (`modelrig-server-windows-x64.exe`) kører og telefonen er paret

**Trin:**
1. Installér `modelrig-v1.6.0.apk` på telefonen (installerer henover — samme
   signatur).
2. Åbn Alva, vær i **rig-mode** (ikke cloud — Voice kræver rig'en).
3. Der er nu en **🎙-knap** i input-baren. Tryk på den.
   - Første gang: Android spørger om mikrofon-adgang → tillad.
4. Knappen bliver til ⏺ og status siger "Optager…". Sig en dansk sætning.
5. Tryk igen for at sende. Status: "Alva lytter og svarer…".
6. Efter et øjeblik: din transskription + Alvas svar vises som chat, og **svaret
   afspilles som tale**.

**Beståelseskriterier:**
- ✅ Mikrofon-optagelse virker (ingen crash ved tryk)
- ✅ Din tale transskriberes nogenlunde korrekt
- ✅ Alva svarer fornuftigt (med hermes3:8b)
- ✅ Svaret høres som dansk tale

**Sandsynlige problemer (utestet lyd-lag):** afspilning kan være for hurtig/for
langsom (sample rate-mismatch), optagelsen kan være for stille, eller
AudioTrack kan opføre sig OEM-specifikt. **Send fejlbesked / beskrivelse, så
retter jeg.** Dette er den mest sandsynlige kandidat til at kræve justering.

---

## Test 2 — Vision (billede → vision-model)

**Hvad det beviser:** 📎-billede sendes til en multimodal model (1.1.0).

**Forudsætninger:** en vision-model på rig'en, fx:
```
ollama pull llama3.2-vision
```
(eller en anden multimodal model du foretrækker)

**Trin:**
1. I appen: vælg vision-modellen (rig eller cloud, IKKE RAG-mode).
2. Tryk 📎, vælg et billede.
3. Skriv fx "Hvad er på billedet?" og send.

**Beståelseskriterie:** modellen beskriver billedets indhold. Fejler den med en
model-fejl, mangler du en vision-model (ikke en app-bug).

---

## Test 3 — Local→cloud-fallback

**Hvad det beviser:** hvis rig'en er nede, falder appen tilbage til cloud (1.0.3).

**Forudsætninger:** cloud er konfigureret (det er den — `kimi-k2.6` sås i din
opsætning).

**Trin:**
1. Vær i rig-mode med en fungerende samtale.
2. **Sluk rig-serveren** (luk exe'en) — eller sæt en forkert server-URL via
   multi-rig-chippen.
3. Send en besked.

**Beståelseskriterie:** beskeden besvares via cloud med en markering om at den
faldt tilbage — i stedet for bare at fejle. (Retry-stien er en svær-at-trigge
kant; hovedsagen er at et normalt send falder tilbage.)

---

## Test 4 — Desktop samtale-panel

**Hvad det beviser:** søg/omdøb/kopiér i desktop-klienten (1.0.1).

**Forudsætninger:** kør `ModelRig-windows-x64-1.6.0.jar` (kræver Java).

**Trin:**
1. Åbn samtale-panelet.
2. **Søgefelt:** skriv noget → listen filtreres på titler.
3. **✎ omdøb:** omdøb en samtale → titlen ændres.
4. **Kopiér:** kopiér en samtale → markdown ligger i udklipsholderen (prøv at
   indsætte i Notepad).

**Beståelseskriterie:** alle tre virker.

---

## Test 5 — Desktop soft-lock-fix

**Hvad det beviser:** indstillingskortet vokser ikke ud over vinduet (0.20.13).

**Trin:**
1. Åbn desktop-klienten, gå til indstillinger.
2. Tjek at indstillingskortet holder sig inden for vinduet, og at luk-knappen
   er nåbar uden at kortet "låser" layoutet.

**Beståelseskriterie:** ingen soft-lock; luk-knap altid nåbar.

---

## Prioritering (hvis du kun når nogle)

1. **Test 1 (Android Voice)** — nyeste, mest ubeviste, størst værdi. Mest
   sandsynligt at kræve en fix-runde.
2. **Test 4 + 5 (desktop)** — hurtige, kræver kun at åbne jar'en.
3. **Test 2 (vision)** — kræver kun at hente en vision-model.
4. **Test 3 (fallback)** — kræver at slukke rig'en midlertidigt.

Rapportér resultater tilbage — især fejlbeskeder fra Test 1 — så retter jeg.

---

## Stående punkter (kræver dine beslutninger, ikke test)

Disse kan ikke bygges videre uden input fra dig:

- **Barge-in for Voice:** skal Alva kunne afbrydes mens den taler? Kræver
  headset-først-beslutning (akustisk ekko-håndtering på højttaler er svært).
- **Wake word ("Hey Alva"):** valgfri mode, senere. Kræver openwakeword-integration.
- **Agent-tools:** modellen kalder værktøjer via rig'en. Kræver en gennemtænkt
  sikkerhedsmodel (hvad må kaldes, bekræftelse, prompt injection) — størst
  usikkerhed i hele roadmappen.
- **PDF-ingest til RAG:** kræver dit bibliotek-valg (PyMuPDF vs pypdf).

---

## ⚠️ Sikkerhed — gør dette nu

**GitHub PAT'en er stadig aktiv.** Den er brugt til alle dagens releases
(inkl. 1.6.0). Den bør revokeres nu hvor der er et naturligt stop:
`github.com/settings/tokens` → find token'en → Revoke.
