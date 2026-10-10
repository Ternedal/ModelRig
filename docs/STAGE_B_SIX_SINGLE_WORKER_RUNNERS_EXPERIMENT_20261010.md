# Stage-B: six single-worker downstream runners — DRAFT EXPERIMENT

**No change to frozen V1 main, production, release tags, exact-head identity,
physical acceptance or CI security authority. DO NOT MERGE.**

## Why another experiment?

Two full green exact-head runs for downstream v1 (#2114) took
9,741 and 9,892 seconds for the slowest of three downstream jobs.
Those jobs used two isolated Python child processes concurrently on the same
hosted runner. CPU-heavy nested attestations compete locally for runner CPUs,
raising individual wall time and making a single heavy shard dominate.

The existing downstream v2 (#2118) recalibrates measured costs across five
fully green source runs but also keeps two simultaneous children per runner.
**This independent v3 experiment tests reducing CPU contention**, not skipping
work: **6 downstream jobs x 1 isolated child per job** replaces
3 downstream jobs x 2 children per job. Total maximum concurrent
downstream children remains **6**. Three separate midchain jobs and the
admission predecessor are unchanged. GitHub runner consumption increases
from 3 to 6 downstream runners; total per-run runner-minutes and queuing
can therefore be greater. Do not claim lower cost or speed until measured.

## Exact bounded change

- Original **31 canonical downstream contract Python files**, exactly once
  across the six shards, same canonical contract sources and assertions.
- Deterministic largest-cost-first scheduling into six single-worker bins
  with the same v2 source cost authority (5 complete green source runs,
  15 original log references), no opportunistic or nondeterministic sharding.
- Planner expected membership sizes: **5 / 5 / 5 / 6 / 5 / 5**.
- Predicted per-job cost sums in original *two-process* observed seconds:
  **8,607 / 8,271 / 8,174 / 8,793 / 8,030 / 7,985 s**.
  Absolute values are **NOT valid single-worker runtime predictions**.
  Total 49,860 observed-cost seconds; idealized six-worker floor 8,310 s,
  before runner speed, per-file overhead and contention.
- The 2400s standard and 3600s targeted deep-contract **hard subprocess
  timeouts are UNCHANGED** and still apply to each canonical contract.
- Dedicated downstream job uses exactly **one** isolated subprocess at
  a time; the unsharded/legacy path preserves its original limit of two.
- Midchain 3/3 and its original worker caps are untouched.
- All nine shard jobs (midchain 1–3, downstream 1–6) depend on successfully
  completed admission and must fetch/verify the **same exact-head signed
  cache manifest**. Pinned checkout SHA, locked entrypoint, inherited
  fail-closed outcomes and workflow per-job timeouts remain intact.

## Failure isolation, acceptance and limitations

The experiment lives on a fresh branch stacked on the unmerged v2 draft,
not V1 main. Its workflow/test changes are limited to fan-out, plan mapping,
and fail-closed coverage/single-worker guards. No permission, product code,
artifact authority, release gate, production activation, or physical
qualification changes.

**Mandatory before considering improvement:**

1. Standard CI incl. fast 31-contract completeness and explicit six-shard
   source assertions, exact-head core and Go+Python CodeQL on the exact
   candidate SHA. The original base-main CodeQL workflow needs an isolated
   same-commit draft security mirror when the experiment is stacked.
2. All **9 shard jobs plus admission** (10 Stage-B component jobs overall)
   must pass on the exact head; no timeout relaxation, test skip, process
   reuse, disabled assertions or empty green synthesis is allowed.
3. Repeat at least twice with independent full-green exact-head runs.
   Compare the admission→last-shard wall time, worst downstream shard and
   total billed runner-minutes to midchain-only #2103 and 3x2 v2 #2118.
4. If it is no faster or runner usage is unacceptable, **reject** v3;
   retain frozen qualified V1 and the independently green #2103 as
   the reference. Even a full green experiment is not release authority.

### References

- [Frozen V1 Stage-B](https://github.com/Ternedal/ModelRig/actions/runs/37845235363)
- [Safe midchain-only parent #2103](https://github.com/Ternedal/ModelRig/pull/2103)
- [Five-run downstream v2 #2118](https://github.com/Ternedal/ModelRig/pull/2118)
- [Measured-cost optimization issue #1682](https://github.com/Ternedal/ModelRig/issues/1682)

This is **CI qualification speed**. It does **not** benchmark or change
ModelRig's live Ollama GPU/token-generation latency.
