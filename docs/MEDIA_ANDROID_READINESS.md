# Media on Android: readiness and the proposed job contract

**Status:** ChatGPT accepted the read model in §2 (#2275 6693665083). Submit, cancel, list and the capability probe are design targets, not agreed shapes. The routes belong to ChatGPT, and none exists yet. This page states what the Android app needs from those routes, and what the branch `feat/android-media-job-readiness` already prepares.

Nothing here turns media on. Video stays default-off. There is no generation UI in the app: the new code is a parser, Danish texts and a polling rule, with tests.

## 1. What exists and what is missing

| Area | State |
|---|---|
| **Gallery (read)** | Agreed (`kaliv-media-gallery/v1`). The Android client, screen and player exist. |
| **Job status (read)** | **Missing.** The job store has seven states, and the store and executor write ten error strings once image-to-video lands, but no route exposes them. Android had no model, so the new `expired` state would have been unknown on the phone. |
| **Submit and cancel** | **Missing.** The route design is ChatGPT's to make. Open questions are in §6. |
| **Media capability probe** | **Missing.** See §4. |

## 2. Read model: `kaliv-media-job/v1` (accepted)

```
GET /api/v1/media/jobs/{job_id}        (owner only; another owner's job is 404, as in the gallery)
200 {"schema":"kaliv-media-job/v1","job":Job}

Job = {
  "id":         string   [A-Za-z0-9_-]{1,128} (the store uses uuid4().hex)
  "state":      "queued"|"running"|"publishing"|"completed"|"failed"|"cancelled"|"expired"
  "profile_id": string   [a-z0-9][a-z0-9-]{0,47}
  "created_at": RFC 3339 UTC ("…Z")
  "updated_at": RFC 3339 UTC, never before created_at
  "expires_at": RFC 3339 UTC, after created_at, when state is "queued"; otherwise null
  "asset_id":   gallery id when state is "completed"; otherwise null
  "error":      the stored error when state is "failed" or "expired"; otherwise null
}
```

**Never in the response:** the prompt, `params`, `owner`, `claimed_by` (it names the GPU and executor instance) and `cancel_requested`. Android ignores unknown fields, so adding one later is safe.

**`expires_at`** is the store's `created + QUEUED_MAX_AGE_S`. It comes from the server, so the phone never works out expiry from its own clock. The store expires lazily in `get()`, so the route already returns `expired` for a stale job, even with media off.

**Error codes.** Restart recovery now writes `interrupted_by_restart` and `interrupted_during_publication` (wiring branch). Rows from earlier builds keep the sentences `interrupted by restart` and `interrupted during publication`: nothing rewrites stored errors. `image_job_store.public_error()` maps both forms to the codes, so the route sends codes only. Android accepts both anyway, with the same text for a sentence and its code.

## 3. What Android checks (fail-closed)

`MediaJobContract.parse` checks every invariant the store holds. A job that breaks one is a protocol error; it is never shown with a guessed status.

| Field | Rule |
|---|---|
| **state** | Must be one of the seven. An unknown state is refused, so a new terminal state can never be polled forever or shown as success. |
| **asset_id** | Present exactly when the state is `completed`. |
| **error** | Present exactly when the state is `failed` or `expired`. For `expired` it must be `expired_unclaimed`. |
| **expires_at** | Present exactly when the state is `queued`. |
| **timestamps** | UTC only, and ordered. |

The server's error text is never shown verbatim. A known error gets its Danish text; anything else becomes "Jobbet fejlede."

## 4. The capability probe must fail closed

`WorkerCapabilities` deliberately fails *open*: a missing answer means "available", so an older rig never loses working buttons. Media generation needs the opposite rule. It is default-off and a high-risk feature, so the phone may offer it only when the rig says **explicitly** that it is on, for each kind:

- text to image;
- text to video;
- image to video.

A missing, unreadable or unknown answer hides the feature. Where the flag lives is the route owner's choice. Putting it in `/capabilities` as nested booleans would be ignored by today's parser, which reads only top-level booleans. That is harmless, but it is not the fail-closed reader; this needs its own small parser.

## 5. UX rules prepared on the branch

**Retry.** Every error has one of four retry classes (`MediaJobPresentation.ERRORS`):

| Retry | Errors | Meaning |
|---|---|---|
| `RESUBMIT` | `expired_unclaimed`, `generation_failed`, `publication_failed`, both restart sentences | Sending the same request again is reasonable. |
| `LATER` | `gpu_busy`, `gpu_unavailable`, `gpu_memory_retained` | The rig is busy, or must restart first. |
| `FIX_INPUT` | `generation_request_rejected`, `source_image_unavailable` | Change the request first. |
| `NONE` | completed, cancelled | Nothing to retry. |

**The app never resubmits on its own.** No idempotency key exists, so an automatic resubmit could run (and cost) a generation twice.

**Polling** (`MediaJobPolling`):

- It starts at 2 s and doubles, up to these caps:

  | Situation | Cap |
  |---|---|
  | `running` or `publishing` | 15 s |
  | `queued` | 60 s (a job can wait hours for the GPU) |
  | after a failed request | 120 s |

- It stops at any terminal state.
- After a state change the count restarts, so the next poll comes quickly.

**Offline and reconnect.** These are rules for the future screen, not yet code:

- Keep the last known job on screen, marked as not current, and keep polling at the offline cap.
- On reconnect, poll at once.
- The phone keeps no job state of its own besides the job id.
- Reaching the rig follows the gallery client: pairing, origin check, and no redirects.

**Gallery lifecycle.** A completed job's `asset_id` opens the gallery item through the existing gallery path. The item may already be gone, for example after a repair. Then the gallery's own `NOT_FOUND` text applies; the job still says completed.

## 6. Design targets for the routes (ChatGPT's, not implemented)

The shared examples are in `docs/contracts/kaliv-media-job-v1/`: `fixtures.json` (24 exchanges) and `openapi.json` (a short OpenAPI 3.1 sketch). Both sides test against the same file.

| Operation | Target (#2275 6693665083) |
|---|---|
| **Submit** `POST /api/v1/media/jobs` | `201`, the job and `Location`. An owner-scoped `Idempotency-Key`: an identical retry returns the original response (`Idempotent-Replayed: true`); a different payload under the same key is `409 idempotency_conflict`. The key is stored atomically with the job, with bounded length and retention, and never logged with the prompt. |
| **Refusals** | `429 queue_full` (with `Retry-After`), `429 owner_active_limit`, `400 invalid_request`, `503 media_disabled`. Codes, never exception text. |
| **Cancel** `POST …/{id}/cancel` | Idempotent. `200` with `outcome` (`cancelled`, `requested`, `too_late`: the store's own answers) and the job as it now stands. |
| **List** `GET /api/v1/media/jobs` | Owner only, newest first, at most 50 a page, opaque cursor, never prompt or params. |
| **Capabilities** `GET /api/v1/media/capabilities` | One explicit boolean per kind; anything else hides the kind (§4). Where it lives is ChatGPT's choice. |
| **404** | Another owner's job and an unknown id answer alike (`not_found`). |

**`publishing` stays its own state.** The app never resubmits on its own, before or after the idempotency key exists.

## 7. Evidence on this branch

| Check | What it covers |
|---|---|
| `tests/workflow_media_job_contract.py` | Fails when the store's states, its finished states, the executor's errors, the restart codes and their sentences, or the 24-hour expiry drift from the Kotlin model. Mutation-checked: deleting `expired`, a mapping or a sentence, or making `publishing` terminal, makes it fail. |
| `tests/workflow_media_job_fixtures.py` | Checks every fixture against the store's invariants, the public codes, the store's cancel answers and the OpenAPI paths, and that no prompt, params, owner or claim is ever returned. Mutation-checked. |
| `MediaJobContractTest`, `MediaJobPresentationTest`, `MediaJobFixturesTest` | JVM unit tests for parsing, presentation and polling; the fixture test parses every job in `fixtures.json` on the phone side. |
| Release build, without signing | `./gradlew :app:compileReleaseKotlin` compiles the release variant. The signed APK is a release step and needs Anders (§2). |
