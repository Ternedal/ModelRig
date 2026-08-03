# Kaliv Development Control Plane

This directory is the isolated foundation for controlled self-development.
It is deliberately **not** wired into ModelRig runtime, Agent 3, Agent 4,
release, merge, or production activation.

## First milestone

The initial slice provides:

- an immutable `kaliv-development-task/v1` contract;
- exact-SHA and budget validation;
- normalized allow/protect path policy;
- fail-closed change-scope evaluation;
- deterministic evidence receipts;
- an ephemeral detached-worktree controller with no shell execution;
- a small CLI and standard-library test suite.

## Explicit non-goals

This slice cannot:

- edit files;
- run arbitrary commands;
- push branches;
- create or merge pull requests;
- alter ModelRig runtime or feature switches;
- access production data or credentials.

## Run tests

```bash
cd devcontrol
python -m unittest discover -s tests -v
```

## Validate a task

```bash
cd devcontrol
PYTHONPATH=src python -m kaliv_dev_control validate-task examples/task.json
```

The package is intentionally dependency-free so the policy core can be
reviewed and tested without bootstrapping an execution environment.
