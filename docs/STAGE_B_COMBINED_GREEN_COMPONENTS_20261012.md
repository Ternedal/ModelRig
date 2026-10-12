# Stage-B admission + balanced downstream — additive qualification trial

**DRAFT EXPERIMENT. DO NOT MERGE. Not authorized for V1 release.**

## Verified source, preserved identities

This branch combines two **independently green** but unmerged proposals without
changing their canonical safety semantics:

- [PR #2122](https://github.com/Ternedal/ModelRig/pull/2122), exact head
  `a366b3e8e3caa23f6bbf41341d7ff843bf28c51e`, is the starting Git
  commit. It runs original full physical/adversarial admission-prefix and
  focused nonce-reuse **concurrently on two isolated hosted jobs**, requires
  BOTH jobs to pass before all six sharded jobs, and validates the original
  exact-head signed manifest. All original serial `all/admission` routes
  remain intact. 2/2 green exact-head [38089952531](https://github.com/Ternedal/ModelRig/actions/runs/38089952531)
  and [38089960759](https://github.com/Ternedal/ModelRig/actions/runs/38089960759).
- [PR #2118](https://github.com/Ternedal/ModelRig/pull/2118), exact head
  `f43c58043b0ecaa7f95dbbb527e590dd2f9f249f`, contributed **only**
  its already-green original 31-contract three-shard/two-worker
  deterministic measured-cost planner, the downstream wrapper using it,
  and its fail-closed fast static test. 2/2 green complete exact-head
  [38081640622](https://github.com/Ternedal/ModelRig/actions/runs/38081640622)
  and [38081628439](https://github.com/Ternedal/ModelRig/actions/runs/38081628439).

One adapted workflow-source test retains the combined authority invariants;
the generated CURRENT_STATE test inventory includes the new offline
downstream partition regression. No change to original pinned SHA
checkout, cache creation/verification, per-contract timeouts, source
contract implementations, release paths, security gates or production
runtime.

## Observed baseline and falsifiable hypotheses

All times are GitHub hosted-job actual timestamps from complete
**success** runs, admission START through last successful shard FINISH,
including dependency handoff. Not local AI inference timing.

| Candidate | Full green run 1 | Full green run 2 | Average |
|---|---:|---:|---:|
| Parent #2122 parallel admission | 12,195 s | 12,905 s | 12,550 s |
| #2118 measured downstream, *serial admission* | 14,061 s | 14,484 s | 14,273 s |
| Six single-worker downstream #2120, serial admission | 14,704 s | 14,710 s | 14,707 s |

Combining previously successful component optimizations **might** reduce
the last downstream-shard bottleneck, but the individual #2118 runs did
not robustly outperform parent #2122's individual longest shard.
The gain is therefore speculative. This experiment must not be
promoted based on cost-model estimates or combining two green PRs
arithmetically; it must pass its *own* exact SHA end-to-end.

At least two new independent full-green exact-head runs are required.
Measure each actual critical path, worst downstream worker and total
runner-minutes. If the combined candidate is not materially faster than
the simpler #2122 without an unacceptable runner cost, **reject this
combination and retain #2122 as the chosen unmerged reference**.

## Immutable guarantees

- Exactly 31 original downstream support contracts across 3 shards,
  each original contract once; exactly 2 **isolated** subprocesses per shard
  (no extra runners/children); 3 original midchain shards unchanged.
- Original per-contract 2,400s and targeted 3,600s hard bounds unchanged;
  original exact-head/checksum/caching and fail-closed error behavior.
- Both real upstream authorization branches (full physical prefix AND
  nonce replay) run and must pass, with no admission cache-hit skipping.
  Parent's Go+Python CodeQL result does NOT qualify the new combined SHA:
  trigger fresh same-exact-head CodeQL on an independently based `main`
  draft security mirror, verify HEAD and synthetic merge trees identical.
- Both new exact-head runs must show full green; no synthetic evidence,
  testing omission, merge, release tag, V1 main alteration, human verdict
  fabrication or production activation.
- Historical rig power/CPU/GPU settings untouched; this tests only hosted
  GitHub Stage-B CI runtime.

Original frozen ModelRig main:
`0b2ff455116f4f28a1a41704d9cb81503f17d2df`.
Nine physical/admin release gates remain pending.
