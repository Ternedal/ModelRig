# Modelvalg til agent-stien (RTX 3060 12GB)

Formål: erstatte `hermes3:8b` på agent-stien med en model der (1) kalder værktøjer
pålideligt i stedet for at beskrive dem i prosa, og (2) holder dansk bedre. Det
er de to reelle svagheder vi så under test.

## Anbefaling (kort)

1. **Prøv `qwen3:14b` først.** Nyeste generation (udgivet apr. 2025), trænet på
   119 sprog — det bedste signal for stærkere dansk end hermes3 — Apache 2.0, og
   tool-calling indbygget. **Men det er tæt** på et 3060: vægtene fylder ~8,7 GB
   ved Q4_K_M, og der er kun 12 GB, så konteksten bliver begrænset. Test det på
   din rig; hvis konteksten er for trang eller den er for langsom, drop til 8B.
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

## Test-protokol (sammenlign mod hermes3 på 5 minutter)

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
