# Experimental downstream v3 after fully green parallel admission

**DRAFT / DO NOT MERGE. No change to qualified frozen V1 main.** This branch
is stacked on [parallel admission #2122](https://github.com/Ternedal/ModelRig/pull/2122),
which is **already independently FULL GREEN twice** (including CodeQL Go+Python)
at exact head `a366b3e8e3caa23f6bbf41341d7ff843bf28c51e`.

## Empirical baseline, source and motivation

The Stage-B completion wall from start of first mandatory admission component
to finish of last required shard (includes admission runner scheduling) was:

| Existing exact-head | Status | Elapsed | Slowest shard |
| --- | --- | ---: | ---: |
| [Frozen V1 37845235363](https://github.com/Ternedal/ModelRig/actions/runs/37845235363) | full green | 16,160s (4h29m20s) | 11,116s |
| [Midchain-only #2103 37982695916](https://github.com/Ternedal/ModelRig/actions/runs/37982695916) | full green | 14,658s (4h04m18s) | 9,649s |
| [Parallel admission #2122 run 38089952531](https://github.com/Ternedal/ModelRig/actions/runs/38089952531) | full green | 12,195s (3h23m15s) | 9,117s |
| [Parallel admission #2122 run 38089960759](https://github.com/Ternedal/ModelRig/actions/runs/38089960759) | full green | 12,905s (3h35m05s) | 10,279s |

The prefix / nonce tests are already on separate jobs and remain mandatory.
The downstream slowest shard is now the major avoidable bottleneck.

A prior deterministic downstream partition #2118 was built using exactly
five complete green exact-head data sets. Two **additional** fully green
parallel-admission runs (#2122) provide observed timings for ALL 31 downstream
contract files. This v3 plan uses **75% of the earlier five-run weighted
cost estimate** + **25% of the mean of the two latest measured runs**,
rounded to integer seconds for each of the exact original 31 canonical files.
This dampens feedback bias from recent runner contention. Source run IDs
and all **21 pinned shard job-log IDs** are embedded in
`tests/support/stage_b_downstream_plan.py` (no speculative durations).

The existing deterministic longest-first, exactly 3-shard and 2-worker
partitioner gives membership sizes **11/10/10**, with mathematical
two-worker cost loads:

- shard 1: 8,508s / 8,848s
- shard 2: 8,196s / 8,044s
- shard 3: 8,231s / 8,000s

**8,848s predicted maximum is only a model estimate, not an observed
faster Stage-B run.** A counterfactual replay of the two most recent
per-file timing datasets estimates the slowest shard at **7,920s** and
**9,667s**, respectively; their *actual* immutable old-partition jobs
took **9,117s and 10,279s**. Inter-contract contention, runner
variability and dependency interactions are *not* preserved in the
counterfactual. None of these replay figures qualify runtime performance.

## Strict security invariants

- Parallel admission is **unchanged** from full-green #2122: complete physical
  gate and transitive canonical ADR-026 → ADR-030/31 → shared ADR-032/33;
  independently executed original nonce-replay adversarial contract with its
  exact-head proof-cache manifest; **both successes** required for shards.
- Exactly **31 canonical downstream adversarial contracts**, no omission or
  duplication, unchanged source assertions and original 2400/3600s per
  contract hard timeout limits; no artificially reduced test coverage.
- Exactly **3 downstream runner jobs x 2 isolated child processes**, same
  as #2122. No extra CPU/GitHub runner or concurrent process fan-out.
- The original unsharded full-chain execution remains complete and
  unchanged; invalid shards, extra/missing contract names, invalid cost
  entries, missing proofs, SHA mismatch and replay claims fail closed.
- Existing pinned GitHub Actions, exact checkout HEAD SHA, manifest
  verification, all midchain jobs, concurrency boundaries, all release
  gates and production authorization are unchanged.

## Required before qualification

1. Pass standard CI and all new fast deterministic partition coverage
   regressions on the candidate exact immutable SHA.
2. Pass Go + Python CodeQL and exact same-tree merge-base verifier; if
   the stacked PR does not trigger main-only CodeQL, open a **draft
   security-only mirror** from the *identical commit* against frozen main.
3. Independently pass **two complete exact-head workflows**: both admissions,
   each of the three midchain and three downstream jobs. Observe full
   admission→last-shard elapsed and total hosted runner-hours.
4. Reject this new partition if the actual repeated improvement is not
   material over #2122, despite any theoretical scheduling score. Don't
   merge, tag, release, re-freeze, activate production, or reinterpret
   physical/admin pending gates.

Nothing here improves local Ollama inference latency; that separate
measurement lives in diagnostic-only PR #2124.
