# Stage-B experimental midchain cost-balanced shards — no V1 runtime authority

This **draft** changes only the midchain Stage-B test scheduler; it does not
change any contract, proof cache, timeout, security rule, release gate,
production activation, or required CI check.

## Input provenance

Completed software-qualified **protected main** exact-head run:
https://github.com/Ternedal/ModelRig/actions/runs/37845235363

- Midchain-1 job 113575752307, isolated driver 4520.7s
- Midchain-2 job 113575752249, isolated driver 11078.2s
- Midchain-3 job 113575752334, isolated driver 2591.8s

All 36 per-contract timing lines came from these jobs' PASS logs. The
checked-in costs in `tests/support/stage_b_midchain_balancing.py` are
each anchored to the exact 2026-10-09 source SHA and to that run ID.
The values are **observations, not guarantees**; moving heavy contracts across
shards may change their runtime, CPU contention and cache use.

## Fail-closed orchestration

The planner validates a one-to-one match between the canonical 36 filenames
and the measured cost table, then deterministically assigns each once across
three shards. Source order is preserved *within* each output shard.

The two measured >1800s deep publication/post-merge contracts remain
**pinned in shard 2**, which retains one worker. **Timeouts stay bound to
the filename's original strided shard**, even when that filename moves:
original shard-2 contracts retain 2400s, original shards 1/3 retain 1800s,
and the explicit post-merge target retains 3600s. Shards 1 and 3 retain
their existing maximum two isolated-process workers. Unsharded behavior and
downstream partition are untouched.

The planner evaluates each candidate in the original canonical source order,
which matches executor submission order, and minimizes a **simple estimated
worker-slot makespan** based on one completed run, not true multi-resource runtime. It can get real performance
wrong. Regression tests assert stable partitioning, full coverage, deep
placement, worker counts, timeout expectations and stale/missing cost rejection.

## Qualification and rollback

1. Leave certified V1 main frozen at its previously qualified exact SHA.
2. Inspect this draft diff and run fast deterministic tests.
3. Run all actual protected PR CI and exact-head Stage-B shards on the draft.
4. Compare actual *per-shard wall-clock*, not just the simulated forecast,
   against the historical job IDs above.
5. Only after a reviewed empirical PASS consider whether the performance gain
   justifies a deliberate new V1 re-freeze; otherwise close the draft.

No previous evidence may be rebound to the experimental commit.
