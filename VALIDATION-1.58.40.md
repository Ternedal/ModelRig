# VALIDATION-1.58.40 — P1 hardening

> **Scope:** branch `agent/p1-hardening-1-58-40`, draft PR #3, based on
> `main` version 1.58.40. This file separates automated evidence from tests that
> require Anders' Windows rig, Pixel 6a, real network and release channel.
>
> **Rule:** an empty manual result is not a pass. CI-green is not on-device proof.

## Test context

| Field | Value |
|---|---|
| Base version | 1.58.40 |
| Draft PR | #3 — `fix: harden pairing, streaming, uploads and releases` |
| Windows rig | RTX 3060 12 GB — manual result pending |
| Phone | Pixel 6a — manual result pending |
| Worker launch | must be `app.entrypoint:app` or packaged `run_worker.py` |

## Automated evidence

### A. Pairing/store ownership

| # | Assertion | Evidence | Result |
|---|---|---|---|
| A1 | Store path is resolved before the `-pair` branch | `backend/cmd/modelrig-server/main.go` | ✅ code + build |
| A2 | Any HTTP response, including 503, proves the live server owns the port/store | `TestServerReachableCountsAnyHTTPResponse` | ✅ Go test |
| A3 | Reachable server + failed `/pair/start` never falls back to a second JSON writer | `TestPairCLIRefusesSecondWriterWhenServerIsReachable` | ✅ Go test |
| A4 | Genuinely offline pairing writes the explicitly configured store | `TestPairCLIOfflineWritesTheConfiguredStore` | ✅ Go test |

### B. Request body and voice-temp boundary

| # | Assertion | Evidence | Result |
|---|---|---|---|
| B1 | Oversized chunked/no-length body is rejected before FastAPI receives it | `tests/worker_hardening.py` | ✅ |
| B2 | Bounded chunked body is replayed exactly once | `tests/worker_hardening.py` | ✅ |
| B3 | Honest oversized `Content-Length` fails before body parsing | `tests/worker_hardening.py` | ✅ |
| B4 | Voice temp directory is removed after the final response frame | `tests/worker_hardening.py` | ✅ |
| B5 | Packaged exe, batch, PowerShell and systemd launch the hardened entrypoint | launcher files + compile/smoke CI | ✅ |

### C. Desktop terminal-stream contract

| # | Assertion | Evidence | Result |
|---|---|---|---|
| C1 | Chat EOF without `done=true` is an interrupted response, not success | `OllamaClient.chatStream` | ✅ compile |
| C2 | Malformed/error NDJSON is surfaced | `OllamaClient.chatStream` | ✅ compile |
| C3 | Model pull requires terminal `status=success` | `OllamaClient.pullModel` | ✅ compile |
| C4 | Model pull verifies the model appears in `/api/v1/models` or `/api/tags` | `OllamaClient.pullModel` | ✅ compile |
| C5 | Desktop pull timeout matches backend's two-hour ceiling | `OllamaClient.pullModel` | ✅ compile |

### D. Draft-first release contract

| # | Assertion | Evidence | Result |
|---|---|---|---|
| D1 | Exactly one job may create a release | `tests/workflow_release.py` | ✅ |
| D2 | A new or pre-existing release is draft before parallel uploads | workflow + contract test | ✅ |
| D3 | Draft-authority job has explicit repository context | checkout + contract test | ✅ |
| D4 | Complete `.apk`, `.jar`, `.zip`, `.exe` and checksum set is verified while still draft | workflow + contract test | ✅ |
| D5 | Exactly one final transition publishes and marks latest | workflow + contract test | ✅ |

### E. CI checkpoints

Every implementation class was stopped and verified before the next was added.
The latest code checkpoint completed successfully in GitHub Actions run
`29473488627`:

- shared backend/worker/integration/workflow tests: ✅
- Go build + vet + backend tests: ✅
- Python lint gate: ✅
- Windows-native updater/supervisor tests: ✅
- desktop compile: ✅
- Android compile + JVM unit tests: ✅

## Manual/on-device validation — required before calling the hardening released

Fill **Result** with ✅ / ❌ / ⏭️ and add concrete notes.

### 1. Offline pairing from a foreign working directory

| Step | Expected | Result | Note |
|---|---|---|---|
| Stop backend | No process on :8080 | | |
| Open PowerShell in another directory, run the absolute `modelrig-server.exe -pair` path | Code is printed | | |
| Start backend normally through launcher | Same store is opened | | |
| Claim the code on Pixel 6a | Pairing succeeds | | |

### 2. Worker body limit

| Step | Expected | Result | Note |
|---|---|---|---|
| Start worker via `app.entrypoint:app` | `/healthz` answers | | |
| Send a normal ingest | Accepted | | |
| Send a chunked body above `KALIV_MAX_UPLOAD_MB` without `Content-Length` | HTTP 413; worker remains healthy; no large RSS spike | | |

### 3. Voice privacy and cancellation

| Step | Expected | Result | Note |
|---|---|---|---|
| Record and complete one voice turn | Works normally | | |
| Inspect `%TEMP%` after completion | No `alva_voice_*` directory remains | | |
| Start voice and press Stop mid-stream | Audio/network stops; temp directory removed after cancellation | | |
| Run voice ×10 | No accumulated temp dirs and no increasing orphaned disk usage | | |

### 4. Desktop stream/pull truthfulness

| Step | Expected | Result | Note |
|---|---|---|---|
| Run a normal streamed desktop chat | Completes normally | | |
| Interrupt network mid-chat after visible text | Error/partial state; never ordinary completed answer | | |
| Pull a small model | Ends only after success + installed-list verification | | |
| Interrupt a large pull mid-stream | Concrete failure; UI never says `Færdig` | | |

### 5. Release-channel proof

Perform with the first intentional release tag after merge.

| Step | Expected | Result | Note |
|---|---|---|---|
| Push bare release tag | A private draft is created before upload jobs run | | |
| Inspect release while builds run | Not public and not `latest` | | |
| Let all jobs complete | All required assets + `SHA256SUMS.txt` exist | | |
| Final publish step | Release becomes public/latest once, after verification | | |

## Explicitly not closed by this PR

These remain real follow-up work; the PR must not claim otherwise:

1. **Android chat/RAG/voice EOF contract.** Android model pull is strict, but
   ordinary chat, RAG and voice still need one shared terminal NDJSON reader.
2. **Android send/retry execution duplication.** `TurnRouter` centralises route
   flags, not execution/finalisation; proposal bubbles and fallback metadata can
   still differ between send and retry.
3. **Voice persistence authority in Android.** The database should persist the
   terminal `done.reply`, not only the concatenated sentence-chunk buffer.
4. **Tool `pull_model` job state.** Agent v2 still starts a best-effort daemon
   thread without persistent progress/failure/cancellation.
5. **RAG transactional ingest and scaling.** Separate next RAG hardening lane.
6. **Agent 3.0.** Must stay isolated and be rebased/split after this baseline.

## Merge/release gate

- [x] Each code checkpoint green before next checkpoint
- [x] Latest shared CI green across all four jobs
- [x] New bug classes have automated regression contracts where feasible
- [ ] Manual pairing test passed
- [ ] Manual voice-temp/cancellation test passed
- [ ] Manual desktop interrupted-stream/pull test passed
- [ ] First real tag proves draft → verify → publish flow
- [ ] Version bumped consistently when cutting the release

**Current verdict:** code-review ready as a **draft hardening PR**. Not yet
hardware- or release-channel-proven, and therefore not honestly “done on rig”.
