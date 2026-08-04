# Kaliv Development Control Plane

This directory contains the dormant, fail-closed foundation for controlled
self-development in ModelRig. It is deliberately **not** connected to ordinary
ModelRig tool registration, Agent 3, Agent 4, GitHub writes, merge, release or
production activation.

The implementation currently reaches **Slice 10I**. A reviewed single-command task
can enter the Windows Tier-A boundary only after fresh signed physical evidence, a
command-specific signed exact-file runtime closure, deterministic workspace
staging, exact cwd validation and bounded native output capture. The staged runtime
is held immutable until the complete Job Object ends, the resulting execution
evidence is joined to canonical Git before/after/reset evidence, one exact passing
patch/receipt pair can be handed to a separate authenticated semantic review
boundary, and an approved candidate can become a deterministic offline draft-PR
readiness proposal without gaining GitHub write authority.

## Implemented authority layers

### Slices 1–4 — task, workspace, campaign and review

- immutable `kaliv-development-task/v1` with exact base SHA, path policy and
  resource budgets;
- detached exact-SHA workspaces, scoped reads/search and bounded unified patches;
- fixed command templates and canonical command receipts;
- campaign state machine with hash-chained evidence and terminal failure states;
- persisted independent structural review request/verdict contracts;
- deterministic draft-PR proposals only; merge authority remains human;
- durable controlled storage, exclusive locks and stale-writer rejection.

### Slice 5 — catalog and read-only GitHub boundary

- immutable command catalog and operator toolchain bindings;
- trusted tool IDs instead of caller-supplied executables;
- exact task, base, catalog and toolchain identities;
- network mode fixed to `deny` for project commands;
- GET-only, fixed-host GitHub adapter with redirects disabled;
- no branch, push, PR, merge, release or settings operation.

### Slice 6 — signed physical Windows evidence

- strict physical report with eleven mandatory I0b probes;
- sandbox identity, workspace access/escape, network deny, cleanup, reboot,
  memory/process limits and compatibility evidence;
- failed probes remain representable but cannot authorize execution;
- separate collector and approver actors;
- canonical HMAC-SHA256 signed envelope;
- exact task, catalog, toolchain, authority-code and workspace rebinding;
- exactly one fresh matching report required.

### Slices 7–8 — native Windows containment

- child created suspended and assigned to a kill-on-close Job Object before resume;
- process-memory and active-process limits enforced by Windows;
- deterministic zero-capability AppContainer profile;
- explicit access only to the approved reparse-free workspace;
- no network capability;
- positive-list Windows initialization environment;
- GitHub tokens, model keys, cookies, authorization headers and signing material
  are excluded;
- native CI proves identity, inside access, outside denial, network denial and
  complete process-tree cleanup.

### Slice 9 — fresh evidence to verified-only execution

- valid signed evidence issues
  `kaliv-development-execution-lease/v1`;
- lease binds task, base SHA, catalog, toolchain, report, rig, workspace and full
  Tier-A authority-code identity;
- persisted launch plans are audit evidence, not executable authority;
- the low-level executor is private;
- the only public runtime path re-verifies signed evidence before every launch;
- workspace, executable and authority code are rehashed immediately before use.

### Slices 10A–10B — deterministic runtime staging

- separate absolute operator-controlled runtime root;
- regular, non-empty, link-free and hash-bound source executable;
- deterministic no-overwrite staging under:

  ```text
  .kaliv/runtime/<tool-id>/<executable-sha256>/<source-basename>
  ```

- canonical staging receipt binds task, lease, catalog, toolchain, source identity,
  destination and bytes;
- the public runtime requires a fresh receipt and cannot launch a caller-supplied
  pre-staged executable;
- only `argv[0]` changes; arguments, cwd, timeout, environment and lease remain
  exact;
- no second public execution surface.

### Slice 10C — bounded native output evidence

- exact task `max_output_bytes` bound into launch-plan authority;
- only `NUL` stdin, stdout and stderr handles inherited through an explicit
  `PROC_THREAD_ATTRIBUTE_HANDLE_LIST`;
- stdout and stderr drained concurrently to EOF;
- every byte included in full stream SHA-256 and byte counts;
- only deterministic bounded prefixes retained as canonical base64;
- timeout kills the complete Job Object, reaches EOF and raises
  `TierAExecutionTimeout` carrying non-passing evidence;
- real-Windows fixture proves output beyond pipe-buffer size and deterministic
  cleanup.

### Slice 10D — signed runtime closure and exact cwd

