# Stage-B: five cost-balanced downstream shards — EXPERIMENT, NEVER MERGE

**Frozen V1 authority unchanged.** This CI-only draft is stacked on the
independently **two-run fully green** four-downstream-shard experiment
[PR #2136](https://github.com/Ternedal/ModelRig/pull/2136), whose exact head
is `94a6763e9dca5b8f6a26441b41d15a1ef77370ba`.
Keep the production release freeze and nine physical/admin gates intact.

## Verified base and the question

Two fully green exact-head Stage-B runs of #2136:
- [38236742180](https://github.com/Ternedal/ModelRig/actions/runs/38236742180):
  admission start to last shard **9,424 s (2h37m04s)**;
  slowest downstream **7,430 s**; total Stage-B runner time **36,762 s**.
- [38236788809](https://github.com/Ternedal/ModelRig/actions/runs/38236788809):
  end-to-end **9,742 s (2h42m22s)**;
  slowest downstream **7,568 s**; total Stage-B runner time **42,644 s**.

Original frozen V1 [37845235363](https://github.com/Ternedal/ModelRig/actions/runs/37845235363):
**16,160 s**, 49,920 Stage-B runner seconds. Four shards therefore
improved critical-wall time **41.7% / 39.7%** in two independent full green
runs, *without* requiring more aggregate runner time on either observation.

The new five-shard trial tests whether a modest extra hosted runner can
cut the longest downstream critical path further, not whether removing
security checks works. It must be measured, not assumed.

## Bounded, auditable change

- Use the **exact same original 31 canonical adversarial contracts**;
  a deterministic measured-cost planner assigns all exactly once.
- Change only downstream matrix count from 4 to **5 jobs**;
  each hosted runner retains **at most two** isolated contract subprocesses.
  Maximum aggregate downstream child concurrency moves **8 -> 10**;
  it is not an increase in per-runner or per-contract resource authority.
- Keep all 3 original midchain jobs, both original successful
  `stage-b-admission` and `stage-b-nonce` prerequisites and their
  real independent checks; `needs: [stage-b-admission, stage-b-nonce]`.
- Keep the original **2,400/3,600 seconds per contract** hard timeouts,
  original 355 minute job timeout, fail-closed invalid shard handling,
  exact-head checkout SHA, cryptographic cache manifest, unchanged
  original full unsharded path, negative nonce/replay, authority and
  release checks. No relaxed assertion, production change or invented PASS.
- The **five existing fully green measured-cost runs** used by parent
  #2136 supply the original cost map unchanged; no fresh timing
  fabrication or cost-table overfitting.
- Planner output canonical group sizes: **6 / 7 / 6 / 6 / 6**.
  Projection from the original historical two-process-source weights:
  per-shard worst two-worker modeled seconds
  **5,496 / 5,526 / 4,814 / 4,984 / 4,737**.
  Parent four-shard projection maximum = **6,338 s**.
  **Do not treat a modeled 5,526 s as measured runtime, nor assume
  equal CPU contention when runner count changes.**

## Acceptance gates

1. All fast CI tests / standard workflows, exact-head core and
   same-HEAD/same-tree Go+Python CodeQL MUST PASS.
2. Each of **two independent, full exact-head runs** MUST prove both
   independent admissions and **all three midchain and five downstream**
   jobs succeed with zero waived or missing contracts.
3. Compare **real** admission start -> last shard, slowest downstream,
   and aggregate Stage-B runner-seconds against the two #2136 runs.
   Additional CI queueing and billed runner time count against the trial.
4. Reject unless a genuine repeatable speed improvement or a
   demonstrable security-neutral resource trade-off is achieved.
   Do **not** change frozen V1 main, merge, tag, re-freeze, activate
   production, infer physical acceptance or lift a timeout.

This is CI qualification runtime, not the inference responsiveness
of Ollama or Kaliv on the user's two RTX 3060 GPUs.
