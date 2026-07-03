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
| POST   | `/rag/query`  | `{query, top_k?, synthesize?, model?}` → matches (text, source, chunk_index, score) (+ answer) |

Any Ollama failure → HTTP 502 with a readable detail (never a stack trace).

## Run
```bash
cd worker
python3 -m venv .venv && source .venv/bin/activate   # optional
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8099
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
word loss), and the full **chunk → embed → store → retrieve** path with stubbed
embeddings (a query correctly returns the nearest source; matches carry
`chunk_index` + `score`). 20 cases total.
