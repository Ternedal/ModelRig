# ModelRig — STATUS (honest build report)

Version **0.16.0** — "V1 milestone 0.16: stable signing, conversation persistence, stop button, official icon". Autonomous session, **2026-07-02/03**.

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

## What's new in 0.16.0  (roadmap milestone 0.16 — "Fundament der ikke smuldrer")
**⚠️ ONE-TIME REINSTALL REQUIRED:** this release switches from the session-local
debug signature to a **stable release keystore** (committed under
`android/signing/`, password in keystore.properties — keep a backup copy in
Notion Secrets). Android refuses to update across a signature change, so
**uninstall the old app once**, then install this APK. Cloud key + system
prompts must be re-entered once. Every future APK installs over the top, from
any session or machine.

- **Stable signing** (both debug and release build types use the repo keystore).
  Cert: CN=ModelRig, SHA-256 `6563 92B0 3A32 1501 …` — verified with apksigner.
  Ships as a **release** build from now on (`versionCode 16`, `versionName 0.16.0`).
- **Conversation persistence** (`data/ChatDb.kt`, Android built-in SQLite, no new
  dependency): conversations + messages survive app kill and phone restart; the
  latest conversation reopens on launch; a **Samtaler** screen lists all
  (open / new / delete). Assistant replies are written once on completion — an
  in-flight reply is lost on a crash (accepted V1 tradeoff).
- **Stop button**: the send button becomes a stop square while streaming;
  cancels the underlying OkHttp call (<1 s), keeps the partial text with an
  "[afbrudt]" marker, and persists the partial.
- **Error hygiene**: failed replies are shown in red but are **never persisted
  and never sent back to the model as history** (previously an error bubble
  leaked into the next request's context).
- **Official app icon**: foreground extracted from the approved
  `modelrig_app_icon_final.png` export (755 px source — sharp), background
  gradient sampled from the same icon. Exports preserved under `/brand/`.

**Verified here:** compiles; signed release APK; signature fingerprint matches
keystore; versionCode/Name correct; server suite smoke green (11/11) after the
version bump.
**Needs on-device:** persistence round-trip, conversation list UX, stop button,
icon on the launcher, and the still-open 0.15.2 keyboard check.

## What's new in 0.15.5
- **Icon now uses the REAL brand mark**, not a hand-drawn approximation. The
  designer's actual symbol (an M-truss whose diagonals **cross** in the centre with
  a stem to a bottom node) was extracted straight from the brand PNG by keying out
  everything except the sapphire+champagne artwork, then placed on the obsidian
  background. Shape verified before shipping.
- Caveat: the source art in the handoff is modest resolution, so the extracted mark
  is a little soft; for pixel-perfect crispness, export the symbol as SVG from the
  source file and drop it in as `ic_launcher_foreground`.

## What's new in 0.15.4
- **Icon refined to match the real brand mark.** The 0.15.3 icon was a simplified
  M. Looked closely at the designer's actual symbol and reproduced it faithfully:
  an M-truss with a central sapphire **hub**, a **stem** down to a **champagne**
  node at bottom-centre, and a **champagne** node top-left (sapphire elsewhere).
  Still a geometric interpretation, not a pixel-trace of the source art.

## What's new in 0.15.3
- **Real app icon.** The app had no `android:icon`, so it showed the default
  Android robot. Added a proper **adaptive icon** (vector, crisp at every size):
  the ModelRig **"M" drawn as a node-graph** — one continuous sapphire stroke
  through four corner nodes with a **champagne accent node** in the centre, on an
  obsidian gradient. Matches the brand mark direction. Wired via
  `android:icon`/`android:roundIcon`. (A PNG preview ships with this release.)

