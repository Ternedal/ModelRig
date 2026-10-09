# Stage-B midchain cost planning — offline experiment

This is a read-only, offline performance experiment. **It does not change
Stage-B execution**, shard membership, source/provenance gates, worker count,
timeout budgets, release authority, or any code in the qualified V1 main.

Evidence: independent success of ModelRig main exact-head GitHub Actions run
37845235363, pinned SHA 0b2ff455116f4f28a1a41704d9cb81503f17d2df. Individual shard jobs:
- midchain-1 job 113575752307, driver 4520.7 seconds;
- midchain-2 job 113575752249, driver 11078.2 seconds;
- midchain-3 job 113575752334, driver 2591.8 seconds.

To reproduce the proposed plan:

    python scripts/stage_b_midchain_plan.py
    python tests/workflow_stage_b_midchain_cost_plan.py

The input fixture records the 36 per-contract PASS timings taken from the
three actual GitHub Actions job logs, with provenance metadata and SHA.
The code parses the canonical Stage-B contract tuple WITHOUT importing the
driver (no process execution), rejects missing/stale/duplicate costs and
computes a deterministic candidate assignment.

The estimator models existing serial shard 2/3 and two-worker shards 1/3
and 3/3. Measured contracts taking >1800s stay in the serial shard, to
avoid silently reducing their per-contract timeout. It is deliberately
conservative about preserving the original runtime: NO Stage-B driver or
workflow code is altered. Estimated speedups are **not measured** and may
change under CPU oversubscription, caching, or deeply nested contract work.

Accepting any future execution change requires a new isolated branch,
proof that every contract runs exactly once, a complete fresh exact-head
Stage-B PASS and a real measured run-to-run comparison before deciding
whether to re-freeze V1. This draft may not be merged into qualified main.
