# Kaliv Development Control Plane

This directory contains the isolated foundation for controlled self-development.
It is deliberately **not** wired into ModelRig runtime, Agent 3, Agent 4,
release, merge, or production activation.

## Current slices

### Slice 1 — authority and workspace foundation

- immutable `kaliv-development-task/v1` contract;
- exact-SHA and resource-budget validation;
- normalized allowed/protected path policy;
- fail-closed change-scope evaluation;
- deterministic scope evidence receipts;
- ephemeral detached-worktree lifecycle;
- dependency-free CLI and JSON Schema.

### Slice 2 — bounded local code work

- UTF-8 file reads and literal search inside task-approved paths;
- `.git` metadata denied even when a task uses a broad path allowlist;
- unified-diff parsing with line and file budgets;
- rejection of binary patches, rename/copy operations, symlink and submodule modes;
- `git apply --check --index` before a patch is staged;
- verification that the real staged diff exactly matches the parsed patch authority;
- immutable command templates with fixed arguments and environment;
- command receipts containing output hashes, duration and workspace fingerprints;
- automatic reset to the exact task base SHA if a command changes repository state;
- the existing CI test-coverage contract runs all `devcontrol/tests` in PR and release gates.

### Slice 3 — campaign integrity and structural review

- immutable campaign state with legal transition rules;
- a SHA-256 hash chain over every state transition and evidence reference;
- terminal failed and cancelled states that cannot silently resume;
- review requests bound to the task, staged patch and command receipts;
- strict reload validation for persisted review requests and verdicts;
- a reviewer actor that must differ from the developer actor;
- a structural reviewer that refuses missing or failed command evidence;
- a gate that can only declare `ready_for_draft_pr`;
- merge authority remains structurally and operationally human.

The reviewer in this slice checks evidence consistency and separation of roles. It
does **not** claim to understand whether the implementation is semantically good.
A later semantic reviewer must remain separate from the developer execution and
must not be allowed to rewrite the task, tests or protected evaluation policy.

### Slice 4 — durable campaign state and draft proposal

- canonical campaign JSON persisted under a controlled root;
- exclusive per-campaign file locks;
- compare-and-swap updates that permit exactly one hash-chained append;
- rejection of stale writers, tampered records, irregular files and symlink roots;
- a deterministic `kaliv-development-draft-pr-proposal/v1` artifact;
- proposal hashes bind task, campaign head, review request and review verdict;
- branch names use the dedicated `kaliv-dev/` namespace;
- generated PR text explicitly preserves human review and merge authority.

The proposal builder performs no Git or GitHub write. It creates reviewable data
only. A later GitHub write adapter must consume this artifact with a credential
that cannot merge, release, modify repository settings or write to `main`.

### Slice 5 — ModelRig command catalog and exact-SHA GitHub reads

- immutable, versioned command catalog for five reviewed ModelRig checks;
- catalog entries name trusted tool IDs rather than accepting executable paths;
- separately supplied absolute tool bindings are hash-verified;
- materialization binds task SHA, base SHA, catalog hash and toolchain hash;
- every project command requires an independently verified OS boundary;
- network mode for project command execution is structurally fixed to `deny`;
- the default isolation verifier rejects all execution;
- fixed-host, GET-only GitHub transport with redirects disabled;
- base-commit verification against the task's exact SHA;
- one-file reads restricted to task-readable, non-protected paths at that SHA;
- strict response type, blob SHA, decoded size, UTF-8 and response-budget checks;
- receipts hash response bodies and ETags without containing credentials.

The GitHub adapter is deliberately not a generic HTTP client. A model cannot
choose its host, repository, HTTP method or ref. This slice grants no branch,
push, pull-request, review, merge, release or repository-settings operation.

### Slice 6 — signed physical Windows-isolation evidence

