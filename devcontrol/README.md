# Kaliv Development Control Plane

This directory contains the dormant, fail-closed foundation for controlled
self-development in ModelRig. It is deliberately **not** connected to ordinary
ModelRig tool registration, Agent 3, Agent 4, GitHub writes, merge, release or
production activation.

The implementation currently reaches Slice 10C: a reviewed catalog command can
only enter the Windows Tier-A boundary after exact signed physical evidence has
been freshly verified, its operator-bound executable has been staged into the
signed workspace, and its native output is captured under the signed task budget.

## Current slices

### Slice 1 — task authority and workspace

- immutable `kaliv-development-task/v1` contract;
- exact base SHA, risk and resource budgets;
- normalized allowed and protected path policy;
- deterministic scope evidence receipts;
- ephemeral detached exact-SHA worktrees.

### Slice 2 — bounded local code work

- scoped UTF-8 reads and literal search;
- `.git` denied even under broad task scope;
- bounded unified-diff parsing and staged-diff verification;
- binary, rename/copy, symlink and submodule patches rejected;
- fixed command templates and deterministic command receipts;
- automatic reset when a command mutates repository state.

### Slice 3 — campaign and review integrity

- immutable campaign states and legal transitions;
- SHA-256 hash chain over transitions and evidence references;
- terminal failure and cancellation states;
- strict persisted review request and verdict validation;
- developer/reviewer actor separation;
- readiness can reach draft PR only; merge authority remains human.

The structural reviewer validates evidence consistency. It does not claim semantic
code understanding and cannot rewrite the task, tests or protected policy.

### Slice 4 — durable state and draft proposal

- canonical campaign JSON under a controlled root;
- exclusive locks and compare-and-swap updates;
- stale-writer, tampered-record and symlink-root rejection;
- deterministic `kaliv-development-draft-pr-proposal/v1` artifacts;
- dedicated `kaliv-dev/` branch namespace;
- no Git or GitHub write operation.

### Slice 5 — command catalog and exact-SHA GitHub reads

- immutable, versioned ModelRig command catalog;
- trusted tool IDs rather than caller-supplied executable paths;
- separate absolute tool bindings with independent SHA-256 verification;
- task, base SHA, catalog and toolchain binding;
- network mode structurally fixed to `deny` for project commands;
- default isolation verifier rejects execution;
- fixed-host, GET-only GitHub adapter with redirects disabled;
- exact base-commit and task-scope verification;
- no branch, push, PR, merge, release or settings operation.

### Slice 6 — signed physical Windows-isolation evidence

- strict `kaliv-windows-isolation-physical-report/v1` contract;
- eleven mandatory I0b probes covering sandbox identity, workspace access and
  escape, network deny, timeout/crash/cancel/reboot cleanup, memory/process limits
  and compatibility;
- failed probes remain representable but cannot authorize execution;
- collector and approver must be different actors;
- changed boot markers prove the reboot boundary;
- canonical HMAC-SHA256 signed envelope;
- signing keys and evidence require separate absolute, non-symlink operator paths;
- exact task, catalog, toolchain, authority bundle and workspace rebinding;
- exactly one fresh matching report is required.

### Slice 7 — Windows-native process containment

- child process created suspended;
- Job Object configured and assigned before first execution;
- kill-on-close owns the complete process tree;
- process memory and active-process limits are kernel-enforced;
- Tier-A UI restrictions applied before resume;
- setup, assignment, resume and cleanup failures fail closed;
- native Windows CI proves the kernel behavior;
- no registered tool opts into the boundary.

### Slice 8 — AppContainer workspace and network boundary

- deterministic regular AppContainer profile per canonical workspace;
- Package SID receives explicit access only to the approved reparse-free tree;
- zero capabilities and no network capability;
- launch rejects mismatched profile, ACL receipt, executable, root or link;
- executable must be a regular file physically inside the workspace;
- positive-list Windows initialization environment;
- only four exact reviewed non-secret application values are permitted;
- injected GitHub/runtime tokens, model keys, cookies, authorization headers and
  signing material are excluded;
- native tests prove AppContainer identity, inside access, outside denial and
  zero-capability loopback denial.

### Slice 9 — signed evidence to verified-only execution

- valid signed evidence issues an immutable
  `kaliv-development-execution-lease/v1`;
- lease binds task, base SHA, catalog, toolchain, report, rig, workspace and full
  Tier-A authority-code hash;
- launch planning produces canonical audit evidence;
- persisted plans are not independently executable authority;
- the low-level plan executor is private;
- the only public runtime path repeats signed-evidence verification immediately
  before launch;
- workspace, executable and authority code are rehashed before execution.

### Slice 10A — trusted runtime staging

- separate absolute operator-controlled runtime root;
- source executable must be regular, non-empty, link-free and hash-bound;
- deterministic destination:

  ```text
  .kaliv/runtime/<tool-id>/<executable-sha256>/<source-basename>
  ```

- copy is hashed while written, flushed, fsynced and atomically published without
  overwrite;
