# Experimental Stage-B midchain rebalancing — NOT V1 authority

**Change is isolated in a DRAFT branch; qualified V1 main stays unchanged.**

Two independently successful exact-head runs on comparable frozen/source trees:

- Frozen ModelRig main SHA: `0b2ff455116f4f28a1a41704d9cb81503f17d2df`
- Exact-head run `37845235363`, three midchain job logs `113575752307`, `113575752249`, `113575752334`.
- Exact-head draft run `37942702263`, three midchain job logs `113898121297`, `113898121209`, `113898121217`.

Midchain-2 lasted 11078.2s and 11175.2s in those runs. In the second run,
midchain-1 took 3724.5s and midchain-3 took 3605.9s.

The experiment keeps all 36 contracts exactly once, original subprocess isolation,
the existing 3-way GitHub Stage-B matrix, 1800/2400/3600-second contract timeouts,
the serial execution of shard 2/3, admission proof cache and fail-closed results.
The two contracts measured above 1800s remain pinned to serial 2/3.
All other contracts are assigned deterministically to the least loaded modeled
worker slot using rounded mean per-contract cost from both successful runs.

Proposed 3-shard assignment: 16 / 4 / 16 contracts. Estimated worker-slot
load is ~5008s, ~4940s and ~5080s at the model's idealized concurrency,
compared with the observed ~11078–11175s serial bottleneck.
**These are estimates, not measured CI speedups or SLAs.** CPU contention,
per-contract recursion, GitHub Actions runners and actual executor order can
produce a different wall time or a timeout. Full exact-head qualification
including every Stage-B shard must be green on the experimental exact head.

No production activation, stage skipping, weaker review enforcement, changes to
the accepted V1 software receipt, or automatic merge are authorized. Compare
actual end-to-end duration *after* CI and record any regression before considering
a future independent V1 re-freeze.
