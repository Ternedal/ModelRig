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

## Job states

```
queued --claim_for--> running --begin_publish--> publishing --complete--> completed
                      running/publishing --fail--> failed
                      running --finish_cancelled--> cancelled      (after request_cancel)
recovery:  running    -> failed "interrupted by restart"
           publishing -> failed "interrupted during publication"   (an asset may exist: the sink reconciles)
```

The migration is additive: `claimed_by` and `cancel_requested`. The legacy API (`claim`/`finish`/`cancel`/`recover_interrupted`) still serves `GenerationJobRunner`.

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
| `KALIV_MEDIA_JOB_DB` | executor, routes | Absolute path of the job SQLite |
| `KALIV_MEDIA_ROOT`, `KALIV_MEDIA_VOLUME_ROOT` | executor, gallery | Media directory and the verified volume root (`ExternalMediaSink`) |
| `KALIV_MEDIA_PROFILE_DIR` | executor | Operator profile directory |
| `KALIV_MEDIA_IDLE_UNLOAD_S` | executor | Optional; default 300 |
| `KALIV_MEDIA_PROFILES_ENABLED`, `KALIV_MEDIA_ALLOW_CANDIDATE_PROFILES`, `KALIV_GPU_LEASE_DIR`, `KALIV_GPU_DEVICE_UUIDS`, `CUDA_DEVICE_ORDER`, `HF_HUB_OFFLINE`, `TRANSFORMERS_OFFLINE` | executor | Existing |

The supervisor reads them the way the children see them: the env file (`modelrig.env`) wins over its own environment.

The entry point checks the configuration before it touches anything, including the GPU lease directory: one that is relative, missing, a symlink or writable by others is exit 78, not a crash. The volume is verified before the job database is first opened and again before every later database access, so a volume that goes away while the executor runs stops it (exit 75) before it claims another job (#2337 reviews 4477083816, 4477083808). A diffusers profile also requires `HF_HUB_OFFLINE=1` and `TRANSFORMERS_OFFLINE=1` at configuration time: without them it is exit 78 and the queue is untouched, instead of every claimed job failing at load (#2337 review 4477167705). A missing directory is never created.

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
