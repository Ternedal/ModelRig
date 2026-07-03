# ModelRig

A local-first AI platform: run models on your own hardware via Ollama, reach them
from a desktop app and an Android phone, with an optional RAG service and an
Ollama Cloud fallback for when local isn't enough.

Version: **0.8.0** (V1 backbone + RAG management + observability)

## Architecture
```
┌──────────────┐        ┌──────────────┐
│  Desktop     │        │  Android V1  │
│ (Compose JVM)│        │ (Compose)    │
└──────┬───────┘        └──────┬───────┘
       │  local-first,          │  pair + chat
       │  cloud fallback        │  (bearer token)
       │                        │
       │                 ┌──────▼───────────────┐
       │  (direct, or    │  Backend (Go)        │
       └──via backend)──▶│  pairing · tokens ·  │
                         │  reverse proxy       │
                         └───┬──────────────┬───┘
                             │              │
                     /api/chat,/api/tags   /rag/*
                             │              │
                       ┌─────▼─────┐  ┌─────▼──────────┐
                       │  Ollama   │  │  Worker (Py)   │
                       │ (local)   │  │  FastAPI RAG   │
                       └───────────┘  └──────┬─────────┘
                                             │ embeddings/gen
                                       ┌─────▼─────┐
                                       │  Ollama   │
                                       └───────────┘

Cloud fallback (desktop): if local is down/insufficient →
Ollama Cloud (https://ollama.com, model :cloud) with OLLAMA_API_KEY.
```

- **backend/** — Go, stdlib only. Device pairing (short `XXXX-XXXX` codes) →
  hashed bearer tokens, device list + **revoke**, brute-force **rate limiting** on
  claim, then reverse-proxies chat/models to Ollama (streaming) and RAG to the
  worker. Auth is loopback-free.
- **worker/** — Python FastAPI. RAG: **chunk** (overlapping) → embed via Ollama →
  SQLite → cosine retrieval → optional synthesis. Plus **source management**: list
  sources, corpus stats, delete a source.
- **desktop/** — Compose Desktop (JVM). **Streaming** chat with local-first +
  Ollama Cloud fallback, model picker, branded UI.
- **android/** — Compose Android V1. Pair with the backend, then **streaming**
  chat with a model picker.
- **tools/** — `modelrig-cli.py`, a dependency-free reference client (pair, chat,
  RAG, device mgmt). Runnable today; used to drive the e2e test.
- **tests/** — worker unit + RAG tests, backend smoke + V1 tests, and an
  end-to-end integration test. `sh tests/run_tests.sh` runs all 55 assertions.
- **deploy/** — env reference, a Windows launcher (`run-windows.ps1`), and systemd
  units for running the worker + backend as services.

## ⚠️ The one gotcha that wastes an afternoon
The backend defaults to binding **`127.0.0.1`**. That is unreachable from your
phone or any other machine. Before pairing Android, set:
```bash
MODELRIG_HOST=0.0.0.0 ./modelrig-server      # LAN
# or bind a Tailscale IP for remote access
```
The backend logs this warning at startup; the Android pairing screen repeats it.

## Run order (local dev)
```bash
# 0. Ollama running with your models
ollama pull qwen2.5-coder:7b
ollama pull nomic-embed-text

# 1. Worker (RAG) — optional, only if you use /rag/*
cd worker && pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8099

# 2. Backend
cd ../backend && go build -o modelrig-server ./cmd/modelrig-server
MODELRIG_HOST=0.0.0.0 ./modelrig-server

# 3. Pair a device
./modelrig-server -pair            # (server stopped) OR:
curl -X POST http://localhost:8080/api/v1/pair/start   # (server running)

# 4a. Desktop
cd ../desktop && gradle run

# 4b. Android
cd ../android && ./gradlew assembleDebug

# 4c. Or the reference CLI (works today, no build)
python tools/modelrig-cli.py --url http://localhost:8080 pair --code XXXX-XXXX
python tools/modelrig-cli.py doctor    # backend / worker / ollama health
python tools/modelrig-cli.py chat "hello"
```

Run the tests (Unix/WSL, needs Go + Python worker deps):
```bash
sh tests/run_tests.sh
```

## Build status at a glance
| Module   | State in this drop                    | Verified here                    |
|----------|---------------------------------------|----------------------------------|
| backend  | compiled binary + tests               | ✅ `go build`/`vet`, 23 (smoke 11 + V1 12) |
| worker   | runs, logic tested                    | ✅ 31 (unit 9 + RAG 22, Ollama stubbed) |
| e2e      | backend + worker run together         | ✅ 22 (full chain via the CLI)    |
| desktop  | complete source, **build locally**    | ⚠️ no JVM/Gradle here             |
| android  | complete source, **build locally**    | ⚠️ no Android SDK here            |

**76 assertions** total (`sh tests/run_tests.sh`), including cross-service request
tracing (same `X-Request-ID` in backend + worker logs) and the CLI `doctor`
health check. Streaming and the model picker in the clients are written but not
compiled here — build locally.

See **STATUS.md** for the honest breakdown: what's proven, what's only source,
versions/assumptions, and known limitations.

## License
MIT — see LICENSE.
