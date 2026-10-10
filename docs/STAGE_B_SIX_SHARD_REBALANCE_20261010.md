# Stage-B six-shard runtime experiment — downstream rebalance stacked on #2103

**DRAFT / UNMERGED only. Frozen qualified V1 main remains unchanged.**
The parent is [PR #2103](https://github.com/Ternedal/ModelRig/pull/2103),
which already passed all 6 exact-head shards for the independently measured
midchain map. This experiment adds *only downstream* measured-cost rebalance.
Do not merge either draft, change branch protection, issue a release tag,
or use these runs to claim physical/human acceptance or production activation.

## Empirical bottleneck, not synthetic PASS

Three **successful** exact-head runs with original downstream strided sharding:

| Run | downstream-1 | downstream-2 | downstream-3 | Longest |
| --- | ---: | ---: | ---: | ---: |
| Frozen main [37845235363](https://github.com/Ternedal/ModelRig/actions/runs/37845235363) | 7918.2 s | 8960.8 s | 9579.9 s | 9579.9 s |
| V1-based smoke [37942702263](https://github.com/Ternedal/ModelRig/actions/runs/37942702263) | 9454.9 s | 8909.5 s | 9690.9 s | 9690.9 s |
| Parent midchain experiment [37982695916](https://github.com/Ternedal/ModelRig/actions/runs/37982695916) | 5045.5 s | 8964.4 s | 9612.6 s | 9612.6 s |

The 9 source GitHub job IDs are pinned as `REFERENCE_LOG_JOB_IDS`
inside `tests/support/stage_b_downstream_plan.py`. Contract durations are
rounded means across **all three passing source runs**. One wrapper total
per job is intentionally excluded from individual contract costs.

## Bounded implementation

The plan is deterministic: order all 31 existing independent downstream
contracts by descending measured wall time and assign each contract to the
least-loaded estimated worker slot across the **existing three shards with
two workers each**. Two copies of any contract can never be scheduled;
every exact original filename is checked against the cost authority.
The returned order is the actual `ThreadPoolExecutor` submission order.

The test protects all 31 original contracts and original unsharded behavior;
exactly 3 Stage-B downstream jobs, max 2 isolated Python child processes
per job, **unchanged 2400/3600-second individual hard timeouts**, original
admission cache verification, pinned Git checkout and all fail-closed outcomes.
No proof caching across tests, weak flags, synthetic early success, auth bypass,
selective test skipping, reduced assertions or process reuse.

The frozen/parent downstream measured maximum was roughly **9.6k seconds**;
the new plan's optimistic cost model yields worker loads of about
**8.1k–8.9k seconds**. This is a **simulation**, NOT an observed CI gain.
Comparing *six-shard* observed longest runtimes: frozen V1 11078s vs
parent #2103 9613s, whereas idealized six-shard candidate critical path
might approach ~8893s (**about 20% below frozen V1, 7–8% below #2103**).
These percentages are **not guarantees**, not measured full Stage-B time,
and exclude prerequisite/admission/cache/setup, actual CPU contention,
network queueing and any possible timeout. None may be claimed green before
a successful same-exact-head end-to-end GitHub Actions qualification.

In particular, another docs-only draft previously hit many 2400/3600s
downstream subprocess timeouts under runner load. A green local model
can never excuse a red exact-head run. If any of the 31 contracts times
out or fails, **reject this proposal** rather than extending timeouts,
hiding output or weakening safeguards.

## Qualification before changing frozen software

1. Fast contract completeness + invariant tests must pass on candidate SHA.
2. Full standard CI, CodeQL and all six Stage-B shards need green exact-head.
3. Compare logs across at least two additional independent green runs;
   record every per-file cost and the slowest upstream/downstream job.
4. Recheck unsafe branches, strict GitHub policy, exact four-repo pins;
   deliberate release re-freeze is a separate explicit decision.

The original V1 SHA is
`0b2ff455116f4f28a1a41704d9cb81503f17d2df`.
`software_exact_green` is qualified for that SHA **only**.
The other nine release gates are still PENDING.
