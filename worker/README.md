# ModelRig — Worker (Python / FastAPI RAG)

Retrieval-augmented generation service. Embeds documents via Ollama, stores them
in SQLite, and answers queries by brute-force cosine retrieval + optional
synthesis. The backend proxies `/api/v1/rag/*` here; clients never call it
directly.

## Endpoints
| Method | Path          | Purpose                                        |
|--------|---------------|------------------------------------------------|
| GET    | `/healthz`    | liveness + version + document count            |
| POST   | `/rag/ingest` | `{documents:[{text, source?}], chunk_size?, overlap?}` → chunk + embed + store |
| POST   | `/rag/query`  | `{query, top_k?, synthesize?, model?, source?}` → matches + optional answer |
| POST   | `/rag/chat`   | streamed NDJSON: sources header, then Ollama deltas |
| GET    | `/health/deep`| live embedding round-trip                      |
| GET    | `/rag/sources`| source names, chunk counts and last ingest     |
| GET    | `/rag/stats`  | corpus totals                                  |
| DELETE | `/rag/source?source=X` | delete every chunk for source `X`      |

Any Ollama failure → HTTP 502 with a readable detail.

## Run
```bash
cd worker
python3 -m venv .venv && source .venv/bin/activate   # optional
pip install -r requirements.txt
# Loopback only: the worker has no auth; the backend reaches it on localhost.
uvicorn app.entrypoint:app --host 127.0.0.1 --port 8099
```

`app.entrypoint:app` is the **production entrypoint**. It wraps FastAPI at the
ASGI boundary and therefore:

- enforces `KALIV_MAX_UPLOAD_MB` even for chunked requests without
  `Content-Length`, before FastAPI buffers JSON in RAM;
- removes `alva_voice_*` temporary audio after the final response frame or a
  cancelled stream.

Importing or launching `app.main:app` directly is reserved for focused route
unit tests and bypasses those process-boundary guarantees.

## Config (env)
| Env                       | Default                    |
|---------------------------|----------------------------|
| `MODELRIG_OLLAMA_URL`     | `http://127.0.0.1:11434`   |
| `MODELRIG_EMBED_MODEL`    | `nomic-embed-text`         |
| `MODELRIG_GEN_MODEL`      | `qwen2.5-coder:7b`         |
| `MODELRIG_OLLAMA_TIMEOUT` | `60` (seconds)             |
| `MODELRIG_DB`             | `./modelrig-rag.db`        |
| `KALIV_MAX_UPLOAD_MB`     | `25`                       |

## Example
```bash
curl -X POST http://localhost:8099/rag/ingest -H 'Content-Type: application/json' \
  -d '{"documents":[{"text":"ModelRig binds 127.0.0.1 by default.","source":"docs"}]}'

curl -X POST http://localhost:8099/rag/query -H 'Content-Type: application/json' \
  -d '{"query":"what host does modelrig bind?","top_k":3}'
```

## Design notes
- Documents are split into overlapping chunks before embedding.
- Embeddings are JSON in SQLite; retrieval is currently a linear cosine scan.
- Pure-Python cosine (`app/rag.py`) keeps the core dependency-light.
- Every request is logged with a request id propagated from the backend.
- Production launchers (`worker/run_worker.py`, `scripts/start-kaliv.bat`,
  `deploy/run-windows.ps1`, systemd) all use the hardened entrypoint.
