# ModelRig — Worker (Python / FastAPI RAG)

Retrieval-augmented generation service. Embeds documents via Ollama, stores them
in SQLite, and answers queries by brute-force cosine retrieval + optional
synthesis. The backend proxies `/api/v1/rag/*` here; clients never call it
directly.

Status: **built and tested** (9/9) in the generator environment (logic verified
with Ollama stubbed out; live embedding/generation needs a running Ollama).

## Endpoints
| Method | Path          | Purpose                                        |
|--------|---------------|------------------------------------------------|
| GET    | `/healthz`    | liveness + version + document count            |
| POST   | `/rag/ingest` | `{documents:[{text, source?}], chunk_size?, overlap?}` → chunk + embed + store |
| POST   | `/rag/query`  | `{query, top_k?, synthesize?, model?, source?}` → matches (text, source, chunk_index, score) (+ answer); `source` restricts retrieval to one source |
| POST   | `/rag/chat`   | `{query, top_k?, model?, source?}` → **streamed** NDJSON: first line `{sources:[…]}`, then Ollama chat deltas (retrieve + stream answer) |
| GET    | `/health/deep`| round-trip an embedding through Ollama → `ok` + dims/latency (or error) |
| GET    | `/rag/sources`| list ingested sources with chunk counts + last-ingested time |
| GET    | `/rag/stats`  | corpus totals: distinct sources + total chunks |
| DELETE | `/rag/source?source=X` | delete every chunk for source `X` (404 if none); `(none)` clears NULL-source chunks |

Any Ollama failure → HTTP 502 with a readable detail (never a stack trace).

## Run
```bash
cd worker
python3 -m venv .venv && source .venv/bin/activate   # optional
pip install -r requirements.txt
# Loopback only: the worker has no auth; the backend reaches it on localhost.
uvicorn app.main:app --host 127.0.0.1 --port 8099
```

## Config (env)
| Env                       | Default                    |
|---------------------------|----------------------------|
| `MODELRIG_OLLAMA_URL`     | `http://127.0.0.1:11434`   |
| `MODELRIG_EMBED_MODEL`    | `nomic-embed-text`         |
| `MODELRIG_GEN_MODEL`      | `qwen2.5-coder:7b`         |
| `MODELRIG_OLLAMA_TIMEOUT` | `60` (seconds)             |
| `MODELRIG_DB`             | `./modelrig-rag.db`        |

## Example
```bash
curl -X POST http://localhost:8099/rag/ingest -H 'Content-Type: application/json' \
  -d '{"documents":[{"text":"ModelRig binds 127.0.0.1 by default.","source":"docs"}]}'

curl -X POST http://localhost:8099/rag/query -H 'Content-Type: application/json' \
  -d '{"query":"what host does modelrig bind?","top_k":3}'
```

## Design notes
- **Chunking**: documents are split into overlapping chunks (`chunk_size` chars,
  `overlap` chars, prefer whitespace break points) before embedding, so a fact
  split across a boundary stays retrievable. Each chunk keeps its `source` and a
  `chunk_index`. Defaults 800/150; tune per corpus.
- Embeddings stored as JSON text in SQLite; retrieval is a linear cosine scan.
  Fine to a few thousand chunks. Swap in `sqlite-vec` or Qdrant when the corpus
  outgrows a linear scan (see STATUS.md).
- Pure-Python cosine (`app/rag.py`) — no numpy dependency.

## Verified here
Cosine unit tests (identical/orthogonal/mismatched/empty), `/healthz` 200, request
validation (missing `query` → 422, `top_k` > 20 → 422), Ollama-down → clean 502
for both endpoints, **chunking** unit tests (empty/short/long, size bounds, no
word loss), the full **chunk → embed → store → retrieve** path with stubbed
embeddings, and **source management** (stats, per-source chunk counts, delete a
source → gone from retrieval, delete unknown → 404), plus **source-filtered
queries** (retrieval restricted to one source) and **streaming RAG chat**
(`/rag/chat` first-line sources + reassembled streamed answer). 34 cases total.

Every request is logged as a structured `level=info req=… method=… path=…
status=… dur_ms=…` line; the `req` id is taken from the backend's `X-Request-ID`
header, so a single request can be traced across backend + worker logs.
