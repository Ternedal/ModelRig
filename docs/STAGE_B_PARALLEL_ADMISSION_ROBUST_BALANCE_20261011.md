# Parallel Stage-B admission + robust downstream partition — EXPERIMENT

**DRAFT ONLY. No V1 main mutation, no release, no production activation.**

This attempt is stacked onto **fully-green [parallel admission draft #2122](https://github.com/Ternedal/ModelRig/pull/2122)**, with the same independently executing full admission-prefix and focused nonce-reuse guard. Both are still prerequisites of all Stage-B shards. The frozen ModelRig V1 SHA is
`0b2ff455116f4f28a1a41704d9cb81503f17d2df`.

## Current measured, fully green reference

- [#2122 run 38089952531](https://github.com/Ternedal/ModelRig/actions/runs/38089952531) took 12,195 seconds (3h23m15s) from admission start through final shard; all 10 jobs PASS.
- [#2122 run 38089960759](https://github.com/Ternedal/ModelRig/actions/runs/38089960759) took 12,905 seconds (3h35m05s); all 10 jobs PASS.
- [Frozen V1 run 37845235363](https://github.com/Ternedal/ModelRig/actions/runs/37845235363) took 16,160 seconds (4h29m20s).
- Security-mirror #2123 Go+Python CodeQL, both normal CI runs, every canonical contract and prior exact-head checks were green. No permission or timeout was weakened.

## New scheduling-only change

Only downstream task order and which of the three existing shards
receives each of the **same original 31 full security contracts** changes.
The previous strided distribution (11/10/10 contracts) becomes
measured-cost balanced (10/10/11). Each shard still starts **at most two
isolated subprocesses** and retains original **2400-second normal and
3600-second targeted deep per-file hard timeout**, while each Stage-B
GitHub job retains the original hard job bound and exact-head cache checks.
The original unsharded execution path remains completely unchanged.

The model's per-file inputs were calculated exclusively from the
**31 contract-level PASS durations** present in each of these five
fully-green original job-log sets:

- 37982695916: 114028089322, 114028089336, 114028089364
- 38081640622: 114313721674, 114313721567, 114313721600
- 38081628439: 114329340864, 114329340802, 114329340771
- 38089952531: 114333866615, 114333866546, 114333866590
- 38089960759: 114338484180, 114338484223, 114338484236

All logs are pinned in `REFERENCE_LOG_JOB_IDS`. For each contract,
`COST_SECONDS = round(0.70 × mean(across five green runs) + 0.30 × max(across five green runs))`.
The deterministic largest-cost-first planner distributes tasks to the
smallest projected two-process makespan using the same original executor.
The five fully-green trials provided all 31 timings, no source missing.

Predicted worker burdens on the new static schedule (seconds):

- downstream-1: 8746 / 8199
- downstream-2: 8343 / 8203
- downstream-3: 8425 / 8975

**Modeled maximum: 8,975 seconds. This is NOT yet verified.**

Retrospective replay of per-file timing observations gives worst-shard
values **8,018 / 9,384 / 8,022 / 7,879 / 9,827 seconds** compared with
**9,611 / 9,383 / 8,738 / 9,078 / 10,242 seconds** using the old
strided queue on the same replay. Those are *in-sample, counterfactual*
simulations, not independent hosted-runner measurements. Different
shards change contention and can erase that apparent advantage.
No reduction in processing time is claimed until measured at exact HEAD.

The complete source inventory and invalid-plan values fail closed.
The targeted `post_release_attestation_contract` took about 3,530 seconds
in one green run, **only ~70 seconds below its unchanged 3,600-second
hard limit**. That makes full real runner qualification critical; no
timeout extension is authorized.

## Required acceptance

1. All fast workflow tests, Python lint, Go tests, standard CI and
   exact-head core succeed on the precise new SHA.
2. Both Go and Python CodeQL succeed on the **same exact SHA/tree**,
   using a main-targeted **draft-only security mirror** if needed.
3. At least two independent complete real Stage-B exact-head runs:
   canonical full prefix + nonce jobs, all 3 midchain and all 3
   downstream jobs PASS, with unchanged original hard timeouts.
4. Compare actual admission→last-shard wall (baseline #2122
   12,195 / 12,905 s), critical shard, total runner-minutes, and
   timeout headroom. Do not promote if speed is unstable, timeout
   risk worsens or runner cost outweighs the benefit.
5. Freeze and pending physical/admin V1 release gates stay intact.
   No merge, tag, unreviewed main write, reduction of provenance
   checks, synthetic PASS or production activation.

**This optimizes Stage-B qualification, not local Ollama inference.
Those are two separate performance bottlenecks.**
