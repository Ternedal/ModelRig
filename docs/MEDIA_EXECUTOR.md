# Media executor (G2 of #2296)

**Status:** default-off.
- The API worker never imports `worker/app/media_executor.py` (boundary test).
- With G2b the appliance's Go `modelrig-supervisor` can start one executor per GPU, but only when `KALIV_MEDIA_EXECUTOR=1` and the configuration below is complete. Off by default; a refused configuration starts nothing.
- Images only, published job-keyed through `ExternalMediaSink`. Video is refused (exit 78) until a staged video sink exists.
- Activation on the rig needs the rig pack (#2296 6509723614) and Anders' go.

Sources:
- Design: #2296 6510332634.
- Reviews closed: 6511335742, 6512440682 and 6513576382.
- Prototype evidence: branch `design/media-executor-g2-20261029`.

## Why a separate process

`GpuResourcesRetained` means one thing: exit, so the OS frees the VRAM and the GPU lease. The FastAPI worker must never be the process that does that.

## Rules

| Rule | Where | Test |
|---|---|---|
| One executor per GPU, proven before recovery | `gpu_lease.acquire_executor_lock` in `start()` | `test_a_second_executor_for_the_same_gpu_refuses_before_touching_any_claim` (real second process) |
| Claims carry a per-process instance (`<UUID>:<16 hex>`); every transition requires it | `ImageJobStore.claim_for/begin_publish/complete/fail/finish_cancelled` | store `ExecutorProtocolTests` |
| Claims only for this executor's profiles | `claim_for` | `test_each_executor_claims_only_its_own_profiles…` |
| Recovery fails only this GPU's dead instances | `recover_gpu` | `test_recovery_fails_only_this_gpus_dead_instances…` |
| One resident adapter; a switch is a proven unload, then a load | `_adapter_for` | `test_switching_profiles_unloads_first_then_loads` |
| Any unload failure is fatal (`False` or an exception): adapter kept, exit 70, no further claim or load | `_unload`, `step` | three tests |
| Idle unload frees the GPU for processes outside the lease | `maybe_unload_idle` | `test_idle_unload_frees_the_gpu_for_others` |
| Video only through `staged()`/`adopt()` | `step` | `test_config_refuses_video_without_a_staged_sink`, video end-to-end |
| Commit point: a cancel before `begin_publish` wins; afterwards `"too_late"` | `begin_publish` | image and video barrier tests |
| Cooperative cancel of a running job | `should_cancel`: ComfyUI poll loop (interrupt, then drain the queue); diffusers `callback_on_step_end` | adapter tests and executor video cancel |
| Missing volume is fatal: exit 75, the job is left for recovery, no other disk | `step`/`run` | `test_missing_volume_exits_75…` |
| A GPU held by another lease-taker fails the job as `gpu_busy`; the executor continues | `step` | `test_a_gpu_held_by_another_lease_taker…` |
| Stored errors are fixed codes, never exception text | `step` | `test_job_errors_are_fixed_codes_never_exception_text` |
| `publishing` counts toward the owner's limit | `submit` | `test_publishing_counts_toward_the_owner_limit` |
| Concurrent initialisers serialise the migration | `ImageJobStore.__init__` (`BEGIN IMMEDIATE` spans inspection and `ALTER`) | `test_concurrent_initialisers_serialise_the_migration` (barrier at the schema read) |
| A failed load continues only if `close()` proves the release; otherwise the adapter is retained and the exit is 70. `GpuResourcesRetained` from `load()` is always fatal | `_adapter_for` | three partial-load tests |
| Publication is job-keyed when the sink offers it (`JobKeyedArtifactSink`, `JobKeyedStagedSink`) | `step`, `GenerationJobRunner` | image, video and real `ExternalMediaSink` tests |
| A durable artifact whose completion write fails stays `publishing`, exit 76, then `interrupted during publication` | `step` | `test_a_durable_artifact_whose_completion_fails…`, `test_restart_reconciliation_with_the_real_gallery_sink` |
| A failure after the commit point is `publication_failed`, not `generation_failed` | `step` | `test_a_publication_error_after_the_commit_point…` |
| The executor lock is released on every terminal path of `run()`; a retained adapter's GPU lease is not | `run`, `ExecutorLock.release` | `test_run_releases_the_executor_lock_on_every_exit_path` |
| A ComfyUI whose interrupt is not confirmed drained (deadline, interrupt or queue check failed) sets `needs_restart`; the executor unloads it with proof before claiming again | `ComfyVideoAdapter._interrupt_and_drain`, `step` | `test_an_unconfirmed_drain_marks_the_adapter_for_restart`, `test_a_comfyui_whose_cancel_did_not_drain_is_restarted_before_the_next_job` |
| A failing database never replaces the fatal GPU exit | `_record_failure` | `test_gpu_retained_still_exits_70_when_the_failure_cannot_be_recorded` |

## Sharing the GPU with Ollama (G4)

**Decision (Anders, 5 Nov 2026): chat first, media waits.** Ollama is outside the GPU lease and is never touched.
- **When there is too little free VRAM**, the job goes back to `queued` with its claim cleared, instead of failing. This is checked by `inspect_cuda_budget` for diffusers, and by ComfyUI's `/system_stats` at start and before every job. Nothing has been submitted yet, and a refused load has proved its release.
- **Nothing resident while waiting.** If the shortage came from a model that was already loaded (ComfyUI's pre-job check), the executor unloads it at once, with the usual proven release, instead of waiting for the idle unload. The job is requeued first, so a failed unload (exit 70) never strands it. (Codex 4477938515.)
- **Back-off.** The executor claims nothing for `VRAM_RETRY_S` (30 s) and then tries again.
- **Bound.** After `VRAM_MAX_WAIT_S` (10 min), counted from the job's first deferral (`deferred_since`), the job fails as `gpu_unavailable`.
- **Cancel.** A cancel requested while the job was running wins: the job is `cancelled`, not requeued.
- **Not waited for:** other admission failures (a missing GPU, an identity mismatch) still fail the job at once, and `gpu_busy` (another lease-taker) is unchanged.
- **Media yields too:** the idle unload (`KALIV_MEDIA_IDLE_UNLOAD_S`, default 300 s) frees the GPU for chat.

## Job states

```
queued --claim_for--> running --begin_publish--> publishing --complete--> completed
                      running/publishing --fail--> failed
                      running --finish_cancelled--> cancelled      (after request_cancel)
                      running --defer (VRAM short)--> queued        (G4; failed "gpu_unavailable" after 10 min)
recovery:  running    -> failed "interrupted by restart"
           publishing -> failed "interrupted during publication"   (an asset may exist: the sink reconciles)
```

The migration is additive: `claimed_by` and `cancel_requested`. The legacy API (`claim`/`finish`/`cancel`/`recover_interrupted`) still serves `GenerationJobRunner`.

## Prompt retention

**Decision (Anders, 5 Nov 2026):** a finished job's prompt is blanked 30 days after it finished.
- **Finished** means `completed`, `failed` or `cancelled`. Queued, running and publishing jobs keep their prompt, because it is still needed.
- **What stays.** The row stays: id, owner, state, asset and error. The gallery and the audit trail still resolve; only the user's text goes. An empty prompt means "purged", because `submit` never accepts an empty one.
- **How.** Every store connection turns on `PRAGMA secure_delete` before it writes, and refuses to work if the build ignores it. That matters for more than the purge: a state transition can move a row and free the old copy of its prompt, and with secure_delete off that copy would stay readable in free space where no later `UPDATE` reaches it (Codex 4477941179). Some builds have it on by default; the store does not rely on that.
- **Scrub.** A purge that blanked anything owes a scrub, and so does the first open of a database created before this version. `purge_prompts()` pays an owed scrub with `VACUUM`, which rebuilds the file with no free space left. The rebuild uses an in-memory temp database (`temp_store=MEMORY`), so no copy goes to the system temp directory. The debt is a counter in `image_jobs_scrub`, committed in the same transaction as the blanking, so a failed `VACUUM` is retried on the next call.
- **When.** The executor runs it at start and then at most once an hour while idle. A failure is recorded and retried, and is never fatal to GPU work.
- **WAL.** If the database is in WAL mode (another connection may switch it), the old pages live on in the `-wal` file until a checkpoint. After a purge the store runs `wal_checkpoint(TRUNCATE)`, which also empties that file. In the default rollback-journal mode this is a no-op.
- **Stated limit, no promise of physical erasure.** SQLite cannot reach copies outside the database and WAL files: backups, filesystem snapshots, deleted rollback journals (including the one a `VACUUM` writes in rollback-journal mode) and SSD remapping. A checkpoint can also be blocked by a long-lived reader; the next hourly purge retries. Prompts never go to logs.

## Starting it (G2b, #2296 6636146026)

`modelrig-supervisor` starts, per device, after the worker and the server:

```
<KALIV_MEDIA_EXECUTOR_PYTHON> -u -m app.media_executor_main --device cuda:N     (working directory: KALIV_MEDIA_EXECUTOR_APP_DIR)
```

Each executor runs in the supervisor's process tree (a Windows Job Object), so stopping the supervisor stops it. Its output goes to `logs/executor-cudaN.log`, size-rotated like the worker's.

| Variable | Read by | Meaning |
|---|---|---|
| `KALIV_MEDIA_EXECUTOR=1` | supervisor, executor | Master switch. Any other value is off. |
| `KALIV_MEDIA_EXECUTOR_DEVICES` | supervisor | `cuda:0` or `cuda:0,cuda:1`; at most 8, no duplicates |
| `KALIV_MEDIA_EXECUTOR_PYTHON` | supervisor | Absolute path of the media environment's `python.exe` (torch and diffusers are not in the frozen worker) |
| `KALIV_MEDIA_EXECUTOR_APP_DIR` | supervisor | Absolute path of the directory that contains `app/media_executor_main.py` |
| `KALIV_MEDIA_WORK_ROOT` | executor | The private work area on the internal disk, where media is generated and the job database lives (Anders, 6 Nov; `docs/MEDIA_WORK_AREA.md`). Missing, not private, a network drive or on the media volume: exit 78 |
| `KALIV_MEDIA_JOB_DB` | executor, routes | Absolute path of the job SQLite, in an existing folder inside the work area (else exit 78). The routes must run as the same account as the executor: nobody else can read the work area |
| `KALIV_MEDIA_ROOT`, `KALIV_MEDIA_VOLUME_ROOT` | executor, gallery | Media directory and the verified volume root (`ExternalMediaSink`) |
| `KALIV_MEDIA_VOLUME_ID` | executor | The id in `<volume root>/.kaliv-media-volume` (G1, `docs/MEDIA_VOLUME.md`). Missing or malformed: exit 78. Wrong disk: exit 75 |
| `KALIV_MEDIA_PROFILE_DIR` | executor | Operator profile directory |
| `KALIV_MEDIA_IDLE_UNLOAD_S` | executor | Optional; default 300 |
| `KALIV_MEDIA_PROFILES_ENABLED`, `KALIV_MEDIA_ALLOW_CANDIDATE_PROFILES`, `KALIV_GPU_LEASE_DIR`, `KALIV_GPU_DEVICE_UUIDS`, `CUDA_DEVICE_ORDER`, `HF_HUB_OFFLINE`, `TRANSFORMERS_OFFLINE` | executor | Existing |

The supervisor reads them the way the children see them: the env file (`modelrig.env`) wins over its own environment.

The entry point checks the configuration before it touches anything, including the GPU lease directory: one that is relative, missing, a symlink or writable by others is exit 78, not a crash. The work area and then the volume are verified before the job database is first opened and again before every later database access, so a volume that goes away, or a work area that changes, while the executor runs stops it (exit 75) before it claims another job (#2337 reviews 4477083816, 4477083808). A diffusers profile also requires `HF_HUB_OFFLINE=1` and `TRANSFORMERS_OFFLINE=1` at configuration time: without them it is exit 78 and the queue is untouched, instead of every claimed job failing at load (#2337 review 4477167705). An existing job database must be a regular SQLite file: a directory, a link (which could lead out of the work area), a FIFO or a file that is not SQLite is exit 78 (#2337 review 4477759300); a locked database stays a transient exit 1. A missing directory is never created.

## Exit codes and the supervisor's policy

`executorRestartPolicy` in `backend/cmd/modelrig-supervisor/executor.go`; every code is unit-tested, and real child processes prove that the code the policy sees is the code the child gave.

| Code | Meaning | Policy |
|---|---|---|
| 0 | Done | Not restarted until the supervisor restarts |
| 70 | GPU memory not proven free | Restart after 5 s (the OS has freed it with the process) |
| 73 | Another executor holds this GPU | **Never** restarted; logged once |
| 75 | Media volume unavailable (also: not there at start) | Restart after 30 s; the executor re-verifies on every start |
| 76 | Publication not recorded (the artifact is durable; the job stays `publishing`) | Restart after 5 s; recovery marks it `interrupted during publication` for the sink owner's reconciliation |
| 78 | Configuration refused (including the switch off) | **Never** restarted; logged once |
| other, or killed | Crash | Restart after 5 s |

Every restartable code doubles its delay for each exit in a row, capped at 5 minutes. A run of at least 5 minutes resets the streak. An executor has no HTTP endpoint: alive is healthy, so it is never restarted for health.

## Not in this slice

- Video through the executor: it needs ChatGPT's staged video sink (`JobKeyedStagedSink`).
- A public "verify the volume" method on `ExternalMediaSink`: the entry point calls its `_root()` at start so a missing volume is exit 75 before anything is opened (ChatGPT owns the sink).
- Routes for submit/get/cancel (ChatGPT).
- Reconciliation itself: ChatGPT's read-only `inspect_generation_consistency` (#2313) classifies the recovered job. There is no automatic completion from file presence, and no inference retry.
- G3 pinning: ComfyUI version and weight manifest.
- Retiring `GenerationJobRunner`.
- **Assumed, to be verified on the pinned diffusers in rig R5:** every allowlisted pipeline honours `callback_on_step_end` and `_interrupt`.
