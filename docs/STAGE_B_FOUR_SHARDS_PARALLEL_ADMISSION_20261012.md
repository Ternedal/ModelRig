# Experimental four downstream shards + validated parallel admission (2026-10-12)

**DRAFT, NEVER MERGE INTO FROZEN V1.** This branch is stacked on
[parallel-admission PR #2122](https://github.com/Ternedal/ModelRig/pull/2122),
an independently green candidate with no release authority. ModelRig V1
main stays `0b2ff455116f4f28a1a41704d9cb81503f17d2df`.

## Verified starting point

PR #2122 exact immutable SHA `a366b3e8e3caa23f6bbf41341d7ff843bf28c51e`:
- [Green run 38089952531](https://github.com/Ternedal/ModelRig/actions/runs/38089952531):
  **12,195 s** admission-start to last-shard completion (3h23m15s);
  admission prefix 3,066s, nonce 2,035s; worst shard 9,117s;
  **40,022 aggregate Stage-B runner-seconds**.
- [Green run 38089960759](https://github.com/Ternedal/ModelRig/actions/runs/38089960759):
  **12,905 s** (3h35m05s); prefix 1,583s, nonce 2,036s;
  worst shard 10,279s; **44,489 aggregate Stage-B runner-seconds**.

This compares with frozen V1 [run 37845235363](https://github.com/Ternedal/ModelRig/actions/runs/37845235363)
at 16,160s (4h29m20s), and baseline #2103
[run 37982695916](https://github.com/Ternedal/ModelRig/actions/runs/37982695916)
at 14,658s (4h04m18s). These are **observed** timings from GitHub
`started_at` and `completed_at` timestamps; runner queueing and upstream
host contention vary. The #2122 gain is **verified twice**; this new
four-shard experiment has **no successful timing measurement yet**.

Six dedicated single-worker downstream runners (#2120) also passed twice,
but each run took ~14,704s and consumed ~59,498–67,018 aggregate
Stage-B runner-seconds. It is not a good speed/cost tradeoff.

## Hypothesis (not benchmark result)

The original 31 downstream contracts still dominate the critical path,
even with parallel admission. Split them over **four independent downstream
GitHub runner jobs**, each with at most **two isolated subprocesses**.
This increases peak downstream concurrency from 6 to 8, with only one
additional runner (3→4), *unlike* the expensive 6x1 trial. Accept the
additional runner spend **only if measured wall time and runner-minutes
justify it**.

Use the existing 31-file cost table grounded in five fully-green exact-head
runs: 37845235363, 37942702263, 37982695916, 38036507743, 38048149969.
It gives a deterministic 4-shard distribution with group sizes
**7/8/8/8** and hypothetical worker loads:

- shard 1: 5,943s + 6,276s (max 6,276s)
- shard 2: 6,297s + 6,280s (max 6,297s)
- shard 3: 6,333s + 6,338s (max 6,338s)
- shard 4: 6,205s + 6,188s (max 6,205s)

**Projected critical shard = 6,338 seconds, simulation only.** These
are historical per-contract execution costs, not observed time on four
new concurrently scheduled runners. This trial is not evidence that
runtime is actually 6,338s or any fixed total.

## Immutable authority boundaries

1. **Exactly the same original 31 adversarial downstream contract scripts
   are each run once and only once.** No substitutions or fake outcomes.
2. Original standard **2,400s** and ten targeted **3,600s** subprocess
   deadlines remain unchanged, as do both worker isolation and the
   unsharded original full-contract execution path.
3. Exactly **three unchanged midchain shards**, and two independent
   **full canonical admission** jobs: physical/adversarial prefix AND nonce.
   All midchain and downstream jobs retain
   `needs: [stage-b-admission, stage-b-nonce]`, failing closed if
   either admission job fails. No signed proof bypass or skip.
4. SHA-pinned checkout, nonce-produced canonical proof+ledger manifest,
   SHA-pinned upload/download verification, build, test and action pins
   stay unchanged. No cache-hit shortcut is introduced.
5. 355-minute job timeouts, existing admission timeout bounds and all
   production / human / physical release approval gates remain unchanged.
6. `tests/workflow_stage_b_downstream_partition.py` tests canonical
   coverage, deterministic four-way assignment, worker/process limits,
   original deadlines, invalid shard rejection, invalid weights and
   fail-closed original unsharded path. `workflow_test_coverage.py`
   pins the workflow matrix and both mandatory admission predecessors.
   `CURRENT_STATE.md` is regenerated to list the added test.

## Required experimental qualification

- Run **all** full CI, exact-head Python+Go, CodeQL Python+Go on
  the identical immutable tree via a main-targeted security-only
  **draft mirror** (not mergeable release authorization).
- Two independent fully green exact-head suites, each requiring two
  admission jobs, three midchain and four downstream shards.
- Measure true wall time including queueing, slowest downstream job,
  Stage-B aggregate runner-seconds and quality/provenance failures.
- If downstream wall time is not **reproducibly lower** than #2122
  and total runner-minutes are excessive, reject this experimental
  four-shard trial in favor of original green #2122.
- **Do not merge, tag, alter V1 release authority, change main,
  bypass physical/admin gates or activate production.**
