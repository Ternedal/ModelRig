# CAPABILITIES.md — ModelRig / Kaliv worker

> Aktuel version: se `VERSION`. Booleanerne betyder "dependency kan importeres" (og for
> `cuda`: GPU-device findes) — **ikke** at den valgte model er verificeret indlæsbar. En
> rigere model (installed/configured/verified) er planlagt. Sandheden på en rig er `/capabilities`.

## Capability-model

Workeren rapporterer sine evner som rene booleans, så en klient kan aktivere
eller forklare funktioner frem for at reklamere med noget den tilsluttede worker
ikke har:

- **`GET /capabilities`** → `{ "asr", "tts", "pdf", "docx", "cuda" }` (billig —
  kun import-checks; kald den på connect og gate UI'en på svaret).
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
| `cuda` | CUDA-runtime + CTranslate2 | GPU + nvidia-drivere (gælder ASR's GPU-brug; Ollamas GPU er separat) |

### Hul: PPTX og HTML rapporteres ikke (17/8)

RAG indlæser i dag fire dokumentformater, men `/capabilities` rapporterer kun
to af dem. `worker/app/rag_pptx.py` og `rag_html.py` har begge en
`is_available()` skrevet til nøjagtig samme kontrakt som de fire ovenfor —
`rag_pptx` tjekker om `python-pptx` kan importeres, `rag_html` returnerer
altid `True` fordi `html.parser` følger med Python — men `_capabilities()` i
`worker/app/main_impl.py` medtager dem ikke.

Konsekvensen er præcis den situation endpointet blev bygget for at undgå: en
klient kan ikke spørge før den reklamerer. Den kan gate PDF og DOCX, men må
gætte om PPTX.

**Dette er en kodefejl, ikke en dokumentationsfejl.** Den er skrevet ned her i
stedet for at blive rettet i en docs-omgang, fordi to nye felter i
`/capabilities` er en adfærdsændring i en offentlig kontrakt og hører til i
sin egen PR — med `worker_unit.py` udvidet tilsvarende.

## Core vs. full worker — **status: core (Kendt begrænsning)**

Den **publicerede** worker-exe (`modelrig-worker-windows-x64.exe`) bygges fra
`worker/requirements.txt`, som pr. 17/8 indeholder FastAPI, Uvicorn, HTTPX,
Pydantic, cryptography og tzdata — altså stadig ingen af de fire nedenfor.
De fire ovenstående er kommenterede/valgfri og er **ikke** i den udgivne exe. Så
på en frisk installation rapporterer `/capabilities` typisk `asr/tts/pdf/docx =
false`, indtil de installeres på riggen (kræver en Python-worker, ikke exe'en).

Dette er en **bevidst accepteret begrænsning** for nu, ikke en fejl — men den er
nu *ærlig*: workeren lover ikke evner den ikke har, og klienten kan spørge.

**Vej til full (planlagt, ikke gjort):** enten en separat `modelrig-worker-full`
med dependencies bundlet + feature-smoke-tests i CI, eller én full appliance-worker.
Indtil da: kør worker fra Python på riggen med de deps du vil bruge.

## Hvad klienten bør gøre (planlagt)

Klienterne bør kalde `/capabilities` på connect og deaktivere/forklare voice- og
dokument-funktioner der ikke er tilgængelige på den tilsluttede worker, i stedet
for at vise en knap der fejler. **(Endpointet findes; klient-gating udestår
fortsat — efterprøvet 17/8: intet i android/, desktop/ eller backend/ kalder
`/capabilities`.)**

> **Tre forskellige ting hedder "capabilities". Forveksl dem ikke:**
> `GET /capabilities` er workerens fem dependency-booleans (dette dokument).
> `GET /api/v1/tools` er T-030's `kaliv-capability/v2`-deskriptorer, som
> Kontrolcentret læser. `GET /api/v1/experimental/agent3/capabilities` er
> Agent 3's egen flade. Et grep efter "capabilities" rammer alle tre, og det
> har allerede kostet én forkert konklusion om at gatingen var på plads.

## Status-nøgle

- **Implementeret:** `/capabilities` + `capabilities` i `/health/full`; ærlig
  import- + CUDA-detektion; unit-testet (`tests/worker_unit.py`).
- **Kendt begrænsning:** udgivet worker-exe er core-only (ingen ASR/TTS/PDF/DOCX-deps).
- **Planlagt:** klient-gating på capabilities; full-worker-pakke + smoke-tests.
