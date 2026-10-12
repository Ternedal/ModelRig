# Experimental seven-run downstream balancing stacked on verified parallel admission

**DRAFT. NO MERGE. NO V1 RELEASE OR PHYSICAL AUTHORITY.** Parent candidate
[PR #2122](https://github.com/Ternedal/ModelRig/pull/2122) at immutable
`a366b3e8e3caa23f6bbf41341d7ff843bf28c51e` is independently
qualified in **two complete exact-head suites**: 12,195 s (3:23:15)
and 12,905 s (3:35:05) earliest Stage-B admission start → last
shard completion. Both standard CI and Go/Python CodeQL are green.
Never change that measured head; this is a fresh stacked experiment.

## What this change does

**Only** assign the **same original 31 downstream adversarial contracts**
to the **same three shard jobs, with the same two isolated child processes
per job** using a deterministic measured-cost partition. It does not
change any contract's source, pass/fail assertion, cached proof authority,
signature verification, default release gate, exact checkout SHA,
workflow timeout, per-contract **2400/3600-second hard timeout**, physical
gate, midchain jobs, or the parallel admission predecessor/nonce jobs.
The unsharded/full-chain execution path remains unchanged and invalid
shard inputs fail closed.

The earlier five-run costs from
`tests/support/stage_b_downstream_plan.py` were themselves derived from
three complete older green runs (75%) plus two green downstream-v1 runs
(25%). On this draft **every one of the same 31 contracts** is
recalibrated with:

```text
seconds = round(0.50 * five_run_weighted_cost
              + 0.25 * measured_contract_time_from_full_green_run_38089952531
              + 0.25 * measured_contract_time_from_full_green_run_38089960759)
```

This weights the two most recently green *parallel-admission* runs
without discarding the five older qualifying histories. All 7 exact-head
run IDs and all 21 source downstream job-log IDs are pinned verbatim in
the planner. Any missing/extra/malformed original contract fails closed.

The deterministic six-worker / three-job cost simulation gives:

| Shard | Original contracts | Modeled isolated worker A | Worker B |
|---|---:|---:|---:|
| 1 | 10 | 8,451 s | 8,037 s |
| 2 | 10 | 8,221 s | 8,031 s |
| 3 | 11 | 8,785 s | 8,267 s |

**8,785 s modeled longest slot, NOT a measured job duration.**
Counterfactually replaying the two latest per-contract timing datasets
with this new assignment predicts *longest* downstream shards of
**7,700 s** and **10,010 s**, versus simulated original strided
assignment maxima of **9,078 s** and **10,242 s** respectively.
These simulations do **not** model changes in runner load, inner nested
resource contention, setup time or cross-contract dependencies. The
real historical #2122 jobs actually took 9,117 s and 10,279 s;
**no real downstream speed benefit has yet been demonstrated**.

The empirical best-case scheduling floor of the two #2122 runs
(the time to execute all 31 canonical contracts divided across six
perfectly occupied workers, plus measured independent-admission
critical-path time) was roughly **2:54 and 3:17**. This is only a lower
bound under fixed observed per-contract durations and excludes runner
setup and loss of parallel efficiency; never present this as achieved
or guaranteed. Getting substantially below it requires reducing
the actual contract work with **independent security proof of equivalence**,
not dropping any adversarial case.

## Gate before even considering adoption

1. Standard CI including full test inventory and this extra offline
   partition regression must succeed; Go and Python CodeQL on exact
   candidate SHA must both succeed via same-tree base-main mirror.
2. Two independent complete exact-head campaigns each require admission
   prefix+nonce and all 3 midchain and 3 downstream jobs GREEN. Every
   canonical downstream adversarial contract must run, not be synthesized.
3. Compare measured total elapsed and all runner-minutes to parent
   **#2122**, *not* the original main baseline alone. If gains are
   not stable or cause extra resource cost, reject this experiment.
4. **Do not merge, release, tag, bypass any protected status, re-freeze
   or activate production.** Software V1 main in four repos remains
   unchanged; nine physical/admin release gates remain pending.

[Detailed evidence ledger in optimization issue #1682](https://github.com/Ternedal/ModelRig/issues/1682).
