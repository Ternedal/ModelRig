# Agent 4 A4-15/A4-21 — Production bootstrap for dormant operator reads

## Scope

A4-15 makes the already-landed Agent 4 operator read surface startable through
the normal worker entrypoint. A4-21 hardens that composition so production read
mode never constructs a mutation-capable lifecycle scheduler in the first
place. Neither slice activates Agent 4 orchestration.

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
adapter for read mode. It delegates to
`worker/app/agent4/operator_read_context.py`, which composes only:

- the canonical campaign repository behind a read-only campaign facade;
- a verified timeline read facade and timeline query service;
- a verified evidence-record read facade and evidence query service;
- the existing campaign and evidence operator services.

The read context deliberately does **not** construct or retain:

- `ResourceAwareCampaignHandoffSchedulerService`;
- campaign queue or resource-lease manager;
- checkpoint, retry, failure or health mutation services;
- projection reconciliation;
- handoff executor, dispatch or signal authority;
- delivery cursors or other lifecycle-oriented runtime services.

The narrow context and the full A4-09 runtime share the same canonical-root
ownership registry. A production read context therefore excludes a second full
writer context for the same root in-process, and a full writer context excludes
a later production read context.

`worker/app/entrypoint.py` remains the only production mount caller.

## Read-only authority boundary

The operator services historically type their campaign dependency as
`CampaignSchedulerService`, while their implementation uses only `get()` and
`list()`. A4-21 supplies `ReadOnlyCampaignSchedulerFacade`, which retains only
the repository needed for those reads. It does not initialize the superclass'
executor, queue, events, clock or projection collaborators.

Every public lifecycle method fails immediately with `CampaignValidationError`:

- recovery;
- submit and dispatch;
- pause and paused transition;
- resume;
- cancel and cancelled transition;
- completion.

Timeline and evidence stores are likewise exposed through facades whose append
methods fail before touching the underlying canonical stores.

This is materially stronger than the original A4-15 design. The superseded
design constructed the full runtime with a synthetic `operator-read` resource
and relied on a rejecting handoff executor. An in-process caller could therefore
reach scheduler persistence before the executor rejection. A4-21 removes that
admission path entirely instead of trying to stop it after lifecycle mutation.

## Filesystem behavior

Composition validates paths and wires read objects only. It does not create the
configured root or any child directory. Mutation attempts through the public
production read context fail before persistence, resource acquisition or
handoff creation. Existing operator reads decide how an empty/nonexistent store
is represented when a request is made; startup itself performs no persistence.

## Network and API boundary

A4-15/A4-21 change no network binding and create no new listener. The operator
API remains:

- worker-hosted;
- GET-only;
- default-off;
- backend-proxied;
- protected by paired-device Bearer plus `agent4:read`;
- free of submit, dispatch, signal, recovery or grant administration routes.

## Activation statement

A4-15/A4-21 do not authorize unattended orchestration, Agent 3 dispatch,
lifecycle writes or operator mutations. `production_activation` remains
`false`.

## Validation

`tests/worker_agent4_production_bootstrap.py` continues to cover:

- inert flag-off behavior;
- required absolute dataroot;
- side-effect-free composition;
- canonical service sharing;
- second-context rejection;
- entrypoint ordering;
- absence of recovery and background-runtime calls.

`tests/worker_agent4_production_read_mutation_boundary.py` adds adversarial A4-21
coverage proving:

- production composition returns the narrow read context, not the full runtime;
- mutation-oriented runtime services are absent from the context;
- scheduler lifecycle methods fail before any filesystem change;
- timeline/evidence append attempts fail before any filesystem change;
- recovery/reconciliation is unavailable;
- the synthetic resource-admission workaround is absent from production
  bootstrap source;
- the canonical-root owner guard is shared with the full runtime.

Existing A4-14 worker and backend tests continue to cover route inventory,
GET-only behavior, grant enforcement and proxy byte preservation.
