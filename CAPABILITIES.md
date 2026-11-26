# CAPABILITIES.md — ModelRig / Kaliv worker

> Aktuel version: se `VERSION`. Booleanerne betyder "dependency kan importeres" (og for
> `cuda`: GPU-device findes) — **ikke** at den valgte model er verificeret indlæsbar. En
> rigere model (installed/configured/verified) er planlagt. Sandheden på en rig er `/capabilities`.

## Capability-model

Workeren rapporterer sine evner som rene booleans, så en klient kan aktivere
eller forklare funktioner frem for at reklamere med noget den tilsluttede worker
ikke har:

- **`GET /capabilities`** → `{ "asr", "tts", "pdf", "docx", "pptx", "html",
  "cuda" }` (billig — kun import-checks; kald den på connect og gate UI'en på
  svaret). At tilføje en nøgle er bagudkompatibelt; at fjerne eller omdøbe en er
  det ikke, og `tests/worker_unit.py` pinner derfor det præcise sæt.
- Samme objekt er inkluderet i **`GET /health/full`** under `capabilities`.

Hver evne afhænger af en **valgfri** dependency, detekteret ved om den kan
importeres (og for `cuda`: CTranslate2's faktiske GPU-device-count, uden at
loade en model):

| Capability | Dependency | Aktivér på riggen |
|---|---|---|
| `asr`  | faster-whisper | `pip install faster-whisper` |
| `tts`  | piper-tts | `pip install piper-tts` |
| `pdf`  | PyMuPDF | `pip install pymupdf` |
| `docx` | python-docx | `pip install python-docx` |
| `pptx` | python-pptx | `pip install python-pptx` |
| `html` | ingen — `html.parser` følger med Python | altid `true` |
| `cuda` | CUDA-runtime + CTranslate2 | GPU + nvidia-drivere (gælder ASR's GPU-brug; Ollamas GPU er separat) |

### Lukket 17/8: PPTX og HTML rapporteres nu

Indtil 17/8 indlæste RAG fire dokumentformater, mens `/capabilities` kun
rapporterede to. `rag_pptx.py` og `rag_html.py` havde begge en
`is_available()` skrevet til nøjagtig samme kontrakt som de øvrige, men
`_capabilities()` medtog dem ikke — så en klient kunne gate PDF og DOCX og
måtte gætte om PPTX. Præcis den situation endpointet findes for at undgå.

Rettet i koden, ikke blot beskrevet. Vagten mod at det sker igen er ikke en
liste over navne: `tests/worker_unit.py` **finder** loaderne ved at gå
`worker/app/rag_*.py` igennem og kræve, at hver med en `is_available()` også
optræder i svaret. En ny loader falder derfor på testen i stedet for stille at
blive urapporterbar.

## Core vs. full worker — **status: voice bundlet, dokument-deps ikke (Kendt begrænsning)**

Den **publicerede** worker-exe (`modelrig-worker-windows-x64.exe`) bygges fra
`worker/requirements.txt` + `worker/requirements-release-voice.txt`
(faster-whisper, piper-tts, soundfile og CUDA 12/cuDNN 9-runtime), og
release-workflowet verificerer stemmepakken i den frosne exe
(`scripts/verify_frozen_voice_package.py`). `asr`/`tts`/`cuda` er altså med;
PDF/DOCX/PPTX-loaderne er stadig **ikke** bundlet. Så på en frisk installation
rapporterer `/capabilities` typisk `pdf/docx/pptx = false`, indtil de
installeres på riggen (kræver en Python-worker, ikke exe'en).

Dette er en **bevidst accepteret begrænsning** for nu, ikke en fejl — men den er
nu *ærlig*: workeren lover ikke evner den ikke har, og klienten kan spørge.

**Vej til full (planlagt, ikke gjort):** enten en separat `modelrig-worker-full`
med dokument-dependencies bundlet + feature-smoke-tests i CI, eller én full appliance-worker.
Indtil da: kør worker fra Python på riggen med de deps du vil bruge.

## Hvad klienten bør gøre (planlagt)

Klienterne bør kalde `/capabilities` på connect og deaktivere/forklare voice- og
dokument-funktioner der ikke er tilgængelige på den tilsluttede worker, i stedet
for at vise en knap der fejler. **(Landet 17/8 for Android: `WorkerCapabilities` henter
svaret ved forbindelsesskift, `IngestCapability` gater dokument-ingest og
`VoiceCapability` gater mikrofonen. Kun et UDTRYKKELIGT `false` blokerer —
ældre rig, manglende nøgle eller mislykket probe opfører sig som hidtil.
Desktop har i dag hverken dokument-ingest eller
stemme — `RagClient` kan kun `chatStream` og `listSources` — så der er intet
at gate der endnu. `workflow_client_capability_gates.py` scanner alligevel
BEGGE klienttræer og opdager selv nye kaldesteder, så en fremtidig
desktop-ingest ikke kan komme ind ugatet.)**

> **Tre forskellige ting hedder "capabilities". Forveksl dem ikke:**
> `GET /capabilities` er workerens syv dependency-booleans (dette dokument).
> `GET /api/v1/tools` er T-030's `kaliv-capability/v2`-deskriptorer, som
> Kontrolcentret læser. `GET /api/v1/experimental/agent3/capabilities` er
> Agent 3's egen flade. Et grep efter "capabilities" rammer alle tre, og det
> har allerede kostet én forkert konklusion om at gatingen var på plads.

## Status-nøgle

- **Implementeret:** `/capabilities` + `capabilities` i `/health/full`; ærlig
  import- + CUDA-detektion; unit-testet (`tests/worker_unit.py`).
- **Kendt begrænsning:** udgivet worker-exe har voice (ASR/TTS/CUDA), men ingen PDF/DOCX/PPTX-deps.
- **Landet:** Android-klient-gating (17/8). **Planlagt:** full-worker-pakke med dokument-deps + smoke-tests.
