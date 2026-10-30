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

## Job states

```
queued --claim_for--> running --begin_publish--> publishing --complete--> completed
                      running/publishing --fail--> failed
                      running --finish_cancelled--> cancelled      (after request_cancel)
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
| 78 | Configuration | Stop |

## Not in this slice

- The process supervisor and the entry point. They need the production `ArtifactSink`, `StagedFileArtifactSink` and `VerifiedMediaVolume` (ChatGPT, #2313).
- Routes for submit/get/cancel (ChatGPT).
- Asset reconciliation after a crash while publishing (sink side).
- G3 pinning: ComfyUI version and weight manifest.
- Retiring `GenerationJobRunner`.
- **Assumed, to be verified on the pinned diffusers in rig R5:** every allowlisted pipeline honours `callback_on_step_end` and `_interrupt`.