- command-specific `kaliv-development-runtime-closure-manifest/v1`;
- independent HMAC-signed closure envelope;
- exact task, command, catalog, toolchain, lease, workspace, source-root,
  entrypoint, cwd and file-set binding;
- deterministic multi-file staging under:

  ```text
  .kaliv/runtime-closures/<tool-id>/<manifest-sha256>/...
  ```

- traversal, Windows device names, alternate streams, case collisions, parent-file
  conflicts, links, junctions, hardlinks, missing and extra files rejected;
- complete staged tree rehashed after staging and immediately before launch;
- launch-plan schema v3 binds manifest, signature, staging receipt and
  `working_directory_sha256`;
- workspace-relative nested cwd is revalidated inside `CreateProcessW` without
  granting caller-selected cwd authority.

### Slice 10E — reviewed standalone version-check closure

- self-contained Go implementation at `backend/cmd/modelrig-version-check`;
- isolated one-command catalog using tool ID `modelrig-version-check`;
- the default catalog remains unchanged, avoiding silent authority replacement;
- `ModelRigVersionCheckClosureBuilder` emits an unsigned single-file manifest
  proposal only;
- exact entrypoint, empty argument vector, root cwd, tool hash, lease, catalog,
  workspace and runtime-root identities required;
- extra runtime files/directories and the legacy Python profile fail closed.

See `VERSION_CHECK_CLOSURE.md` for the isolated catalog and operator flow.

### Slice 10F — runtime lifetime immutability

- the exact staged closure is reverified after workspace ACL provisioning;
- every closure directory and file receives a protected read/execute-only DACL for
  the operator SID and exact AppContainer package SID;
- open handles permit read sharing only and deny new write/delete-sharing opens;
- overwrite, replacement, rename, deletion and file insertion are denied while the
  Job Object lives;
- original DACLs are retained by handle and restored only after confirmed Job
  Object closure;
- ambiguous process-tree cleanup retains the guard instead of reopening the tree;
- native Windows tests prove AppContainer sabotage, concurrent host sabotage,
  unchanged bytes/tree, DACL restoration, output capture, nested cwd and timeout
  cleanup through the same path.

### Slice 10G — Git-aware Tier-A command receipt

- `run_single_verified_tier_a_command_with_receipt` accepts no caller-selected
  command ID or arguments;
- the task must grant exactly one command and require that same command as evidence;
- `HEAD` must equal the exact task base before execution;
- an optional staged patch is accepted, while unstaged and untracked input fail
  before Tier-A is called;
- canonical Git snapshots bind HEAD, staged and unstaged binary/full-index diff
  hashes and sizes, plus the NUL-delimited untracked-path identity;
- the orchestrator calls only `run_verified_tier_a_command`;
- deterministic runtime staging is removed after Job Object and lifetime-guard
  completion and before the after snapshot;
- any Git mutation creates a non-passing receipt, triggers exact-base reset and
  requires a clean reset snapshot;
- timeout keeps the complete non-passing Tier-A result and Git evidence;
- authority bundle v6 includes the receipt orchestrator and invalidates all
  v5-or-earlier physical reports;
- portable and real-Windows tests prove staged-patch preservation, mutation/reset,
  timeout evidence, canonical reload and the actual AppContainer/Job Object path.

### Slice 10H — authenticated semantic-review evidence

- a canonical offline request embeds the exact staged patch bytes, full passing
  Slice 10G receipt, task criteria, fixed review-policy hash and current v6
  execution-authority hash;
- request construction exposes no workspace, command, argv, catalog or toolchain
  selection surface;
- the receipt must prove identical before/after snapshots, no reset and passing
  Tier-A execution;
- patch hash and size must match both Git snapshots exactly;
- structured verdicts assess every acceptance criterion in order and record
  bounded findings with explicit severity;
- approval requires every criterion satisfied and zero findings;
- developer and reviewer actors must differ;
- reviewer-only HMAC keys are bound to exact reviewer actors;
- verification rejects task, patch, receipt, policy, execution-authority, actor or
  signature mismatch;
- canonical request/verdict files are bounded, link-free and create-once;
- the module is outside the Tier-A v6 execution bundle and cannot launch commands,
  reset Git or write to GitHub.

Slice 10H supplies the trustable artifact boundary, not a built-in AI reviewer.
A separately operated human or model reviewer must actually analyze the canonical
request and produce the structured verdict.

### Slice 10I — authenticated draft-PR readiness proposal

- `kaliv-development-authenticated-draft-pr-readiness-proposal/v1` embeds the
  complete task, exact semantic-review request and signed approval verdict;
