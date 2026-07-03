# ModelRig — STATUS (honest build report)

Version **0.7.0** — "V1 backbone + RAG management, integration-tested". Autonomous session, **2026-07-02/03**.

## Read this first
This repo was rebuilt from architecture after a sandbox reset wiped the earlier
verified code, then pushed toward V1. Structure and design are faithful, but this
is a *fresh* build — not byte-for-byte the earlier artifact. Everything below is
labelled by how it was actually verified.

Environment had **Go** (installed on the fly) and **Python**, but **no Kotlin
compiler, no Gradle, no Android SDK**. So:

- backend + worker were genuinely compiled/run/tested here.
- desktop + android are **complete source you build locally** — written to
  compile, not compiled here. Treat first local build as the real test.

## What's new in 0.7.0
- **RAG source management** — the RAG is now operable, not just write-and-query:
  - `GET /rag/sources` — sources with chunk counts + last-ingested time.
  - `GET /rag/stats` — corpus totals (distinct sources, total chunks).
  - `DELETE /rag/source?source=X` — remove every chunk for a source (404 if none).
  - All proxied through the backend (`/api/v1/rag/*`) and exposed in the CLI
    (`rag-sources`, `rag-stats`, `rag-delete --source`).
- **Proxy now forwards query strings** to upstream (needed for the DELETE above);
  general fix, benefits any query-param endpoint.
- Tests grew to **69 assertions**; the e2e now ingests two sources, lists, deletes
  one, and confirms it's gone — through the CLI against live processes.

## What landed in 0.6.0
- **Reference CLI** (`tools/modelrig-cli.py`) — a dependency-free client: pair,
  streaming chat, models, RAG, device list/revoke. A real client you can run today
  while the Kotlin clients await a local build.
- **End-to-end integration test** (`tests/e2e.py`) — starts the **real** backend +
  **real** worker + a fake Ollama and drives the whole flow through the CLI
  (12/12). This is the first test that exercises the modules *together*.
- **Proxy bug found and fixed by that test**: the reverse proxy forwarded upstream
  request bodies with chunked transfer encoding and no `Content-Length`. Real
  Ollama (Go) decodes that fine, but stricter upstreams don't — the proxy now
  preserves `Content-Length`. Exactly the class of bug unit tests miss.
- **Ops** (`deploy/`): env reference, a Windows launcher (`run-windows.ps1`), and
  systemd units for worker + backend.
- **Test suite bundled** (`tests/`, `sh tests/run_tests.sh`) — 55 assertions.

## What landed in 0.5.0 (the V1 push)
**Backend (verified):**
- **Streaming** chat passthrough proven end to end (NDJSON, `/api/v1/chat`).
- **Device management**: `GET /api/v1/devices` (no token hashes) and
  `DELETE /api/v1/devices/{id}` (revoke → token dies immediately).
- **Rate limiting** on `pair/claim` (`MODELRIG_CLAIM_MAX`/5 min per IP) against
  code brute-forcing.
- **`-pair` footgun fixed**: it now detects a running server and mints the code
  over HTTP (single writer), falling back to a direct file write only when no
  server answers.

**Worker (verified):**
- **Chunking** with overlap before embedding; matches now carry `source` +
  `chunk_index` + `score`. `chunk_size`/`overlap` are request params.

**Clients (source only, NOT compiled here):**
- **Streaming** replies token-by-token (desktop `java.net.http` line reader,
  Android OkHttp source reader).
- **Model picker** — desktop pulls `/api/tags` or `/api/v1/models`; Android pulls
  `/api/v1/models`; choice persists on Android via `TokenStore`.

## Verified (ran here)
| Item | How |
|------|-----|
| Backend compiles / vets | `go build ./...` + `go vet ./...` clean |
| Backend behaviour | **23** assertions: core smoke (11) + V1 (12) |
| Backend persistence | store JSON inspected: token hash stored, pairings emptied after single use |
| Worker imports & runs | FastAPI app loads; `/healthz` 200 |
| Worker logic | **29**: cosine, validation, 502 handling, chunking, retrieval, source management |
| **Integrated stack** | **17** e2e assertions: real backend + real worker + fake Ollama, driven through the CLI |

