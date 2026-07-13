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

## Core vs. full worker — **status: core (Kendt begrænsning)**

Den **publicerede** worker-exe (`modelrig-worker-windows-x64.exe`) bygges fra
`worker/requirements.txt`, som kun indeholder FastAPI, Uvicorn, HTTPX og Pydantic.
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
for at vise en knap der fejler. (Endpointet findes; klient-gating udestår.)

## Status-nøgle

- **Implementeret:** `/capabilities` + `capabilities` i `/health/full`; ærlig
  import- + CUDA-detektion; unit-testet (`tests/worker_unit.py`).
- **Kendt begrænsning:** udgivet worker-exe er core-only (ingen ASR/TTS/PDF/DOCX-deps).
- **Planlagt:** klient-gating på capabilities; full-worker-pakke + smoke-tests.
