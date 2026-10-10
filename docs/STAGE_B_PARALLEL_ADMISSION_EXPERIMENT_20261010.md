# DRAFT — two independent fail-closed Stage-B admission jobs

**Immutable V1 main: unchanged. Experimental branch from fully-green midchain-only
PR #2103, not a release candidate.** The nine physical/admin gates are pending.

## Measured cause and hypothesis

GitHub admission in the first completed six-runner trial took **5,067 s**.
Its deep ADR-DC-032/033 chain took **2,467.8 s** after the shallow prefix
(~517.5 s critical path), then an independent focused ADR-DC-033 nonce-reuse
guard ran **1,987.7 s**. Both independently reconstruct deep provenance.
They do **not** need the same mutable directory, credentials or nonce
ledger. Instead of serial execution on one hosted runner, this prototype
qualifies these two branches **concurrently on separate GitHub jobs**.

The expected limit if runner speed stayed constant is approximately
`max(shallow + shared-deep, nonce)` instead of
`shallow + shared-deep + nonce`, plus runner setup overhead.
**This is a hypothesis, not measured acceleration.** Additional runner
allocation increases CI resource usage. All workflows remain subject to
GitHub scheduling and test variance.

## Authority-preserving execution graph

```text
                       ┌───────────────────────────────────────────────┐
                       │ stage-b-admission (original name)             │
Exact HEAD ────────┬──>│ FULL physical gate → all transitive ADR-026  │
                   │   │ → ADR-030/031 → shared ADR-032/033 deep pair   │
                   │   └───────────────────────┬───────────────────────┘
                   │                           │ REQUIRED SUCCESS
                   │   ┌───────────────────────┴───────────────────────┐
                   └──>│ stage-b-nonce (independent hosted runner)     │
                       │ canonical ADR-033 adversarial nonce-reuse     │
                       │ → authentic proofs.json + start-ledger        │
                       │ → seal and verify pinned exact-head manifest  │
                       │ → upload exact-head cache                     │
                       └───────────────────────┬───────────────────────┘
                                               │ REQUIRED SUCCESS BOTH
                                               ▼
                                3 midchain + 3 downstream jobs
                                each fetches and verifies original
                                exact-head cache manifest; any failure
                                prevents shards from starting
```

- **Canonical tests and negative/adversarial assertions are not skipped,
  rewritten, or substituted.** The prefix retains the original full
  `workflow_stage_b_physical_gate.py` transitive ADR-026 suite and
  executes exactly the same two shallow and shared deep pair contracts.
- The nonce job directly runs the existing canonical focused
  `rsi_pilot_exact_task_execution_admission_nonce_reuse_contract.py`
  via the original bounded stage-B router. This test independently
  constructs signed proofs and replay-negative assertions.
- Both branches check out the **same exact pinned head SHA**. The nonce
  branch seals, verifies and publishes proof cache just as original
  admission did. Every downstream shard verifies that manifest.
- **Fail-closed job graph:**
  `needs: [stage-b-admission, stage-b-nonce]`.
  No shard starts until BOTH jobs succeed. A failure in either blocks
  *all* shards.
- **No cache-hit shortcut**: intentionally removed admission cache
  restore. Each new exact-head run physically executes both mandatory
  admission branches on its exact immutable candidate commit.
- Original `all` and `admission` router modes remain unmodified
  (still perform the complete sequential canonical qualification).
  New `admission-prefix` executes only the full prefix, and
  `admission-nonce` executes only the original nonce phase. Both
  reject active shard labels and invalid modes fail closed.
- Original 3000/7200-second shared-deep/nonce subprocess bounds, and
  all downstream 2400/3600-second bounds, job timeout 355 minutes,
  process isolation, SHA pins, manifest verification, production and
  release authorizations are unchanged.
- An added offline regression test proves routing, no skipped prefix/nonce,
  rejection of inadmissible shard labels, and invalid mode rejection.
  Existing workflow tests lock that the job graph requires both jobs
  and that no cache-hit skip can bypass a canonical test.

## Acceptance and stopping criteria

1. Standard CI and exact-head core SUCCESS, Go+Python CodeQL both
   PASS against the **exact same commit and tree** (security-only
   draft mirror may be used because repository CodeQL filters to main).
2. Complete first Stage-B exact-head: **both independent admission jobs
   and all six original shards PASS**. No evidence/nonce failures.
3. At least one **second independent** fully-green exact-head run,
   comparing critical path and total runner-seconds to #2103 and
   previously successful frozen V1. Measure admission as
   max(completion of prefix and nonce) - first admission job start.
4. Reject on lost tests, invalid evidence, timeout relaxation, unsigned
   proof reuse, increased false accept, status failure, or no material
   repeatable speed gain. Do not merge either PR, alter main, tag,
   release or activate production.

**Important:** This only experiments with Stage-B CI wall time.
It does not improve local Ollama inference throughput or Kaliv user
perceived voice latency; those require rig-side runtime measurements.
