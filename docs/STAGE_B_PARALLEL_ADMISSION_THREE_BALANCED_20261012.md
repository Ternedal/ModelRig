# EXPERIMENT: measured-cost 3x2 downstream rebalance + green parallel admission

**DRAFT, UNMERGED, no V1 release authority.** Baseline branch is
[#2122](https://github.com/Ternedal/ModelRig/pull/2122): two independent
full exact-head GREEN runs, including both original mandatory admission
security phases and all six original Stage-B shard jobs. Frozen main is
`0b2ff455116f4f28a1a41704d9cb81503f17d2df`.

## Why 3 x 2, not 6 x 1?

Six downstream jobs x one child were proven green but used **~992–1,117
total hosted Stage-B runner wall-minutes** in two full runs, and took
14,704 / 14,710 s admission→last-shard. Green parallel admission with
the **original three downstream jobs** measured 12,195 / 12,905 s and
used **~667–741 Stage-B runner wall-minutes**. The goal here is to
rebalance the cheaper three-job topology instead of spending more runner
resources on a potentially modest wall-time gain.

## Exact source authority

The original exact 31 downstream contract filenames and original hard
2400/3600-second per-contract timeouts are preserved, as is the
unchanged **two isolated child subprocesses per downstream shard**.
No nested proof, signatures, nonce tests, authorization or release
gate is modified. Existing fail-closed two-admission workflow remains
unaltered, including BOTH mandatory conditions on every shard:
`needs: [stage-b-admission, stage-b-nonce]`.

Each exact canonical contract's cost is the rounded **mean of four
real successful per-file contract wall timings** recovered from these
fully GREEN exact-head runs:

- `38089952531` and `38089960759` (parallel admission #2122,
  original three-way strided downstream)
- `38081640622` and `38081628439` (five-run-cost pilot #2118,
  measured-cost three-way downstream)

The exact **12 original GitHub downstream job log IDs** are
embedded in `REFERENCE_LOG_JOB_IDS` in
`tests/support/stage_b_downstream_plan.py`. Each of the 31 contracts
was found once in each complete full-green run; there are no missing
timings, negative result substitution or synthetic PASS markers.

The deterministic three-shard, two-worker-per-shard scheduler retains
31/31, yields group membership sizes **10 / 10 / 11**, and predicts
two-worker makespans **8269 / 7912 / 8711 seconds** from those mean
costs. Replaying the same allocation against the four measured source
datasets predicts (counterfactually) longest-shard time of
**7866 / 9915 / 9392 / 8048 seconds**.

**None of these predictions is actual runtime for this new branch.**
CPU contention inside a shard, child start order, fixture setup,
runner contention and source-run variability make estimates uncertain.

## Safety contract

- Both real independent admission prefix and nonce-reuse checks MUST PASS.
  Nonce-run evidence is produced, sealed and checked against exact HEAD SHA.
- All original 31 downstream scripts execute in isolated processes.
  Original `_MAX_SHARDED_PARALLEL_CONTRACTS=2`, no new jobs or worker
  fan-out; 3 downstream runner jobs + 3 original midchain jobs.
- Original 2400s standard/3600s targeted-deep downstream subprocess
  hard deadlines and 355-minute job budget remain unchanged, as are
  shared-deep/nonce limits and proof/cache/manifest guards.
- Offline fail-closed tests lock exact 31-file coverage, no duplicates,
  deterministic partition, invalid shard inputs, original unsharded
  behavior, constant hard timeouts and cost sanity.
- CI source checks ensure the original six shards and both admission
  prerequisites remain mandatory.
- No main, protected branch authority, production code, tags, physical
  gates or freeze identity are changed.

## Acceptance decision

Before considering any speed claim: standard CI, all CodeQL Go+Python
checks on identical HEAD tree, and at least **two independent fully
green** exact-head campaigns (both admissions plus six shards, all
31 downstream contract files). Compare real critical-path times and
total runner-seconds with #2122 and frozen V1. If cost/speed/security
is not demonstrably better, retain #2122 and reject this experiment.
This is **CI qualification speed**, not a local Ollama inference measure.