- strict `kaliv-windows-isolation-physical-report/v1` contract;
- exact binding to task, base SHA, command catalog and toolchain;
- eleven mandatory I0b probes covering token, workspace, network, lifecycle,
  reboot, memory, process limits and compatibility;
- failed probes remain representable as evidence but can never authorize execution;
- collector and approver must be separate actors;
- reboot markers must prove a changed boot boundary;
- canonical HMAC-signed evidence envelope with operator-controlled key ID;
- operator keys are loaded only from absolute, non-symlink regular files;
- evidence is accepted only from a non-symlink operator-owned root;
- evidence hash must already be named by the task's isolation attestation;
- signature, freshness, exact authority and all probes are verified again;
- exactly one matching report is required; ambiguity fails closed;
- the verifier plugs directly into `CatalogMaterializer`.

This slice defines and verifies physical evidence. It does not manufacture a
physical result and does not implement the Windows Job Object or restricted-token
boundary. Until the real rig produces and an operator approves a complete report,
the default verifier still rejects all project-command execution.

## Command authority

The default command registry remains intentionally empty. A task may name command
IDs, but nothing executes merely because an ID appears in a task. The ModelRig
catalog must first be materialized with an operator-controlled toolchain and an
isolation attestation bound to the exact task, catalog and toolchain.

Models and task payloads cannot supply executables, arguments, working directories,
environment variables, isolation evidence or network policy. The catalog currently
contains only:

- `modelrig.version.check`;
- `modelrig.devcontrol.tests`;
- `modelrig.workflow.test-coverage`;
- `modelrig.backend.vet`;
- `modelrig.backend.tests`.

In task schema v1, every command ID granted to a task is also required evidence
for draft-PR readiness. Optional commands are deliberately deferred to a future
schema version instead of being introduced through an ambiguous in-place change.

## Physical evidence operator flow

The physical harness must first write one canonical unsigned report matching
`schemas/windows-isolation-physical-report-v1.schema.json`. Signing is a separate
operator action and the key file must live outside the developer workspace.

```bash
cd devcontrol
PYTHONPATH=src python -m kaliv_dev_control sign-physical-report \
  C:/ModelRigEvidence/i0b-unsigned.json \
  C:/ModelRigEvidence/i0b-signed.json \
  --key-file C:/ModelRigOperator/isolation.key \
  --key-id operator-key-2026
```

The command prints only the signed artifact SHA-256. That hash must be included in
the exact task's `kaliv-development-isolation-attestation/v1` evidence list.

An operator can verify the finished evidence independently:

```bash
cd devcontrol
PYTHONPATH=src python -m kaliv_dev_control verify-physical-report \
  C:/ModelRigEvidence/attestation.json \
  --evidence-root C:/ModelRigEvidence \
  --key-file C:/ModelRigOperator/isolation.key \
  --key-id operator-key-2026
```

HMAC is suitable here only when the signing key is protected by the separate
operator account/process boundary described by I0b. A key copied into the agent
workspace would invalidate the independence claim even though the signature is
mathematically valid.

## Explicit non-goals

The current control plane cannot:

- run an arbitrary shell command;
- obtain command arguments from a model;
- execute a ModelRig catalog command without verified OS isolation;
- create a genuine I0b result without running the physical probes;
- use GitHub as a generic URL or repository browser;
- push branches;
- create, update or merge pull requests;
- alter ModelRig runtime or feature switches;
- discover or persist credentials;
- provide the Windows Job Object, restricted-token or network boundary itself;
- perform semantic code review;
- release or activate any change.

## Run tests

```bash
cd devcontrol
python -m unittest discover -s tests -v
```

The same suite is executed by the existing `tests/workflow_test_coverage.py`
contract inside ModelRig's shared CI and release test gate.

## Validate a task

```bash
cd devcontrol
PYTHONPATH=src python -m kaliv_dev_control validate-task examples/task.json
```

The package remains dependency-free so its authority and evidence primitives can
be reviewed without bootstrapping an agent execution environment.
