# Alva Voice — roadmap-delta og kvalitetssikring

> **⚠️ HISTORISK DOKUMENT (8/7).** Dette var dagens test-/plan-dokument og er
> bevaret som optegnelse. Det AKTUELLE testgrundlag er **DEVICE_TEST.md** (runbook)
> + **TROUBLESHOOTING.md** (symptom→fix) + **STATUS.md** linje 3 (aktuel version).

**Dato:** 2026-07-08
**Forfatter:** Claude (kvalitetssikring af `alva_claude_handoff_2026-07-08`)
**Status:** Til Anders' beslutning. Voice er nu et **prioriteret roadmap-spor**, ikke en løs V3-idé.

Dette dokument kvalitetssikrer Voice I/O-planen fra handoff-pakken mod det
faktiske ModelRig-roadmap og mod verificerbar virkelighed (modeller, licenser,
hardware). Det er bevidst kritisk — planen er god, men har antagelser der skal
korrigeres før implementering.

---

## 1. Konklusion først

Voice-planen er **realistisk i sin struktur** (samlet Voice I/O, push-to-talk
før wake word, sentence-chunking, barge-in som V1-krav) — men **for optimistisk
på tre punkter**, som alle skal afklares før kode skrives:

1. **Modelvalgene er tungere end pakken antyder.** Primær ASR (`parakeet-rnnt-110m-da-dk`) kræver NVIDIA NeMo-toolkitet — en stor, tung afhængighed, ikke en pip-og-kør-model. Verificeret på HuggingFace 8/7.
2. **Licenserne er ikke alle frit delbare.** Parakeet kører under **NVIDIA Open Model License**, ikke Apache/MIT. Brugbar, men ikke "frit open source" hvis du vil dele projektet.
3. **Voice er en ny arkitektur-vertikal, ikke en feature oveni ModelRig.** Den kræver en ny lyd-pipeline-proces på rig'en (mikrofon → VAD → ASR → LLM → TTS → afspilning), som ikke findes i dag. Det er større end alt i V2 tilsammen.

**Anbefaling:** byg en **radikalt smal Voice-MVP** først (push-to-talk + én
ASR + eksisterende LLM-streaming + Piper TTS), bevis latency-kæden på Anders'
RTX 3060, og udvid derfra. Wake word, CoRal-stemme og barge-in-finpudsning er
fase 2+.

---

## 2. Modelverifikation (det pakken bad om)

| Model | Findes? | Licens | Afhængighed | Dom |
|---|---|---|---|---|
| `nvidia/parakeet-rnnt-110m-da-dk` (primær ASR) | ✅ Ja, reel dansk ASR (110M, FastConformer/RNN-T) | ⚠️ **NVIDIA Open Model License** (ikke MIT/Apache) | ⚠️ Kræver **NVIDIA NeMo** (tung) | Brugbar, men tung + licens-forbehold |
| `nvidia/parakeet-tdt-0.6b-v3` (ikke i pakken — mit fund) | ✅ Ja, 25 EU-sprog inkl. dansk (600M) | ✅ **CC-BY-4.0** (friere) | NeMo | **Værd at overveje** som friere-licens-alternativ, hvis størrelsen er OK |
| `faster-whisper` (ASR fallback) | ✅ Ja, velkendt | ✅ MIT | CTranslate2 (let) | Solid, letvægts fallback — måske bedre startpunkt end Parakeet |
| `CoRal-project/roest-v3-chatterbox-350m` (primær TTS) | ⚠️ Skal verificeres on-device | Skal tjekkes | Ukendt runtime | **Ikke bekræftet endnu** — behandl som kandidat |
| Piper `da_DK-talesyntese-medium` (TTS) | ✅ Ja, dansk Piper | ⚠️ **GPL-3.0** (aktiv piper1-gpl; gl. MIT-repo arkiveret okt-2025) | ONNX (let, CPU-only) | **MVP-startpunkt** — let, hurtig, men GPL (fint privat, tjek ved deling) |
| Silero VAD | ✅ Ja | ✅ MIT | let (ONNX/torch) | Godt valg |
| openwakeword (wake word) | ✅ Ja | ✅ Apache | let | Fint — men fase 2, ikke MVP |

**Kritiske licens-flag:**
- **Parakeet = NVIDIA Open Model License.** Læs den før låsning. Den tillader
  kommerciel/ikke-kommerciel brug, men er ikke en klassisk OSS-licens. Hvis
  ModelRig/Alva nogensinde skal deles offentligt, er `parakeet-tdt-0.6b-v3`
  (CC-BY-4.0) eller `faster-whisper` (MIT) friere.
