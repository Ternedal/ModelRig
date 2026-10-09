# Stage-B midchain capacity scenario (read-only, 2026-10-09)

Scope: reproducible calculation, not a change to Stage-B, CI, timeouts,
cache identity, branch protection or release evidence.

- Frozen source: `0b2ff455116f4f28a1a41704d9cb81503f17d2df`.
- Successful exact-head run: https://github.com/Ternedal/ModelRig/actions/runs/37845235363
- Actual midchain job IDs: `113575752307`, `113575752249`, `113575752334`.
- 36 per-contract elapsed observations transcribed directly from these three
  green GitHub Actions job logs into `tests/support/stage_b_midchain_timings_20261009.json`.
- Costs, SHA and original shard provenance are all validated fail-closed.

Run from repository root with Python 3.11+:

    python scripts/stage_b_midchain_scenario.py
    python tests/workflow_stage_b_midchain_scenario.py

Output is JSON with original three-shard runtime model, hypothetical
capacity-aware 2/1/2 worker assignment and simulated makespans.
The current driver (source) still uses its pinned strided mapping, and
the analysis rejects altered drivers. Every contract appears exactly once.

**This is not a measured improvement**. The timing numbers were observed under
the original shard partition; moving CPU-intensive provenance contracts
into a two-worker shard can change cost, trigger oversubscription and
cross existing per-file timeout policy. A production change would need
a separate isolated Stage-B PR, exact-head qualification, review of actual
wall times, and explicitly authorized V1 re-freeze.

`activation_authorized=false`, `production_activation=false`,
`release_gate_satisfied=false` are always emitted.
