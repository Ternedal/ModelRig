# Stage-B downstream robust cost rebalance v2 — EXPERIMENT ONLY

**DRAFT, UNMERGED, no release or production authority.** The qualified
frozen V1 main is `0b2ff455116f4f28a1a41704d9cb81503f17d2df`.
This work is stacked on previous experimental draft #2114, itself stacked
on the independently successful midchain-only experiment #2103. The
physical/admin V1 release gates stay PENDING.

## Empirical trigger

The first downstream rebalance, exact candidate commit
`28cf33e1f12c80f5b5abfe18b34aeab22f5dbbe8`, was **fully green**
twice, including CodeQL Go+Python checked via same-head main-based
security-only draft #2117:

- [Run 38036507743](https://github.com/Ternedal/ModelRig/actions/runs/38036507743):
  downstream-1/2/3 job times 6,896/9,741/9,396 seconds.
- [Run 38048149969](https://github.com/Ternedal/ModelRig/actions/runs/38048149969):
  downstream-1/2/3 job times 5,044/9,892/9,470 seconds.
- Parent #2103's earlier complete green
  [run 37982695916](https://github.com/Ternedal/ModelRig/actions/runs/37982695916):
  worst downstream job 9,649 seconds.

Both green #2114 runs revealed a persistent workload imbalance:
downstream-1 was far lighter than downstream-2 and downstream-3.
The original v1 downstream cost map was *predicted* to be balanced from
three earlier full-green runs but did **not** yield a reproducible improvement
over parent #2103. Admission wall time also fluctuated ~3,459 vs ~5,033 s;
do not attribute its variation to downstream assignment.

## Conservative five-run recalibration

For each of the **same canonical 31 downstream contracts**, calculate:

```text
seconds = round(
    0.75 * mean(contract time over the 3 earlier full-green runs)
  + 0.25 * mean(contract time over the 2 full-green #2114 runs)
)
```

The older three green run IDs are
`37845235363`, `37942702263`, `37982695916`.
The newer two green run IDs are `38036507743`, `38048149969`.
All 15 actual GitHub job-log IDs are pinned as
`REFERENCE_LOG_JOB_IDS` in
`tests/support/stage_b_downstream_plan.py`. No synthetic timing or
missing/failing run is used as source authority. The 75% historical weight
reduces overfitting to the latest assignment or transient runner contention.

The same existing deterministic 3-shard, 2-worker-per-shard planner
produces shard membership counts **10/10/11**. Its *model-only*
per-worker predicted loads are:

- shard 1: 8,607 s / 7,985 s
- shard 2: 8,271 s / 8,030 s
- shard 3: 8,174 s / 8,793 s

**Predicted maximum = 8,793 s. NOT OBSERVED.** Replaying the five
historical per-file timing datasets through the new work queue estimates
the worst-shard times to be **9,131 / 9,770 / 7,954 / 8,632 / 7,926 s**,
respectively. These are counterfactual simulations and exclude
inter-contract resource contention, context effects and runner variation.
The old/current measured maxima were 9,612/9,691/9,649/9,741/9,892 s
for the respective five runs. Such retrospective replay is *not* proof of
a real speedup or a safety qualification.

## Immutable safety invariants

- All original 31 contracts run once and only once over downstream shards.
- Still exactly 3 downstream shard jobs and no more than **2 isolated
  subprocesses per shard**; no worker or runner fan-out increase.
- **Original 2400/3600-second hard per-contract timeouts remain unchanged**,
  including targeted deep-contract exceptions. All expected modeled costs
  remain below the correct existing bounds.
- No assertion, real process execution, checkout SHA pinning, cache-root
  manifest validation, provenance authority, release or production gate
  changes; no shared mutable proof reuse, shortcuts or synthetic PASS.
- Unsharded full-path behavior remains unchanged, and invalid shard inputs
  fail closed. Fast deterministic tests lock input coverage and modeled
  membership against inadvertent changes.
- No `main` changes, merge, production activation, release tag or V1 re-freeze.

## Acceptance before consideration

1. Run all fast workflow invariants and standard CI on the exact new draft
   head, and all Stage-B exact-head jobs, including all 31 downstream
   contracts, **must be SUCCESS** without timeout relaxation.
2. Run same-tree exact-head Go+Python CodeQL via a *new* main-based
   security-only mirror if CodeQL's branch filter does not trigger for the
   stacked draft. Do not reuse #2117's CodeQL result for altered code.
3. Obtain **at least two independent fully green** runtime measurements
   and compare the worst-shard wall times against #2103 and #2114.
4. If there is no stable real speed improvement, **reject v2** and retain
   the last successful unmerged candidate. No experimental CI green
   alone can qualify frozen V1 or the pending physical/admin gates.