- **CoRal Chatterbox TTS: licens uverificeret.** Må ikke låses som "primær"
  før både runtime OG licens er bekræftet på Anders' maskine.

**Vigtigste tekniske forbehold:** NeMo-baserede modeller (Parakeet) er ikke
lette at pakke som en selvstændig exe, sådan som ModelRig-serveren er i dag.
NeMo trækker PyTorch + en stor afhængighedsflade. Det bryder den nuværende
"download exe, ingen toolchain"-simpelhed for rig-opsætning. **Dette er den
største skjulte omkostning i hele Voice-planen.**

---

## 3. Roadmap-delta: hvad ændrer sig

### Nyt navnehierarki (fra pakken — accepteret)
- **Alva** = appen/oplevelsen (Android-appen er nu rebrandet til Alva, v1.2.0).
- **ModelRig** = backend/motor/runtime (uændret navn — Anders' beslutning).
- Undersystemer: **Alva Voice**, **Alva Memory**, **Alva Tools**, **Alva UI**.

### Hvad der IKKE ændrer sig (allerede leveret, bare omdøbt konceptuelt)
- **Alva Memory** er ikke ny — det er den eksisterende RAG + samtale-persistens
  + presets, der allerede er bygget og on-device-bekræftet. Ingen ny kode
  kræves for at "starte" Memory; den findes.
- **Alva UI** er den eksisterende Android/desktop-oplevelse. Rebranded, ikke
  genopbygget.
- **ModelRig Core** er den eksisterende Go-backend + worker + Ollama-routing.

### Hvad der er genuint NYT (og stort)
- **Alva Voice** — hele lyd-pipelinen findes ikke i dag. Dette er 90% af
  handoff-pakkens reelle arbejde.
- **Alva Tools** — agent/handlingsudførelse. Kræver stadig sikkerhedsmodellen
  (samme åbne spørgsmål som altid: hvad må kaldes, bekræftelse, prompt
  injection). Uændret fra tidligere V3-diskussion.

### Gamle roadmap-dele der skal markeres superseded
- Eventuelle løse "ASR"- eller "TTS"-punkter i det gamle roadmap er nu
  **absorberet i Alva Voice** som ét samlet spor. De må ikke implementeres
  isoleret (pakkens kerneprincip, som jeg er enig i — isoleret ASR uden
  end-of-speech/VAD er ubrugelig i praksis).

---

## 4. Revideret Voice-MVP (smallere end pakkens)

Pakken foreslår allerede en fornuftig MVP. Jeg skærer den **yderligere** ned,
fordi den tungeste del (Parakeet+NeMo) ikke bør være i det første kørende bevis:

```
Alva Voice MVP (bevis latency-kæden, mindst mulig ny afhængighed):

  Push-to-talk (hold knap)         [Android — ingen wake word endnu]
        ↓
  Mikrofon-capture (16kHz mono)    [Android AudioRecord]
        ↓
  Silero VAD (end-of-speech)       [let, MIT]
        ↓
  ASR: faster-whisper dansk        [MIT, let — IKKE Parakeet/NeMo endnu]
        ↓
  LLM: eksisterende Ollama-streaming  [GENBRUG — findes allerede!]
        ↓
  Sentence-chunking                [split på . ! ? for time-to-first-audio]
        ↓
  TTS: Piper da_DK medium          [fri, let, ONNX]
        ↓
  Audio queue + afspilning         [Android AudioTrack]
        ↓
  Barge-in (afbryd ved ny tale)    [VAD lytter mens Alva taler]
```

**Hvorfor faster-whisper før Parakeet i MVP:** MIT-licens, ingen NeMo, kører
let. Beviser hele kæden uden den tungeste afhængighed. Parakeet (bedre dansk
kvalitet) kommer i fase 2, når kæden virker og latency er målt — så er det et
isoleret modelbytte, ikke en del af det risikable første forsøg.

**Kritisk MVP-metrik (fra pakken — enig):** *time-to-first-audio*. Alva skal
begynde at tale efter første taleegnede sætnings-chunk, ikke vente på hele
LLM-svaret. Dette er den ene metrik der afgør om det føles som en assistent
eller en formular.

---

## 5. Milepæle med acceptkriterier

**V-MVP.1 — Optag → tekst (ASR alene)**
- Accept: hold knap, tal dansk, slip → korrekt dansk transskription vises.
  VAD trimmer stilhed i begge ender. Kører på rig'ens RTX 3060 uden OOM.

**V-MVP.2 — Tekst → tale (TTS alene)**
- Accept: given en dansk streng → Piper afspiller forståelig dansk tale på
  telefonen. Sætnings-chunking bekræftet (flere sætninger → flere audio-chunks).

**V-MVP.3 — Fuld kæde uden barge-in**
- Accept: tal → Alva transskriberer → eksisterende LLM svarer → svaret læses
  op, og **første lyd starter før hele svaret er genereret** (time-to-first-audio
  målt og < ~2s efter LLM's første sætning).

**V-MVP.4 — Barge-in**
- Accept: mens Alva taler, kan brugeren begynde at tale → Alva stopper
  afspilning øjeblikkeligt og lytter. Ingen overlap, ingen hængende audio.

**V2 — Bedre stemme + wake word (efter MVP)**
- CoRal Chatterbox som primær stemme (hvis licens+runtime bekræftet).
- Parakeet som primær ASR (bedre dansk WER).
- "Hey Alva" wake word (openwakeword) som *valgfri* mode.
- Latency-benchmark-suite.

---

## 6. Risici og åbne afklaringer

1. **NeMo-afhængigheden bryder exe-simpliciteten.** Hvis Parakeet skal være
   primær, kan rig'en ikke længere køres som en selvstændig exe uden Python.
   **Afklaring:** accepterer Anders en tungere rig-opsætning for Voice, eller
   skal Voice-ASR holdes på faster-whisper for at bevare exe-modellen?
2. **RTX 3060 12GB VRAM-budget.** Kører ASR + LLM + TTS samtidig i VRAM?
   qwen2.5-coder:7b bruger ~5GB, nomic ~0.3GB. Parakeet + Piper oveni skal
   måles. **Afklaring:** kræver on-device VRAM-test før løfter gives.
3. **Android mikrofon-permission + baggrundslyd.** RECORD_AUDIO + real-time
   capture på tværs af OEM'er. **Kan kun testes på Anders' faktiske telefon.**
4. **Barge-in er teknisk svært.** At lytte mens man afspiller kræver akustisk
   ekko-håndtering (ellers hører Alva sig selv). **Afklaring:** headset-først i
   MVP, højttaler-barge-in senere?
5. **Licens-låsning.** Parakeet (NVIDIA OML) og CoRal (uverificeret) må ikke
   låses før licens er læst. faster-whisper + Piper er begge frie — sikre
   MVP-valg.

---

## 7. Implementeringsrækkefølge (konkret)

1. **Nu (færdigt):** Alva-rebrand af Android-appen (v1.2.0). ✅
2. **Beslutninger fra Anders** (før kode): NeMo-afhængighed ja/nej (risiko #1),
   headset-først ja/nej (risiko #4), licens-accept for Parakeet (risiko #5).
3. **Voice-MVP fase 1:** V-MVP.1 (ASR) som et isoleret Python-modul på rig'en,
   testet med faster-whisper mod en dansk lydfil — før noget Android-arbejde.
   Beviser ASR-kvalitet uden UI-kompleksitet.
4. **Voice-MVP fase 2:** V-MVP.2 (Piper TTS) isoleret på rig'en.
5. **Voice-MVP fase 3:** kobl ASR→LLM→TTS på rig'en (stadig ingen telefon) —
   bevis time-to-first-audio i terminalen.
6. **Voice-MVP fase 4:** Android-lag (push-to-talk, capture, afspilning) oven
   på den beviste rig-pipeline. **Her, og først her, testes på telefonen.**
7. **Barge-in** som sidste MVP-brik.
8. **Fase 2-modeller** (Parakeet, CoRal, wake word) som isolerede bytter.

Dette følger projektets hårdt tillærte princip: **byg og bevis motoren først,
UI-laget sidst, on-device-test ved hver flade.** Voice er præcis den slags
hardware-afhængige system hvor "compile-verificeret" intet betyder — hvert lag
skal bevises på rigtig hardware før det næste bygges oven på.

---

## 8. Hvad jeg IKKE gjorde (ærlighed)

- Jeg **byggede ikke** noget Voice-kode. Det ville være spekulativt uden
  Anders' svar på risiko #1, #4 og #5, og uden en RTX 3060 at måle på.
- Jeg **verificerede ikke** CoRal Chatterbox' runtime/licens (kun ASR nåede
  jeg at slå op). Det skal gøres før TTS-fase 2.
- Jeg **låste ingen modelvalg.** Alle er kandidater, præcis som pakken beder om.
- Voice-benchmark-tallene i `VOICE_IO_SPEC.md` (latency-budgetter) er
  **designmål, ikke målte tal.** De skal verificeres på hardware.
