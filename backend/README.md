# ModelRig — Backend (Go, stdlib only)

The control-plane API and reverse proxy. Handles device pairing + tokens, then
proxies chat/models to Ollama and RAG to the worker. **Zero external Go
dependencies** (net/http only) so it compiles anywhere `go` runs.

Status: **built, vetted and smoke-tested** (11/11) in the generator environment.

## Endpoints
| Method | Path                    | Auth   | Purpose                                  |
|--------|-------------------------|--------|------------------------------------------|
| GET    | `/healthz`              | none   | liveness + version                       |
| POST   | `/api/v1/pair/start`    | admin* | mint a pairing code                      |
| POST   | `/api/v1/pair/claim`    | none** | exchange a code for a device token       |
| GET    | `/api/v1/status`        | bearer | device + upstream (ollama/worker) reachability |
| GET    | `/api/v1/health/deep`   | bearer | actively round-trips Ollama + worker (embeds); `ok` + per-check latency |
| GET    | `/api/v1/devices`       | bearer | list paired devices (no token hashes)    |
| DELETE | `/api/v1/devices/{id}`  | bearer | revoke a device (its token dies at once) |
| POST   | `/api/v1/token/rotate`  | bearer | re-issue the calling device's token; old one dies |
| GET    | `/api/v1/models`        | bearer | → Ollama `/api/tags`                     |
| POST   | `/api/v1/chat`          | bearer | → Ollama `/api/chat` (streamed)          |
| POST   | `/api/v1/rag/query`     | bearer | → worker `/rag/query`                    |
| POST   | `/api/v1/rag/ingest`    | bearer | → worker `/rag/ingest`                   |
| POST   | `/api/v1/rag/chat`      | bearer | → worker `/rag/chat` (streamed RAG answer) |
| GET    | `/api/v1/rag/sources`   | bearer | → worker `/rag/sources`                  |
| GET    | `/api/v1/rag/stats`     | bearer | → worker `/rag/stats`                    |
| DELETE | `/api/v1/rag/source`    | bearer | → worker `/rag/source` (query forwarded) |

\* `pair/start` requires header `X-Admin-Key` **iff** `MODELRIG_ADMIN_KEY` is set;
otherwise it is open (dev mode) and the server logs a warning.
\*\* `pair/claim` consumes a valid, unexpired, single-use code, and is
rate-limited per client IP (`MODELRIG_CLAIM_MAX` attempts / 5 min, default 10) to
stop brute-forcing the code space.

Auth is **loopback-free**: there is no localhost bypass — every protected request
needs a valid bearer token, even from 127.0.0.1. Tokens are compared by hash in
constant time.

## Build & run
```bash
cd backend
go build -o modelrig-server ./cmd/modelrig-server

# IMPORTANT: bind 0.0.0.0 (or a Tailscale IP) so phones/LAN can reach it.
MODELRIG_HOST=0.0.0.0 ./modelrig-server
```

## Pairing
```bash
# server stopped: mint a code offline
./modelrig-server -pair

# server running: use the HTTP endpoint (updates the live in-memory store)
curl -X POST http://localhost:8080/api/v1/pair/start
```
Then in a client: `POST /api/v1/pair/claim {"device_name":"...","code":"XXXX-XXXX"}`
→ returns a `token` (shown once).

> `-pair` now detects a running server on `127.0.0.1:PORT` and, if found, asks it
> to mint the code over HTTP — so the code lands in the live store (no more
> dual-writer footgun). Only if no server answers does it write the store file
> directly. If `MODELRIG_ADMIN_KEY` is set, `-pair` sends it automatically.

## Config
Defaults → optional JSON file (`MODELRIG_CONFIG=path`) → env overrides.

| Env                    | Default                     | Notes                              |
|------------------------|-----------------------------|------------------------------------|
| `MODELRIG_HOST`        | `127.0.0.1`                 | **set 0.0.0.0 for LAN/Android**    |
| `MODELRIG_PORT`        | `8080`                      |                                    |
| `MODELRIG_OLLAMA_URL`  | `http://127.0.0.1:11434`    |                                    |
| `MODELRIG_WORKER_URL`  | `http://127.0.0.1:8099`     |                                    |
| `MODELRIG_DATA`        | `./modelrig-data.json`      | device + pairing store             |
| `MODELRIG_PAIRING_TTL` | `300` (seconds)             |                                    |
| `MODELRIG_ADMIN_KEY`   | *(unset → pair/start open)* | gate for `pair/start`              |
| `MODELRIG_CLAIM_MAX`   | `10`                        | max claim attempts / IP / 5 min    |
| `MODELRIG_CONFIG`      | *(unset)*                   | path to a JSON config file         |

See `config.example.json`.

## Layout
```
cmd/modelrig-server/main.go     entrypoint, -pair, graceful shutdown
internal/config                 defaults + file + env
internal/auth                   tokens, SHA-256 hash, device IDs
internal/pairing                XXXX-XXXX unambiguous codes
internal/store                  JSON-file store (mutex, atomic write)
internal/proxy                  generic streaming forwarder
internal/httpapi                routes, middleware, handlers
```

## Verified here
`go vet ./...` clean, `go build` clean, and **22 smoke-test cases** across two
runs:

Core (11): health, 401 without token, pairing start/claim, 64-hex token issuance,
single-use code enforcement, garbage-token rejection, case-insensitive `Bearer`,
unknown/malformed codes, and the Ollama-down proxy path returning 502.

V1 (11): NDJSON **streaming passthrough** proven end to end (three streamed chunks
reassembled), model-list proxy, device list (no `token_hash` leak), device
**revoke** → token invalid immediately, `-pair` HTTP path (a code minted by the
running server is claimable), and **rate limiting** (attempts allowed up to the
limit, then 429). Store persistence verified (token hash stored, pairings emptied
after use).

V1 also covers **token rotation** (rotate → new token works, old token 401, same
device id). Beyond these, an **end-to-end test** (`tests/e2e.py`) runs this
backend together with the real RAG worker and a fake Ollama, driving the whole
flow through the reference CLI (28 assertions, incl. deep health + rotation +
streaming RAG chat). That test is what surfaced the proxy forwarding
request bodies as chunked with no `Content-Length`; the proxy now preserves the
incoming `Content-Length` (and forwards query strings) so upstreams work too.

## Observability
Every request gets an `X-Request-ID` (generated, or taken from the incoming
header if a client sets one). It's returned to the client, forwarded to the
upstream (Ollama/worker), and logged in a structured line:

```
level=info req=1a2b3c… ip=192.168.1.20 method=POST path=/api/v1/rag/query status=200 dur_ms=42
```

The worker logs the same `req` id, so one request traces across both services.
The reference CLI's `doctor` command surfaces upstream health at a glance;
`doctor --deep` hits `/api/v1/health/deep`, which actually round-trips an
embedding through the worker + Ollama (proving the models respond, not just that
ports are open). If a token leaks, `POST /api/v1/token/rotate` (CLI: `rotate`)
issues a fresh one and kills the old — no re-pairing needed.