- the builder re-verifies the reviewer signature and current v6 execution-authority
  identity before creating an artifact;
- request-changes, reject, uncertain criteria, non-satisfied criteria or findings
  cannot be represented as ready;
- staged patch, Tier-A receipt, reviewer actor/key, review policy and proposal
  policy remain independently hash-bound;
- repository, proposed head branch, title, body, draft flag and merge authority are
  not caller-selected;
- the head branch is derived from task ID, exact base SHA and patch SHA;
- title and body are deterministic and fail reload if altered;
- only a canonical base branch may be supplied, defaulting to `main`;
- canonical readiness files are bounded, absolute, link-free and create-once;
- `DraftPrReadinessGate` re-verifies the exact task, reviewer trust and current
  execution authority;
- the module has no branch-push, PR-create/update, reviewer-request, merge, release,
  settings or deployment adapter.

Slice 10I is offline proposal evidence only. It does not publish the deterministic
branch name or body anywhere, and a human retains all merge authority.

See `TIER_A_EXECUTION.md`, `RUNTIME_STAGING.md`,
`RUNTIME_LIFETIME_GUARD.md`, `TIER_A_COMMAND_RECEIPT.md`, `SEMANTIC_REVIEW.md`
and `DRAFT_PR_READINESS.md` for the complete authority, filesystem, receipt,
review and proposal rules.

## Reviewed command authority

The default registry remains empty. Naming a command ID in a task does not make it
executable. The command must also exist in an immutable catalog, have an exact
operator tool binding, pass fresh signed physical evidence and complete the signed
runtime-closure chain.

The default ModelRig catalog contains:

- `modelrig.version.check`;
- `modelrig.devcontrol.tests`;
- `modelrig.workflow.test-coverage`;
- `modelrig.backend.vet`;
- `modelrig.backend.tests`.

Slice 10E's standalone version checker uses a separate isolated catalog rather
than changing this list. Slice 10G further requires a one-command task before its
Git-aware orchestration surface can run. Slice 10H consumes only completed evidence
and cannot add or select commands. Slice 10I consumes only one verified semantic
approval and cannot publish its proposed branch or pull request. Optional commands
remain deferred rather than added ambiguously.

## Physical evidence operator flow

The physical harness writes one canonical unsigned report matching
`schemas/windows-isolation-physical-report-v1.schema.json`. Signing is a separate
operator action and its key must stay outside the developer workspace.

```bash
cd devcontrol
PYTHONPATH=src python -m kaliv_dev_control sign-physical-report \
  C:/ModelRigEvidence/i0b-unsigned.json \
  C:/ModelRigEvidence/i0b-signed.json \
  --key-file C:/ModelRigOperator/isolation.key \
  --key-id operator-key-2026
```

The signed artifact SHA-256 must be named by the exact task attestation.
Independent verification uses:

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
invalidates the independence claim. The same separation rule applies to the
semantic-review key: it must remain unavailable to the developer/execution side.

## Explicit remaining boundaries

The control plane still cannot:

- run arbitrary shell commands or model-selected executable arguments;
- execute without exact fresh signed physical evidence;
- manufacture a genuine I0b result without physical probes;
- automatically discover a transitive PE/DLL, Python or Go runtime closure;
- claim lifetime protection against a separate administrator or kernel component;
- perform semantic analysis without a separately operated reviewer;
- provision, rotate or revoke reviewer keys;
- create the proposed branch, commit or push it;
- create, update or mark a pull request ready for review;
- request GitHub reviewers or alter repository settings;
- merge, release, deploy or activate its own work.

No registered ModelRig tool calls the Tier-A bridge, receipt orchestrator,
semantic-review boundary or draft-readiness builder. Hosted CI uses synthetic
evidence to prove software wiring and does not replace the selected rig's physical
eleven-probe campaign or a real independent semantic review.

## Run tests

```bash
cd devcontrol
python -m unittest discover -s tests -v
```

The portable suite is included in ModelRig's shared PR/release gate. It proves the
10H artifact, signature, actor-separation and tamper-rejection contracts plus the
10I deterministic, draft-only readiness artifact. The native Windows gate
separately proves Job Object, AppContainer, environment, signed physical evidence,
exact runtime closure, lifetime immutability, nested cwd, strict handle
inheritance, bounded output, timeout cleanup and a real Git-aware Tier-A receipt.

## Validate a task

```bash
cd devcontrol
PYTHONPATH=src python -m kaliv_dev_control validate-task examples/task.json
```

The package remains dependency-free so authority and evidence primitives can be
reviewed without bootstrapping an agent execution environment.
