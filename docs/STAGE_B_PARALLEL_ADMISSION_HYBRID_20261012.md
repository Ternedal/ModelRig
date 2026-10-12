# DRAFT — Hybrid Stage-B speed experiment: verified parallel admission + seven-run downstream balance

## Authority and baseline

This experiment is branched from [PR #2122](https://github.com/Ternedal/ModelRig/pull/2122), SHA `a366b3e8e3caa23f6bbf41341d7ff843bf28c51e`, which **passed two independent full exact-head campaigns, all standard CI and Go+Python CodeQL**. It is a *separate* stacked experiment, not a replacement for the preserved green head.

The frozen ModelRig V1 main remains `0b2ff455116f4f28a1a41704d9cb81503f17d2df`. No merge, production activation, release authority, physical/admin gates, timeout or unsafe waiver is authorized.

## Verified baseline performance

Use GitHub job `started_at` and `completed_at` timestamps, from the beginning of the earliest Stage-B admission job to the end of the last Stage-B shard (this explicitly includes staggered admission runner starts):

| Exact-head run | Candidate | Full elapsed | Downstream max | All green |
| --- | --- | ---: | ---: | --- |
| 37845235363 | frozen main | 16,160 s | 9,612 s | YES |
| 37982695916 | midchain-only #2103 | 14,658 s | 9,649 s | YES |
| 38089952531 | parallel admission #2122 | 12,195 s | 9,117 s | YES |
| 38089960759 | parallel admission #2122, independent run | 12,905 s | 10,279 s | YES |

The parallel admission approach does **not** skip the shallow, deep-provenance or nonce-reuse contracts. They all ran in real isolated jobs and retained the original per-file timeouts and all release/production guards. Its first two measured full-run wall improvements versus frozen V1 are ~24.5% and ~20.1%. **These timing results do not qualify this new hybrid commit.**

## Why the extra downstream experiment?

The original strided assignment of the **same 31 canonical downstream contracts** can produce an unbalanced critical shard, even after the separate admission speedup.

We retain the *same three downstream runner jobs with two isolated worker processes each*. The existing fail-closed cost-balancing planner is imported. Its only input change is a new, traceable weight table:

```text
new_seconds(file) = round(
    0.65 * historical_cost(file)
  + 0.35 * mean(2026-10-10 green #2122 measured costs for file)
)
```

Historical cost is from the 5 full-green runs
`37845235363 / 37942702263 / 37982695916 / 38036507743 / 38048149969`;
recent cost is from `38089952531 / 38089960759`. All 7 run IDs and all 21 actual downstream shard job log IDs are embedded in `stage_b_downstream_plan.py`.

The candidate retains **all 31 contracts exactly once**, distributes them deterministically as **10 / 10 / 11** with exactly two child processes/job, and has a retrospective **estimated** cost maximum of **8,811 s**. The two latest observed per-file timing sets, replayed counterfactually through the new partition, predict worst downstream shard at **7,868 s and 9,879 s**, compared with the actual old-strided workload's **9,117 s and 10,279 s** (GitHub job wall, including setup, versus simulated task-sum). These comparisons are **NOT apples-to-apples empirical measurements**, cannot account for cross-file CPU/memory contention, and are *not evidence of speedup*. The predicted gain might disappear or reverse in a real GitHub runner.

## Safety invariants and acceptance

- All 31 original exact downstream test files still run in their **own isolated Python subprocesses**, each once.
- Exactly **three original downstream shard runner jobs, max two concurrent isolated children per shard**, all existing hard subprocess limits **2400/3600s** unchanged. The normal unsharded legacy route still runs the full canonical suite.
- Existing independent parallel-admission graph still requires **both** the full physical/provenance prefix and separate real nonce-replay guard to pass before any shard starts. Exact-head SHA checkout, signed provenance, on-disk proof/ledger checks, cache-root manifest, negative replay tests and production authority gates are untouched.
- The fast offline test validates all canonical membership, 10 targeted deeper contracts, hard per-child bounds, one-to-one coverage, hash/source provenance references, determinism, fail-closed invalid modes and that no invalid cost is accepted. This test is not substituted for real end-to-end qualification.
- Require **two independent full-green exact-head runs** and same-HEAD CodeQL Go/Python via security mirror (if the stacked PR misses base-main-only CodeQL), standard CI and negative tests. Compare measured critical path, max shard and runner-minutes versus #2122. If real stable improvement is absent or targeted deep contracts time out, reject this candidate in favor of the already green #2122.
- All V1 physical/admin release gates remain PENDING. **Do not merge, tag, re-freeze, publish production or claim release authority.**

This is Stage-B CI qualification time, **not** local Ollama/ModelRig response latency.
