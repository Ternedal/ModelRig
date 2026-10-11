# Stage-B parallel admission + risk-balanced downstream — DRAFT experiment

**Do not merge.** ModelRig V1 main stays frozen at `0b2ff455116f4f28a1a41704d9cb81503f17d2df`; all nine physical/admin gates remain pending. This branch combines one **independently successful** feature with a new **unqualified scheduling proposal**, not a release decision.

## Qualified parent

[Parallel admission #2122](https://github.com/Ternedal/ModelRig/pull/2122) at `a366b3e8e3caa23f6bbf41341d7ff843bf28c51e` already passed two complete exact-head and Go+Python CodeQL runs:
- [38089952531](https://github.com/Ternedal/ModelRig/actions/runs/38089952531): 12,195 seconds (3h23m15s) admission-first-start→last-shard-end; 9,117-second slowest downstream shard
- [38089960759](https://github.com/Ternedal/ModelRig/actions/runs/38089960759): 12,905 seconds (3h35m05s); 10,279-second slowest downstream shard

Both mandatory independent admission branches ran successfully, no cache-hit skip, and **all** six original 3-midchain + 3-downstream shards qualified. Their admission critical path was 3,074 s / 2,622 s, respectively.

## New experimental change (no runtime claims)

The original 31 downstream adversarial contracts are **unchanged** but repartitioned across the same three GitHub downstream jobs and up to two isolated child processes per job, using the previously audited [seven-run cost history](https://github.com/Ternedal/ModelRig/issues/1682):

- Historical five-run measured-cost source from PR #2118, which itself blends the first three complete successful exact-head runs at 75% and the next two at 25%
- 80% of that existing audited cost value + 20% of the **arithmetic mean** of each contract's successful execution seconds from #2122's two additional full-green runs
- New run IDs: `38089952531`, `38089960759`. Their six exact downstream job-log IDs: `114333866615`, `114333866546`, `114333866590`, `114338484180`, `114338484223`, `114338484236`. All seven run IDs and 21 underlying job logs are pinned in the plan source.
- The same deterministic longest-first, two-worker, three-shard planner used by green PR #2118, with newly weighted costs. Shard membership counts **11/10/10**.
- New modeled worker loads: **[8528,8838] / [8213,8043] / [8221,7993] s**, so **8,838 s modeled maximum**. These are *simulation values*, NOT real measured job wall times or a performance guarantee. The model ignores variable runner contention and contract interactions.

Using only the two completed #2122 per-contract observation sets in counterfactual replay, the new partition's simulated longest worker time is **7,920 / 9,667 seconds**, compared with the actual parent #2122 longest downstream job **9,117 / 10,279 seconds**. These are not like-for-like causal measurements: simulator timings come from the different original 3x2 partition and runner environment, exclude setup, and can diverge. **Do NOT advertise those percentages as realized gains.**

The 3,529.5-second `post_release_attestation_contract` observed in the slower #2122 run is close to the unchanged 3,600-second targeted deep timeout; never relax it or silently retry/bypass an adversarial test to improve the number. Full safety authority has precedence over runtime gains.

## Safety invariants (mandatory)

- Exactly the same **31 original** downstream contracts, no skipping, renamed/synthetic success or removed adversarial assertions.
- Same **three downstream GitHub jobs, two isolated child subprocess workers/job**, same three midchain jobs. No additional runner/process cost.
- Identical per-contract **2,400-/3,600-second hard timeouts** and original full unsharded path; invalid shard inputs fail closed.
- Unmodified parent #2122 independent full physical/provenance admission and real nonce-reuse negative test; downstream only starts with **BOTH** green.
- Exact checkout SHA, cache manifest/proof/ledger verification and original security/production/release gates are preserved.
- Added fast deterministic coverage and scheduling tests, with generated test inventory refreshed.

## Qualification contract

1. Full standard CI (incl. negative tests, all 31 contracts exactly once in source plan), Go+Python CodeQL against **the same exact commit and Git tree**, and both independent full exact-head workflows **must PASS**.
2. Measure actual admission→last-shard wall time, **slowest downstream job** and aggregate runner-minutes against parent #2122's two green runs. A stable improvement is necessary to recommend promoting *this draft*; single-run variance is not evidence.
3. If either CI/safety gate fails, if any canonical contract is omitted, or if performance does not improve measurably, reject the new repartition and retain **qualified draft #2122**.
4. Never merge any experimental or security-mirror PR into frozen V1 main, tag/re-freeze, or activate production without explicit release authorization and all physical/admin evidence.

This is **CI qualification speed**, NOT Kaliv/Ollama GPU token-generation latency.
