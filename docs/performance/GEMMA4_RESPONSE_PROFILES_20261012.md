# Gemma 4:26b – svarprofiler (eksperiment, ikke V1-aktiveret)

## Målinger på Windows/Ollama, 12. oktober 2026

Brugerens rig: to RTX 3060 12 GB; `gemma4:26b` 25,2B Q4_K_M.
Enkle kald, varm model, `think=false`, kontekstgrænse 8192:

| Forsøg | Total tid | Outputtokens | Afslutning |
|---|---:|---:|---|
| Ultra | 1,16 s | 57 | stop |
| Kort | 1,89 s | 94 | stop |
| Streaming (5) | 1,21–1,25 s | 59–62 | stop |
| Stabilitet (20) | 1,09–1,42 s | 59–63 | stop |
| Gentaget 1487-token prompt | 2,80 / 1,41 / 1,49 s | 58 | stop |

Streaming time-to-first-visible-text: 105, 115, 132, 143, 212 ms;
median 132 ms. Dette er **ikke** time-to-first-audio.

Thinking true med 512 outputtokens gav `done_reason=length`, tomt svar og
1805 tegn i `thinking`. Thinking false med 401 tokens gav færdigt svar.
For lange kontekstprompts måltes ca. 33–35 s, men testene ændrede både
`num_ctx` og promptlængde og isolerede derfor ikke årsagen.

## Implementeret i denne branch

`worker/app/response_profiles.py` tilbyder fire eksplicit valgte,
immutable, opt-in profiler og en ren funktion `apply_profile`. Den ændrer
kun en **kopi** af et Ollama-payload, bevarer eksisterende systeminstruktioner,
streamingindstillingen og øvrige options samt strengere outputlofter.
Ukendt profil afvises. En separat `apply_chat_profile` kan håndtere simple `/api/chat`-beskeder med bevaret systemrolle og rækkefølge. Tool-calls, multimodale beskeder, ekstra eller ikke-indledende systembeskeder og blandede systemfelter afvises eksplicit. Workerens lokale `ollama_client.chat` understøtter nu opt-in via miljøvariablen `MODELRIG_EXPERIMENTAL_CHAT_PROFILE` med værdierne `voice_brief`, `chat_brief`, `detailed` og `reasoning`. Uden miljøvariablen er payload identisk med før ændringen. Det gælder **kun** lokal plain-text non-streaming chat; streaming, tool-calls og cloud er ikke tilsluttet. Ny isoleret `test_ollama_response_profile_wiring.py` beviser default-off og opt-in uden en Ollama-server.

| Profil | think | num_predict (loft) | Formål |
|---|---|---:|---|
| voice_brief | false | 128 | korte talte svar |
| chat_brief | false | 256 | kort chat |
| detailed | false | 1024 | forklaring |
| reasoning | true | 2048 | krævende ræsonnement |

Tokenlofter kan stoppe et svar midt i en sætning: `done_reason=length`
**må aldrig** vises som et fuldført svar uden eksplicit håndtering. Den første opt-in worker-integration afviser nu `length` og tomme svar med `OllamaError`. Ved eksplicit `done_reason=length` forsøger opt-in plain-text `chat` nu **præcis én** gentagelse med dobbelt `num_predict` (maks. 4096). Kun dette lokale, ikke-streamende kald gentages. Fejl i netværk/HTTP og tomme svar gentages ikke. Hvis andet forsøg også udtømmer tokenbudgettet, afvises svaret, hvilket kan føre til 502. Thinking-indstillingen ændres ikke under retry.
Systemtekst er kun vejledning; den er ikke en sikkerhedsgrænse.

## Eksisterende funktionalitet der skal genbruges

Desktop `OllamaClient.kt` har allerede `chatStream` med NDJSON,
`done=true`-kontrol og en `think`-parameter. Android/cloud har allerede
logik for at slå thinking fra. Undgå parallel implementering eller omgåelse
af eksisterende abort-/sikkerhedskontrakter.

## Før integration og V1-merge

1. Identificér alle produktionskald til Ollama (`/api/generate` og `/api/chat`)
   og den nuværende ejerskabskæde for systemprompts, værktøjer og streaming.
2. Den første integrationssøm er nu tilføjet bag en eksplicit environment-flag, default **off**. Hold den deaktiveret til CI, integrationstests og beslutning om rollout er gennemført; ændr ikke V1-output eller tool-invocations.
3. Vælg profiler ud fra bekræftet UI-/opgave-intent, **ikke** regex-klassifikation
   af brugerindhold. Bevar brugerens eksplicitte ønske om detaljer.
4. Ved `done_reason=length`, håndtér det som ufuldstændigt, ikke succes.
   Ved thinking uden synlig tekst: fallback skal være kontrolleret og afgrænset.
5. Evaluer tool-calling, JSON-format, dansk kvalitet, lange samtaler,
   privacy/sikkerhed, afbrydelser, TTS/ASR og end-to-end første lyd.
6. Kør CI, Windows/Android build og fysiske GPU-tests før aktivering.

Offline-test med worker på PYTHONPATH:
`PYTHONPATH=worker python -m unittest discover -s worker/tests -p test_response_profiles.py`.

Ingen målt hastighedsforbedring kan tilskrives denne branch, før funktionen
er tilsluttet en reel inferenssti og testet på riggen.
