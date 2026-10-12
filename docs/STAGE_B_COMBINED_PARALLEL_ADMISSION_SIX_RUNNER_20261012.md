# Combined performance experiment — dual admission + six isolated downstream runners

**DRAFT ONLY. Never merge, release, tag, re-freeze or activate production.**
Frozen V1 main remains `0b2ff455116f4f28a1a41704d9cb81503f17d2df`;
all nine physical/admin gates remain pending.

## Measured evidence before this change

- Frozen V1 green exact-head: [37845235363](https://github.com/Ternedal/ModelRig/actions/runs/37845235363), ~4h29m admission-to-last-shard.
- Midchain-only successful #2103: [37982695916](https://github.com/Ternedal/ModelRig/actions/runs/37982695916), ~4h04m.
- **Parallel admission #2122**, with all exact-head jobs, CodeQL Go+Python, ordinary CI and physical-gate suites fully green twice:
  [38089952531](https://github.com/Ternedal/ModelRig/actions/runs/38089952531) ~3h23m15s;
  [38089960759](https://github.com/Ternedal/ModelRig/actions/runs/38089960759) ~3h35m05s.
  Both independently enforce admission-prefix AND original real nonce-replay test.
- **Six single-worker downstream #2120**, independently all green twice:
  [38083540450](https://github.com/Ternedal/ModelRig/actions/runs/38083540450) ~4h05m04s;
  [38083575692](https://github.com/Ternedal/ModelRig/actions/runs/38083575692) ~4h05m10s.
  In BOTH runs, downstream shard 4 stayed near **9,600 seconds**
  while other downstream jobs finished sooner. This remains a real bottleneck.

## New candidate

Combine **proven dual-admission execution** from #2122 with **six isolated
single-worker downstream runners** from #2120, but **rebalance the exact
canonical 31 downstream contracts** using additional *empirically measured*
six-runner file timings.

The starting five-run cost table came from successful runs
`37845235363, 37942702263, 37982695916, 38036507743, 38048149969`
and its original 15 pinned job logs. All 12 downstream child job logs
from independent green six-runner runs `38083540450, 38083575692`
are added; **7 green exact-head sources, 27 log jobs** in total.
For each exact canonical contract, weights (seconds) equal
`round(0.75 × previous 5-run calibrated cost + 0.25 ×
mean(two six-single-worker-run measured contract durations))`.
The old 75% weight guards against overfitting runner variation.
No fabricated contract observations or missing file durations.

The existing deterministic six single-worker shard greedy scheduler
is unchanged. Modeled shard sizes are **5 / 5 / 5 / 5 / 5 / 6**,
with modeled sums **8069 / 7908 / 7838 / 7892 / 7790 / 8633 s**.
Replaying the *observed per-contract times* from the two completed
six-runner runs through this new schedule gives **8426 s** and **7241 s**
respectively as the longest six-shard sum, versus actually observed
~9596/9603 seconds on the previous six-runner arrangement.
**These 8,426 / 7,241 numbers are hypothetical replays, NOT observed
execution times for the new scheduling plan.** Reordering tests changes
contention and worker performance; only new full runs can verify gains.

The ultimate Stage-B critical path is gated by the slower of the two
mandatory admission phases followed by the slowest of the unchanged
three midchain shards and new six downstream shards. More GitHub
runner-minutes may be consumed. Track both wall time and total runner
seconds before recommending this cost/speed trade-off.

## Security invariants

- All original 31 downstream contracts run exactly once, fully isolated
  in separate original subprocesses with **unchanged 2400/3600 second
  per-contract hard timeouts**, no skipping, no fake green status.
- Exactly six dedicated downstream GitHub runner jobs, one active child
  per job; original 3 midchain runner jobs remain unchanged. Downstream
  max 6 active children, no increased per-run contract concurrency.
- Both independent admission branches actually execute at the exact
  pinned candidate head with **no cache-hit early exit**:
  original physical full transitive admission prefix and complete
  original ADR-033 adversarial nonce-reuse contract.
- The nonce job alone creates, seals and verifies exact-head cache
  manifest, all shards download and verify it. All 9 shard jobs require
  `needs: [stage-b-admission, stage-b-nonce]` — both must pass.
- No changes to source release permissions, signatures, trust roots,
  nonce-replay negatives, real physical evidence, product/worker
  production runtime, merge policies, or V1 software freeze.
- Offline tests assert exact 31-file coverage, shard routing fail-closed,
  aggregate count, original bounds and fixed seven-run authority, while
  CI tests assert both mandatory admission jobs and pinned cache chain.

## Acceptance

1. Ordinary CI and both Go/Python CodeQL must be green for the exact
   commit, via same-SHA main-based **security-only draft mirror** if
   the stacked PR does not trigger CodeQL.
2. At least **two complete independent exact-head runs** with
   admission prefix + nonce + all 9 shards SUCCESS, without timeouts,
   skipped contracts, absent artifacts or lowered checks.
3. Compare admission-to-last-shard duration AND total runner usage
   to #2122 and #2120. If no clear reproducible improvement, **reject**
   this experiment and keep #2122 as the last independently green
   fastest candidate.
4. Keep experimental draft PRs unmerged until explicit release
   approval and remaining physical/admin gates.

**This changes CI qualification runtime only.** Kaliv/Ollama local GPU
token speed must be measured separately on the physical rig.
