# Stage-B seven-run measured-cost downstream balance — DRAFT, not release authority

## Baseline: first truly repeatable major Stage-B win

The two independent fully-green exact-head runs of [#2122](https://github.com/Ternedal/ModelRig/pull/2122) at
`a366b3e8e3caa23f6bbf41341d7ff843bf28c51e` both passed the original
canonical test contracts, new **parallel admission gates**, Go+Python CodeQL
and all six midchain/downstream shards:

| Exact run | Admission critical branch (s) | Slowest six shards (s) | Full measured critical path (s) |
| --- | ---: | ---: | ---: |
| Frozen V1 [37845235363](https://github.com/Ternedal/ModelRig/actions/runs/37845235363) | 5,040 | 11,116 | **16,160** |
| Safe midchain-only [37982695916](https://github.com/Ternedal/ModelRig/actions/runs/37982695916) | 5,006 | 9,649 | **14,658** |
| #2122 [38089952531](https://github.com/Ternedal/ModelRig/actions/runs/38089952531) | 3,066 | 9,117 | **12,195** |
| #2122 [38089960759](https://github.com/Ternedal/ModelRig/actions/runs/38089960759) | 2,036 | 10,279 | **12,905** |

The best measured time is ~3h23m, the more conservative second time
~3h35m. **Both were green, not simulated.** Actual admission and runner
times vary; these values are not latency guarantees.

Separate #2120's six-runners x one worker experiment also passed two
complete exact-head runs, but yielded **14,704/14,710 s** full Stage-B
with 59,498–67,018 total hosted runner-seconds, versus #2122's
12,195/12,905 s with 40,022–44,489 runner-seconds. Do not combine
unproven runner fan-out with an approved release merely to improve a
theoretical scheduling score.

## Seven observed green source histories, one safe scheduling-only edit

The last green #2122 run showed **10,279 seconds in downstream-3**,
including a deep post-release attestation lasting **3,529.5 s**, close
to its existing **3,600-second hard timeout**. The test MUST still run
and that timeout MUST NOT be increased.

This new branch preserves #2122's parallel admission, old midchain plan,
all 31 original downstream adversarial contracts, all security and cache
proof gates, all original 2,400/3,600-second per-contract timeouts and
all job limits. It updates **only the downstream contract order/assignment**
to three existing jobs with a maximum of **two isolated child subprocesses**
per job, using an auditable measured-cost table.

The original source weighted cost baseline is from five prior green
exact-head runs `37845235363`, `37942702263`,
`37982695916`, `38036507743` and `38048149969`.
Two additional independent green exact-head runs
`38089952531`, `38089960759` supplied six more original
downstream runner logs. Their full 31 individual contract durations
were extracted; original immutable job IDs are pinned in
`tests/support/stage_b_downstream_plan.py`.

Each new bounded integer weight is:

```text
round_to_nearest_integer(
  0.75 * published earlier five-source cost weight
+ 0.25 * arithmetic mean of the two new green per-contract durations
)
```

Deterministic longest-cost-first placement into 3 x 2 modeled worker
lanes (exact original ThreadPoolExecutor job submission order) leads
to **11/10/10** contracts. Modeled maximum worker time is **8,848 s**,
versus the earlier 8,793 s model; the model itself is **not a real
speed improvement**. Retrospective what-if replay against the two
actual #2122 measurement sets gives an estimated slowest shard
~7,920 / 9,667 seconds, but runner interference and batch effects
invalidate guaranteed speed claims. Another full exact-head campaign
is required before performance comparison.

## Fail closed / acceptance

- Source SHA, merge-tree-equivalence, checkout pin, signed cache manifest,
  admission prefix proof and nonce replay-negative tests all unchanged.
- 31 exact canonical downstream contracts run exactly once; no disabled
  assertions, synthetic PASS, cache bypass or permissive shard parsing.
- Original **3 downstream jobs**, **max two child processes each**,
  unsharded full chain and original 2400/3600 hard timeouts preserved.
- Fast regression asserts complete coverage, exact seven-run provenance,
  modeled worker assignment, invalid cost rejection and unsupported shards.
- CI, CodeQL Go/Python (same immutable exact-head mirror if needed),
  exact-head core and **ALL admission and six shard jobs** must be green
  on each independent run, at least **twice**, before a speed claim.
- Compare both **actual critical-path elapsed wall time and runner-seconds**
  to #2122's 12,195/12,905 s before considering an optimization.
  Reject if slower/unstable, fail-closed authority differs or resource
  cost increases without a meaningful speed gain.
- This is a **draft stacked experimental branch**. Do not merge, tag,
  re-freeze, activate production or change frozen V1
  `main=0b2ff455116f4f28a1a41704d9cb81503f17d2df`.
  Nine physical/admin release gates remain PENDING.

The empirical target of around **3h or better** is aspirational, not
an established bound. Actual on-rig Ollama response latency is wholly
separate from Stage-B GitHub qualification and remains to be benchmarked.
