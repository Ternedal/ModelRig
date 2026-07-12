# Modelvalg til agent-stien (RTX 3060 12GB)

Formål: erstatte `hermes3:8b` på agent-stien med en model der (1) kalder værktøjer
pålideligt i stedet for at beskrive dem i prosa, og (2) holder dansk bedre. Det
er de to reelle svagheder vi så under test.

## Anbefaling (kort)

1. **`qwen3:14b` — BEKRÆFTET på riggen 12/7.** Kører på 3060'en, og den er
   markant bedre end hermes3: den KENDER sin identitet og sine tools ("Jeg er
   Kaliv... læse riggens status og tilføje noter") — det gjorde hermes3 aldrig.
   Nyeste generation, 119 sprog, Apache 2.0, tool-calling indbygget. **Men den
   er tæt** på 12 GB (vægtene ~8,7 GB ved Q4_K_M), så konteksten er begrænset.
   Kendte svagheder set on-device: dropper bindestreger i dansk tekst
   ("LollandFalster", "150200") og hallucinerer på dansk faktaviden (Mandø i
   "Baltisk hav") — det er MODEL-svagheder, ikke app-bugs; brug cloud til hårde
   faktaspørgsmål. Ignorerer også "ingen emojis"-instruktioner (derfor den
   deterministiske klient-strip, v1.45.0).
2. **Fallback: `qwen3:8b`.** Sikker plads (~6 GB), mere luft til kontekst og
   hastighed. Sandsynligvis bedre instruktionsfølgning end hermes3:8b — men da
   den også er 8B, kan den stadig af og til narre i prosa. Ikke garanteret bedre
   på tool-kald end hermes3, men Qwen's tool-træning er stærkere.
3. **Alternativ: `qwen2.5:14b`.** Lidt ældre, men har **dokumenteret
   out-of-the-box function calling** og er stærk multilingual. Samme plads-hensyn
   som qwen3:14b.

Min konklusion: **14B er det reelle spring** for tool-pålidelighed. Et andet 8B
(qwen3:8b) løser næppe narrations-problemet helt — det er en størrelses­grænse,
ikke kun en model-grænse. Så hvis dansk + pålidelige tool-kald betyder noget, er
`qwen3:14b` det rigtige forsøg, med `qwen3:8b` som fallback hvis 14B er for tungt.

## Pull-kommandoer

```
ollama pull qwen3:14b      # primær kandidat (~8.7 GB Q4, tæt på 12 GB)
ollama pull qwen3:8b       # fallback (~6 GB, mere luft)
ollama pull qwen2.5:14b    # alternativ med bevist function calling
```

## Sådan skifter du model

Modellen vælges i appens model-dropdown (der hvor der står `hermes3:8b ▾`).
Pull modellen på riggen, og den dukker op i listen. Ingen kode-ændring nødvendig
— worker'en sender bare det modelnavn appen vælger videre til Ollama.

Vil du sætte den som standard, så den bruges uden at vælge hver gang: sæt
modelnavnet i appens indstillinger (rig-model-feltet), eller sæt `GEN_MODEL` på
worker'en.

## Vigtig faldgrube: "thinking mode"

Qwen3 har en tænke-tilstand (chain-of-thought). Den kan — ligesom hermes3's
"*Hmm, the human said hej...*" — spilde tokens og potentielt rode med rene
tool-kald. Til agent-brug vil du sandsynligvis have den **fra**. I Ollama:

```
/set nothink
```

eller sæt det i en Modelfile. Hvis du ser modellen "tænke højt" i stedet for at
kalde værktøjet, er det dét der skal slås fra. (Det er faktisk en fordel ved
Qwen3 over hermes3: tænke-tilstanden kan styres eksplicit.)

## Test-protokol — nu ÉN kommando (v1.36.0)

Den manuelle protokol herunder er erstattet af eval-harnessen (ROADMAP
V12.0). På riggen, fra repo-mappen:

```
set PYTHONPATH=%CD%\worker
python -m app.eval_models hermes3:8b qwen3:14b qwen3:8b
```

Den scorer hver model på (1) tool-disciplin — kalder den værktøjet, narrer
den i prosa (løgnen fra skærmbillederne), eller over-trigger den på "hej"?
(2) dansk-fasthed over 6 ture, (3) tre objektive smoke-checks — plus median-
latens. `--json fil` gemmer resultatet; `--baseline hermes3:8b --gate` gør
den til en hård port (kandidaten skal SLÅ baseline). Kør den efter hver
`ollama pull` — så er modelvalget en måling, ikke en fornemmelse.

## Manuel protokol (historisk — harnessen gør dette automatisk)

Kør hver kandidat gennem de to ting der fejlede. Direkte mod Ollama, uden om app:

**1. Kalder den værktøjet? (det vigtigste)**
```
curl http://127.0.0.1:11434/api/chat -d "{\"model\":\"qwen3:14b\",\"stream\":false,\"messages\":[{\"role\":\"user\",\"content\":\"lav en note der siger hej\"}],\"tools\":[{\"type\":\"function\",\"function\":{\"name\":\"note_append\",\"description\":\"tilfoej en note\",\"parameters\":{\"type\":\"object\",\"properties\":{\"text\":{\"type\":\"string\"}},\"required\":[\"text\"]}}}]}"
```
- **Godt:** svaret har et `tool_calls`-felt med `note_append` og et `text`-argument.
- **Skidt:** svaret er kun prosa ("Sure, I've created...") uden `tool_calls` —
  samme problem som hermes3.

**2. Holder den dansk?**
```
ollama run qwen3:14b "Svar kun på dansk. Hvad er hovedstaden i Danmark?"
```
- Skal svare på dansk, ikke engelsk.

**3. Passer den i VRAM med brugbar kontekst? (kun 14B)**
Efter modellen er loadet, i et andet vindue:
```
nvidia-smi
```
Se hvor meget af de 12 GB der er brugt. Er der <1 GB fri, er konteksten for
presset — så er `qwen3:8b` det pragmatiske valg.

## Hvad jeg IKKE kan verificere (ærligt)

- **Dansk-specifik tool-calling-kvalitet.** Kilderne dokumenterer "multilingual"
  og "119 sprog", men jeg fandt ingen benchmark specifikt for *dansk* + tool-kald.
  119-sprogs-træningen er et stærkt *indirekte* signal for bedre dansk end
  hermes3, men det er en kvalificeret antagelse, ikke bevist tal.
- **Præcis VRAM-margin på DIN rig.** Kilderne siger 14B "barely fits" på et 3060
  12GB med "limited context". Det afhænger af din faktiske kontekst-længde og
  hvad ellers bruger GPU'en (ASR/TTS deler kortet!). Kun din `nvidia-smi` viser
  sandheden. Bemærk: hvis ASR (faster-whisper large-v3) og TTS også ligger på
  GPU'en samtidig, kan 14B + Whisper tilsammen sprænge 12 GB.

## Kilder
- willitrunai.com, localaimaster.com, localllm.in, markaicode.com, gigagpu.com,
  ai-ollama.github.io (VRAM-tal + tool-calling + multilingual, apr.–jun. 2026).

## Vision (V10) — foto → RAG (v1.37.0)

Sæt en vision-model og genstart workeren, så er foto-ingest tændt:

```
set KALIV_VISION_MODEL=llama3.2-vision:11b
```

Kandidater til 3060'eren: `llama3.2-vision:11b` (~8 GB) eller qwen-VL-
familien — **VRAM-kabalen fra §ovenfor gælder dobbelt** (ASR + gen + VLM kan
ikke alle være resident på 12 GB). Uden env-variablen svarer endpointet
ærligt 501 — vi gætter aldrig med gen-modellen, for billeder mod en
ikke-vision-model fejler på model-afhængige måder.

Test fra riggen (billede som base64):

```
curl http://127.0.0.1:8099/rag/ingest/image -H "Content-Type: application/json" -d "{\"image_base64\":\"<BASE64>\",\"source\":\"kvittering\"}"
```

Og "hvad er det her?"-flowet kræver ingen ny kode på Android: chat-stien
bærer allerede billeder — pull modellen, vælg den i dropdownen, vedhæft et
foto (📎).


## Voice-modeller (v1.52.0+): tekst-cloud ≠ tale-cloud

Voice-kæden (ASR→LLM→TTS) har sin EGEN cloud-model, adskilt fra tekst:

- **Tekst-cloud** (`cloudModel`): vælg den tunge model til svære spørgsmål —
  fx `deepseek-v3.1:671b`. Vælges via ☁-chippen i cloud-mode.
- **Tale-cloud** (`voiceCloudModel`): vælg en HURTIG model, for hele kæden
  venter på den — fx `gpt-oss:120b`. Vælges i rig-mode: model-dropdown →
  "Stemme svarer via cloud" til → "☁ Cloud-model til tale" → vælg.
  Falder tilbage til tekst-cloud-modellen indtil den sættes.
- **Lokal tale**: sluk voice-cloud-toggle → den valgte rig-model (qwen3:14b)
  svarer. Hurtigst, men mindre kvalitet.

Routing-striben under headeren viser altid begge ("◈/☁ tekst: X · 🎙/☁ tale: Y").
Med streamende voice (v1.54.0) taler Kaliv første sætning mens resten genereres,
så selv en stor tale-model FØLES hurtigere — men time-to-first-sentence afhænger
stadig af modellens hastighed.
