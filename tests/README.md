# ModelRig tests

Run the whole suite (Unix / WSL; needs Go + Python with worker deps):
```bash
sh tests/run_tests.sh
```
It builds the backend to a temp path, exports `MODELRIG_BIN`, frees ports, and
runs everything below. **76 assertions** total.

| File | What it covers | Count |
|------|----------------|-------|
| `worker_unit.py` | cosine math, `/healthz`, request validation (422), Ollama-down 502 | 9 |
| `worker_rag.py`  | chunking + full retrieval + source management (sources/stats/delete) + source-filtered query | 22 |
| `backend_smoke.py` | health, auth (401), pairing start/claim, single-use codes, token issuance, Ollama-down 502 | 11 |
| `backend_v1.py` | streaming passthrough, model proxy, device list/revoke, `-pair` HTTP path, rate limiting | 12 |
| `e2e.py` | **real backend + real worker + fake Ollama** via the CLI; RAG mgmt, request-id tracing, `doctor` | 22 |

## What's genuinely exercised
- **backend** and **worker** are compiled/run and hit over real sockets.
- `e2e.py` proves the integrated chain (backend ↔ worker ↔ Ollama) — it's what
  caught the proxy sending request bodies as chunked with no `Content-Length`.
- Ollama is faked (deterministic embeddings + canned chat), so no model calls are
  made. Real-model behaviour still needs a live rig.

## Running one file
```bash
export MODELRIG_BIN=/path/to/modelrig-server        # or let run_tests.sh build it
PYTHONPATH="$(pwd)/worker" python3 tests/worker_unit.py
python3 tests/e2e.py            # starts its own servers
```

## Notes
- The suite frees TCP ports by number between runs. It never uses `pkill` with a
  process-name pattern — matching the server name would also match the test
  runner's own command line and kill the shell.
- `e2e.py` tears processes down with SIGTERM then SIGKILL so nothing is left
  holding a port.