- existing identical bytes are reusable; different bytes fail closed;
- canonical `kaliv-development-runtime-staging-receipt/v1` binds the complete
  task, lease, catalog, toolchain, source identity, destination and bytes;
- verification rehashes both source and staged copy.

### Slice 10B — staging-bound Tier-A runtime

- `runtime_staging.py` is part of the signed Tier-A authority bundle;
- all older physical reports are invalid after this authority-bundle change;
- `run_verified_tier_a_command` requires an explicit `trusted_runtime_root`;
- every call freshly verifies evidence, issues a lease, stages the executable,
  verifies the receipt, builds a new launch plan and rehashes authority before
  entering AppContainer;
- `bind_for_launch` creates a new one-command leased registry;
- only `argv[0]` changes to the verified workspace copy;
- arguments, cwd, timeout, environment, lease, catalog, toolchain and attestation
  remain exact;
- the original registry is not mutated;
- no second public execution surface is introduced.

### Slice 10C — bounded native output evidence

- launch-plan schema v2 binds the task's exact `max_output_bytes` budget;
- the authority bundle is bumped to v3, invalidating all older reports;
- the prior lease/materialization implementation remains byte-identical in a
  private core module, while the public bridge owns the only runtime entry point;
- `CreateProcessW` receives only three inherited standard handles through
  `PROC_THREAD_ATTRIBUTE_HANDLE_LIST`;
- unrelated parent handles cannot be inherited;
- stdout and stderr are drained concurrently to EOF;
- every byte contributes to a full stream SHA-256 and total byte count;
- only deterministic per-stream prefixes are retained in memory;
- binary prefixes are stored as canonical base64 in
  `kaliv-development-tier-a-execution-result/v1`;
- timeout terminates and closes the Job Object, finalizes both stream identities
  and raises `TierAExecutionTimeout` carrying non-passing evidence;
- a statically linked real-Windows fixture proves output beyond pipe-buffer size,
  truncation, separate stream hashes and timeout EOF cleanup.

See `TIER_A_EXECUTION.md` and `RUNTIME_STAGING.md` for the complete authority
chains and deliberate limitations.

## Reviewed command authority

The default registry remains empty. A task naming a command ID does not make it
executable. A command must also exist in the immutable catalog, have an exact
operator tool binding, pass the signed physical evidence verifier and complete
the trusted staging chain.

The current ModelRig catalog contains:

- `modelrig.version.check`;
- `modelrig.devcontrol.tests`;
- `modelrig.workflow.test-coverage`;
- `modelrig.backend.vet`;
- `modelrig.backend.tests`.

Task schema v1 treats every granted command as required draft-PR evidence. Optional
commands are deferred to a future schema version rather than added ambiguously.

## Physical evidence operator flow

The physical harness writes one canonical unsigned report matching
`schemas/windows-isolation-physical-report-v1.schema.json`. Signing is a separate
operator action and its key must remain outside the developer workspace.

```bash
cd devcontrol
PYTHONPATH=src python -m kaliv_dev_control sign-physical-report \
  C:/ModelRigEvidence/i0b-unsigned.json \
  C:/ModelRigEvidence/i0b-signed.json \
  --key-file C:/ModelRigOperator/isolation.key \
  --key-id operator-key-2026
```

The printed signed-artifact SHA-256 must be named by the exact task's isolation
attestation. Independent verification uses:

```bash
cd devcontrol
PYTHONPATH=src python -m kaliv_dev_control verify-physical-report \
  C:/ModelRigEvidence/attestation.json \
  --evidence-root C:/ModelRigEvidence \
  --key-file C:/ModelRigOperator/isolation.key \
  --key-id operator-key-2026
```

HMAC is suitable only while the signing key is protected by the separate operator
account/process boundary required by I0b. A key copied into the agent workspace
invalidates the independence claim.

## Explicit non-goals and remaining boundaries

The current control plane cannot:

- run arbitrary shell commands or accept model-selected executable arguments;
- execute without exact fresh signed physical evidence;
- manufacture a genuine I0b result without physical probes;
- stage a complete DLL, Python or Go runtime closure;
- execute catalog commands whose working directory is not the workspace root;
- claim a complete development `CommandReceipt` from output alone; Git workspace
  before/after identity and reset evidence remain separate;
- perform independent semantic AI review;
- push branches or create/update/merge pull requests;
- alter repository settings, runtime feature switches or production deployment;
- merge, release or activate its own work.

No registered ModelRig tool calls the Tier-A bridge. The hosted Windows proof uses
synthetic signed evidence for software wiring and does not replace the selected
rig's complete physical eleven-probe campaign.

## Run tests

```bash
cd devcontrol
python -m unittest discover -s tests -v
```

The same portable suite is automatically included in ModelRig's shared PR and
release gate. The real-Windows gate separately proves Job Object, AppContainer,
environment, signed evidence, trusted staging, strict inherited handles, bounded
output, timeout cleanup and existing ToolHost behavior.

## Validate a task

```bash
cd devcontrol
PYTHONPATH=src python -m kaliv_dev_control validate-task examples/task.json
```

The package remains dependency-free so its authority and evidence primitives can
be reviewed without bootstrapping an agent execution environment.
