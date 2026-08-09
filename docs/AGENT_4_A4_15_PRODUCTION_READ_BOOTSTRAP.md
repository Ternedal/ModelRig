# Agent 4 A4-15 — Production bootstrap for dormant operator reads

## Scope

A4-15 makes the already-landed Agent 4 operator read surface startable through
the normal worker entrypoint. It does **not** activate Agent 4 orchestration.

The production entrypoint imports Agent 4 only when:

```text
KALIV_AGENT4_OPERATOR_API=1
```

Exact opt-in additionally requires an absolute canonical dataroot:

```text
KALIV_AGENT4_DATA_ROOT=<absolute path>
```

Missing, relative or file-valued roots fail startup before the worker is ready.

## Ownership

`worker/app/agent4/production_bootstrap.py` is the single production composition
adapter for read mode. It:

- composes the canonical A4-09 `Agent4RuntimeContext`;
- uses the same campaign, timeline and evidence stores as the operator services;
- injects that context into `mount_agent4_operator`;
- creates no parallel reader or store model;
- preserves the one-context-per-canonical-root guard.

`worker/app/entrypoint.py` remains the only production mount caller.

## Read-only handoff boundary

The context contains `ReadOnlyAgent4HandoffExecutor`. Every dispatch, lifecycle
signal and outcome lookup raises `CampaignValidationError`. This gives the
canonical scheduler graph the executor shape it requires without granting any
external execution authority.

The bootstrap does not call:

- submit or dispatch;
- pause, resume, cancel or signal;
- recovery or projection reconciliation;
- Agent 3;
- threads, timers, polling or background tasks.

## Filesystem behavior

Composition validates paths and wires store objects only. It does not create the
configured root or any child directory. Existing read services decide how an
empty/nonexistent store is represented when a request is made; startup itself
performs no persistence.

## Network and API boundary

A4-15 changes no network binding and creates no new listener. The operator API
remains:

- worker-hosted;
- GET-only;
- default-off;
- backend-proxied;
- protected by paired-device Bearer plus `agent4:read`;
- unavailable directly from Android until the separate Kaliv client slice.

## Activation statement

A4-15 does not authorize unattended orchestration, Agent 3 dispatch, lifecycle
writes or operator mutations. `production_activation` remains `false`.

## Validation

`tests/worker_agent4_production_bootstrap.py` covers:

- inert flag-off behavior;
- required absolute dataroot;
- side-effect-free composition;
- canonical service sharing;
- second-context rejection;
- fail-closed executor operations;
- entrypoint ordering;
- absence of recovery and background-runtime calls.

Existing A4-14 worker and backend tests continue to cover route inventory,
GET-only behavior, grant enforcement and proxy byte preservation.