**69 assertions total** via `sh tests/run_tests.sh`.

**Backend V1 test highlights:** streamed chat reassembled from 3 chunks ("Hej fra
ModelRig") · model-list proxy · devices list without `token_hash` · revoke →
revoked token returns 401 · `-pair` HTTP path (code from running server is
claimable) · rate limit (allowed up to limit, then 429).

**Worker V1 test highlights:** chunk_text (empty/short/long, size bounds, no word
loss) · chunk→embed→store→retrieve with stubbed embeddings returns the nearest
source with `chunk_index` + `score`.

**Integration (e2e) highlights:** pair via CLI → `whoami` → models proxy →
**streaming chat reassembled** ("stream-ok") → rag-ingest → rag-query (matches
only, then synthesis) → devices → revoke → a call after revoke correctly fails
401. All through the reference CLI against live backend + worker processes.

## NOT verified here (source only — build locally)
| Item | Why | What to do |
|------|-----|-----------|
| desktop compiles/runs | no JVM-desktop/Gradle toolchain | `cd desktop && gradle run` |
| android compiles/APK | no Android SDK | Android Studio, or `./gradlew assembleDebug` |
| client streaming + model picker | Kotlin not compiled here | exercise against a live rig |
| Kotlin/Compose versions | couldn't resolve deps here | bump if Gradle complains |
| Any live Ollama call (local or cloud) | no Ollama in env | test against your rig |

## Versions & assumptions
- **Go**: module targets `go 1.23`; built with 1.23.4. Still **zero external Go
  deps** (net/http only).
- **Desktop**: Kotlin `2.0.21`, Compose Compiler plugin `2.0.21`, Compose
  Multiplatform `1.7.0`. Plausible, **unverified** — use the current matched pair
  if the build fails.
- **Android**: AGP `8.5.2`, Kotlin `2.0.21`, Compose BOM `2024.09.03`, OkHttp
  `4.12.0`.
- **Ollama Cloud** (desktop fallback): host `https://ollama.com`, header
  `Authorization: Bearer <OLLAMA_API_KEY>`, `/api/chat` (same shape as local),
  `:cloud`-suffix models. Confirmed from docs, not exercised with a real key.
- **Brand palette** invented (graphite/signal/amber) — retune if a real one exists.

## Known limitations (V1)
1. **JSON file store, not SQLite.** Still dependency-free and fine for a handful of
   devices. The `-pair` dual-writer footgun is now handled (HTTP-first). SQLite
   (`modernc.org/sqlite`, pure Go) remains the path once device count / write
   frequency grows.
2. **RAG retrieval is a linear cosine scan.** O(n) per query. Swap in `sqlite-vec`
   / Qdrant past a few thousand chunks.
3. **Streaming fallback is pre-stream only.** If the local source dies mid-stream,
   the error surfaces (we don't restart on cloud and double the output).
4. **`pair/start` is open in dev mode** unless `MODELRIG_ADMIN_KEY` is set (logged
   at startup). `-pair` sends the key automatically when set.
5. **Android stores the token in plain SharedPreferences** and ships
   `usesCleartextTraffic=true` (LAN HTTP). Fine for home LAN; harden with
   Tailscale/HTTPS + DataStore/Keystore.
6. **No Gradle wrapper jar shipped.** Run `gradle wrapper --gradle-version 8.9`
   once, or use a system Gradle.

## Suggested next steps (toward a real 1.0 tag)
1. Build desktop + android locally; fix version drift; confirm streaming + model
   picker against a live rig.
2. Confirm LOCAL→CLOUD fallback by killing Ollama with a cloud key set.
3. Persist desktop settings; add token/sec + per-message source history.
4. Decide SQLite vs JSON for the backend store before scaling device count.
5. Only tag **1.0** once both clients are built and smoke-tested on real hardware.