## What's new in 0.15.2
- **Keyboard/inset, take 2 (correct this time).** Pinned down from two on-device
  data points: with no `softInputMode` the window *resized* (so ime-padding
  double-lifted the input); with `adjustResize` the window does *not* resize (so
  removing the padding hid the input behind the keyboard). The correct, documented
  edge-to-edge combo is **`adjustResize` (window doesn't resize) + `imePadding`**
  (lifts the input by the keyboard height). Both are now in place.

## What's new in 0.15.1
- **Fix: input field jumped to the top when the keyboard opened.** Classic
  edge-to-edge double-inset — the window already resizes for the keyboard, so the
  extra `ime` padding on the input bar pushed it up by the keyboard height. The
  input now uses only the navigation-bar inset, and the activity declares
  `windowSoftInputMode="adjustResize"` so the resize behaviour is deterministic.
  On-device check: keyboard-up should keep the input just above the keyboard.

## What's new in 0.15.0
- **Real brand applied** (Android). The theme now uses the **ModelRig brand
  handoff v3** palette (now committed under `/brand/` so it can't be lost again),
  sampled from the brand board: sapphire `#306CFC`, champagne `#DEC08A`, obsidian/
  graphite base, cloud-white text. Earlier builds used an invented palette; this
  matches the brand direction (premium dark, sapphire actions, champagne accent).
  Source badge is now a champagne/sapphire pill; send is a clean sapphire arrow.
- **Cloud model dropdown**: `CloudClient.listModels()` (tries `/api/tags`, then
  `/v1/models`) populates a dropdown for cloud — same UX as the rig model picker.
  Manual model entry in settings remains as a fallback.
- Compile-verified + APK built.

## What's new in 0.14.0
- **Chat UX overhaul** (Android). Fixes the status-bar collision (targetSdk 35
  forces edge-to-edge; the app now calls `enableEdgeToEdge()` and applies status /
  ime / navigation-bar insets) and turns the chat into a real messaging layout:
  **right-aligned blue user bubbles, left-aligned surface assistant bubbles**
  (~82% max width, tail corner), a blinking streaming cursor, a circular send
  button (Canvas-drawn arrow, no icon dep), model chip + source badge + Skift in
  the top bar, and a centered empty state. Compile-verified + APK built; the
  layout/insets are the on-device check.

## What's new in 0.13.0
- **Per-source system instructions** (Android): rig and cloud each get an optional
  multiline system prompt (`TokenStore.rigSystem` / `cloudSystem`), sent as the
  first `role:"system"` message on every request for that source. Set on the setup
  screen (saves as you type). Compile-verified + APK built; runtime is the usual
  on-device check (the prompt is just prepended to the existing, working message
  flow, so low risk). 0.12.0's cloud path was confirmed working on-device.

## What's new in 0.12.0
The point: **use the phone with cloud when the rig is off.**
- **Android direct Ollama Cloud** (`net/CloudClient.kt`): streams from
  `https://ollama.com/api/chat` with your account key — no rig needed. Setup screen
  now offers **rig and/or cloud**; if both are set, chat has a Rig/Cloud toggle.
- **Cloud key encrypted at rest** via AndroidKeystore AES-256-GCM (`data/Crypto.kt`),
  no external dependency.
- **Backend can also use cloud** (bonus): `MODELRIG_OLLAMA_KEY` → the proxy sends
  `Authorization: Bearer` to Ollama, so pointing `MODELRIG_OLLAMA_URL` at
  `https://ollama.com` makes the whole rig cloud-backed.

**Verified here:**
- The Android app **compiles and builds to a real APK** (full toolchain: JDK 21,
  Gradle 8.9, Android SDK 35). Compile-clean.
- The backend cloud path: with `MODELRIG_OLLAMA_KEY` set, a fake cloud that
  requires the bearer header received `Authorization: Bearer …` and the chat
  streamed through. Existing suite still green (90 assertions unchanged; proxy
  auth is a no-op when no key).

**NOT verified (needs your device + a real key):**
- That the app *runs* the cloud path end to end (streaming from ollama.com).
- That the **Keystore encrypt/decrypt** round-trips on a device (least-tested code
  — it compiles, but crypto only runs on-device). Failure is caught, not crashy:
  a save error shows a message rather than killing the app.
- Actual cloud model names / availability on your account.

## What's new in 0.11.0
- **Android UI overhaul** (source only, **not compiled here** — like all the
  Kotlin). Material 3 dark theme with the shared brand palette; custom top bar
  (model dropdown + overflow: clear / unpair); chat bubbles with auto-scroll and a
  streaming spinner; multiline input; Danish UI strings.
- **Dependency-free Markdown renderer** (`android/ui/Markdown.kt`): headings,
  bold/italic, inline code, fenced **code blocks with a copy button**,
  bullet/numbered lists, blockquotes, rules, styled links. No tables / deep
  nesting / images (swap `MarkdownText` for a CommonMark lib if needed). Chosen
  over a library specifically because it compiles deterministically without a
  version/API to get wrong — which matters since it can't be built here.
- Streaming + markdown interact deliberately: **plain text while streaming**, then
  **markdown once complete** (no re-parse per token, no half-open code fences).
- No new dependencies; backend + worker unchanged (version const bumped to 0.11.0
  so `/healthz` matches the release tag). **This is the biggest single chunk of
  unverified code in the repo — its first real test is your local Android build.**

## What's new in 0.10.0
- **Streaming RAG chat** — `POST /rag/chat` (proxied at `/api/v1/rag/chat`,
  CLI: `rag-chat`) retrieves context and then **streams** the answer, instead of
  the blocking synthesis path. The first NDJSON line is `{"sources":[…]}` (what
  context was used); the rest are Ollama chat deltas. Retrieval failure returns a
  clean 502 before the stream starts; a chat failure mid-stream is surfaced as a
  final `{"error":…}` line. Verified: worker reassembles the streamed answer, and
  the whole chain streams through the backend to the CLI (`stream-ok`, sources on
  stderr).
- Tests: **90 assertions**.

## What's new in 0.9.0
- **Token rotation** — `POST /api/v1/token/rotate` (CLI: `rotate`) re-issues the
  calling device's token without re-pairing; the old token stops validating
  immediately. For when a token leaks. Verified: new token works, old → 401, same
  device id.
- **Deep health** — `GET /api/v1/health/deep` (CLI: `doctor --deep`) actively
  round-trips: it lists Ollama models *and* asks the worker to embed a token
  (which calls Ollama), reporting `ok` + per-check latency. Proves the models
  respond, not just that ports are open. Verified both paths: all-green, and a
  dead Ollama surfaced as `worker error: cannot reach Ollama at … All connection
  attempts failed` with exit 1.
- Tests: **86 assertions**.

## What's new in 0.8.0
- **Source-filtered RAG query** — `POST /rag/query` accepts `source` to restrict
  retrieval to one source (CLI: `rag-query --source X`). Filtered in SQL.
- **CLI `doctor`** — one command checks backend reachability, token validity, and
  Ollama + worker health (via `/api/v1/status`), then prints a verdict and a
  concrete fix per failure. Exit code reflects health (0 green, 1 problem).
- **Request IDs + structured logging** — every request gets an `X-Request-ID`
  (or reuses an incoming one), returned to the client, **forwarded to upstreams**,
  and logged as `level=info req=… ip=… method=… path=… status=… dur_ms=…`. The
  worker logs the same id, so one request traces across both services. Verified in
  the e2e: a custom id appears in both the backend and worker logs.
- Tests: **76 assertions**. Both `doctor` paths (all-green and upstreams-down) and
  cross-service tracing are covered.

## What landed in 0.7.0
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
| Backend behaviour | **28** assertions: core smoke (11) + V1 (17, incl. token rotation) |
| Backend persistence | store JSON inspected: token hash stored, pairings emptied after single use |
| Worker imports & runs | FastAPI app loads; `/healthz` 200 |
| Worker logic | **34**: cosine, validation, 502, chunking, retrieval, source mgmt, source-filtered query, streaming RAG chat |
| **Integrated stack** | **28** e2e assertions: real backend + real worker + fake Ollama via the CLI; request-id tracing, `doctor --deep`, token rotation, streaming RAG chat |

**90 assertions total** via `sh tests/run_tests.sh`.

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
