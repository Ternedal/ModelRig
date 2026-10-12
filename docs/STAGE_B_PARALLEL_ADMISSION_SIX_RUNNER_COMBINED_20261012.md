# Experimental candidate: parallel admission + two-run six-worker downstream rebalance

**PERFORMANCE EXPERIMENT ONLY. DO NOT MERGE.** Frozen ModelRig V1 main
remains at `0b2ff455116f4f28a1a41704d9cb81503f17d2df`. Nine physical
and administrative release gates remain pending.

## Source observations — two real full green six-runner campaigns

First six-runner candidate [#2120](https://github.com/Ternedal/ModelRig/pull/2120)
was **fully green** in both exact-head runs, but no overall faster than
three-runner baselines: [run 38083540450](https://github.com/Ternedal/ModelRig/actions/runs/38083540450)
had Stage-B critical elapsed 14,704 s; [run 38083575692](https://github.com/Ternedal/ModelRig/actions/runs/38083575692)
14,710 s. Its repeated bottleneck was downstream-4 with
9,633 / 9,640 s, while other jobs were often much lighter.

Each original canonical contract is observed in two real, complete,
successful independent hosted GitHub runs, extracted from exactly
**12 pinned downstream job logs**:

- Run 38083540450, jobs 114321321398, 114321321450,
  114321321405, 114321321390, 114321321392, 114321321407.
- Run 38083575692, jobs 114336594175, 114336594115,
  114336594156, 114336594206, 114336594173, 114336594220.

The original contract set is still exactly 31 files. For each file,
`COST_SECONDS` is `round(mean(original PASS duration in these two runs))`
with two complete unique entries, not a fabricated or inferred metric.
The unchanged deterministic largest-first/smallest-load allocator now
produces exactly 6 downstream groups containing **5/5/5/6/5/5** contracts.
It assigns historical average per-runner sums
**7242 / 7023 / 7070 / 7619 / 6944 / 7031 seconds**.

When counterfactually replayed against each exact historical file duration
set, the simulated loads are:
- First: **7821 / 8006 / 7664 / 8330 / 7864 / 7655 s**.
- Second: **6659 / 6041 / 6477 / 6908 / 6023 / 6406 s**.

**WARNING: These are simulations on historical isolated per-file timings,
NOT a completed execution of this new assignment.** Actual jobs have
CPU/runner variance and different artifact/setup costs. No speedup may be
claimed until the exact new candidate is measured at least twice end to end.

## Combining with separately measured fastest admission

Parallel admission [#2122](https://github.com/Ternedal/ModelRig/pull/2122)
is already independently fully green, twice:

- [run 38089952531](https://github.com/Ternedal/ModelRig/actions/runs/38089952531):
  admission 3,066 s prefix / 2,035 s nonce, real Stage-B elapsed **12,195 s**
  from first admission start to last shard finish.
- [run 38089960759](https://github.com/Ternedal/ModelRig/actions/runs/38089960759):
  admission 1,583 s prefix / 2,036 s nonce, total **12,905 s**.

That reduced measured Stage-B critical path from frozen V1 **16,160 s**
in [run 37845235363](https://github.com/Ternedal/ModelRig/actions/runs/37845235363)
to **12,195–12,905 s** — around **20–24.5%**, with no bypass.
(The result depends on relative runner speeds and admission variance.)

This combined branch is based on #2122; it keeps BOTH fully-qualified
independent admission jobs, neither skipped, with
`needs: [stage-b-admission, stage-b-nonce]` on every shard. It only
changes downstream sharding from three jobs x two isolated children to
six jobs x one child each, plus the newly measured cost table.

## Invariants and cost

- Original **31 exact canonical downstream contract files all execute**
  in isolated processes. No removal, mock, skip or replacement.
- One isolated child per downstream job. Across six jobs, max **six**
  concurrent downstream subprocesses, same as former 3 x 2.
- Three original midchain jobs still execute exactly the full same
  contracts and unchanged subprocess limits.
- Two original independent admission jobs run all real original
  security tests, including shared deep attestations and focused
  nonce-replay negatives, and BOTH are required for all shards.
- Exact pinned checkout SHA; original proof/ledger creation,
  cryptographic manifest create/verify/upload, and per-shard artifact
  verification. Admission cache-hit skip is still forbidden.
- Original standard/deep **2400/3600-second** downstream contract
  deadlines and original 355-minute hosted runner job bound. Other
  shared-deep 3000s/nonce 7200s bounds are unchanged. No weakening of
  source security checks, CodeQL, branch protections or release gates.
- The new version uses **six downstream hosted runners**, not three;
  total billed runner-minutes can increase even if completion time
  drops. Record both elapsed wall time and sum of billable job wall
  time before recommending it.

## Acceptance

Require two independent full exact-head green runs on SAME immutable
HEAD and matching Git tree, with standard CI, Go+Python CodeQL and
all original physical/security regression checks green; measure
admission→last-shard elapsed and runtime/cost trade-offs against
previous #2122 and #2120. This branch is a draft and is **NOT**
release authority. If speed/cost quality does not improve repeatably,
reject the combined experiment. Never tag, activate or change V1 main.
