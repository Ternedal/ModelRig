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
- a shared-CI bridge that makes all `devcontrol/tests` mandatory in PR and release gates.

### Slice 3 — campaign integrity and structural review

- immutable campaign state with legal transition rules;
- a SHA-256 hash chain over every state transition and evidence reference;
- terminal failed and cancelled states that cannot silently resume;
- review requests bound to the task, staged patch and command receipts;
- a reviewer actor that must differ from the developer actor;
- a structural reviewer that refuses missing or failed command evidence;
- a gate that can only declare `ready_for_draft_pr`;
- merge authority remains structurally and operationally human.

The reviewer in this slice checks evidence consistency and separation of roles. It
does **not** claim to understand whether the implementation is semantically good.
A later semantic reviewer must remain separate from the developer execution and
must not be allowed to rewrite the task, tests or protected evaluation policy.

## Command authority

The default command registry is intentionally empty. A task may name command IDs,
but nothing executes until separately reviewed code injects an exact
`CommandTemplate`. Models and task payloads cannot supply executables, arguments,
working directories or environment variables.

In task schema v1, every command ID granted to a task is also required evidence
for draft-PR readiness. Optional commands are deliberately deferred to a future
schema version instead of being introduced through an ambiguous in-place change.

This control plane proves Git/worktree and policy isolation with fixture
repositories. It is **not** proof of an operating-system security boundary.
Running modified project code on the production rig remains blocked until Windows
isolation I0b has been physically validated.

## Explicit non-goals

The current control plane cannot:

- run an arbitrary shell command;
- obtain command arguments from a model;
- push branches;
- create, update or merge pull requests;
- alter ModelRig runtime or feature switches;
- access production data or credentials;
- provide proven process, account or network isolation;
- perform semantic code review;
- release or activate any change.

## Run tests

```bash
cd devcontrol
python -m unittest discover -s tests -v
```

The same suite is also run by `tests/workflow_devcontrol.py` inside ModelRig's
shared CI and release test gate.

## Validate a task

```bash
cd devcontrol
PYTHONPATH=src python -m kaliv_dev_control validate-task examples/task.json
```

The package remains dependency-free so its authority and evidence primitives can
be reviewed without bootstrapping an agent execution environment.
