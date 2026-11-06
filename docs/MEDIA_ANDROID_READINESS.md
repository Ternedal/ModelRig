# Media on Android: readiness and the proposed job contract

**Status:** this is a proposal, not an agreement. The media routes belong to ChatGPT (#2275), and none of the job routes exist yet. This page states what the Android app needs from those routes, and what the branch `feat/android-media-job-readiness` already prepares.

Nothing here turns media on. Video stays default-off. There is no generation UI in the app: the new code is a parser, Danish texts and a polling rule, with tests.

## 1. What exists and what is missing

| Area | State |
|---|---|
| **Gallery (read)** | Agreed (`kaliv-media-gallery/v1`). The Android client, screen and player exist. |
| **Job status (read)** | **Missing.** The job store has seven states, and the store and executor write ten error strings once image-to-video lands, but no route exposes them. Android had no model, so the new `expired` state would have been unknown on the phone. |
| **Submit and cancel** | **Missing.** The route design is ChatGPT's to make. Open questions are in §6. |
| **Media capability probe** | **Missing.** See §4. |

## 2. Proposed read model: `kaliv-media-job/v1`

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

**Error strings.** The store writes two of them as sentences, not codes: `interrupted by restart` and `interrupted during publication`. Android maps them exactly as stored. If the route normalizes them into codes, both sides change together, and `tests/workflow_media_job_contract.py` fails until they match.

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

## 6. Open questions for the route owner

1. **Submit:** the response shape, and whether an `Idempotency-Key` is accepted. Without one, the app can never retry a submit after a timeout, because it cannot know whether the job was created.
2. **Queue-limit refusals:** `image job queue full` (16) and `owner image job limit reached` (3) are raised as `ImageJobError` text today. They need stable codes for the phone.
3. **Cancel:** a `queued` job cancels at once. A `running` job is marked for cancellation and stops later. Does the response return the job as it then stands?
4. **A list of the owner's jobs,** so the app can show the queue after it restarts. The phone keeps no job state of its own.
5. **Whether `publishing` is exposed** as its own state or folded into `running`. Android accepts both.

## 7. Evidence on this branch

| Check | What it covers |
|---|---|
| `tests/workflow_media_job_contract.py` | Fails when the store's states, its finished states, the executor's errors or the 24-hour expiry drift from the Kotlin model. Mutation-checked: deleting `expired`, a mapping or a sentence, or making `publishing` terminal, makes it fail. |
| `MediaJobContractTest`, `MediaJobPresentationTest` | JVM unit tests for parsing, presentation and polling. |
| Release build, without signing | `./gradlew :app:compileReleaseKotlin` compiles the release variant. The signed APK is a release step and needs Anders (§2). |
