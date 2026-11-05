# Media executor (G2 of #2296)

**Status:** default-off and not wired.
- Nothing imports `worker/app/media_executor.py`.
- No process starts it, and there is no route.
- Activation needs the production sinks and verifier (ChatGPT), a process supervisor (next slice) and the rig pack (#2296 6509723614).

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

## Exit codes

| Code | Meaning | Supervisor policy (next slice) |
|---|---|---|
| 0 | Done | — |
| 70 | GPU memory not proven free | Restart (the OS has freed it) |
| 73 | Another executor holds this GPU | Never restart in a loop |
| 75 | Media volume unavailable | Wait until the volume verifies |
| 76 | Publication not recorded (the artifact is durable; the job stays `publishing`) | Restart; recovery marks it `interrupted during publication` for the sink owner's reconciliation |
| 78 | Configuration | Stop |

## Not in this slice

- The process supervisor and the entry point. They need the production `ArtifactSink`, `StagedFileArtifactSink` and `VerifiedMediaVolume` (ChatGPT, #2313).
- Routes for submit/get/cancel (ChatGPT).
- Reconciliation itself: ChatGPT's read-only `inspect_generation_consistency` (#2313) classifies the recovered job. There is no automatic completion from file presence, and no inference retry.
- G3 pinning: ComfyUI version and weight manifest.
- Retiring `GenerationJobRunner`.
- **Assumed, to be verified on the pinned diffusers in rig R5:** every allowlisted pipeline honours `callback_on_step_end` and `_interrupt`.
