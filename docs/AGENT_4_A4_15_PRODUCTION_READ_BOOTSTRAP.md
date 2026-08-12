# Agent 4 A4-15/A4-21 — Production bootstrap for dormant operator reads

## Scope

A4-15 makes the already-landed Agent 4 operator read surface startable through
the normal worker entrypoint. A4-21 hardens that composition so production read
mode never constructs or exposes a mutation-capable lifecycle scheduler. Neither
slice activates Agent 4 orchestration.

The production entrypoint imports Agent 4 only when:

```text
KALIV_AGENT4_OPERATOR_API=1
```

Exact opt-in additionally requires an absolute canonical dataroot:

```text
KALIV_AGENT4_DATA_ROOT=<absolute path>
```

Missing, relative or file-valued roots fail startup before the worker is ready.

## ADR-A4-005 traceability

**Implemented ADR:** ADR-A4-007. A4-21 preserves the established worker-hosted,
backend-proxied and paired-device read boundary while removing mutation-capable
lifecycle authority from the production read composition.

**Reference architecture:** ADR-A4-005 / Agent 4 B-reference architecture plus
the A4-09 canonical composition and single-dataroot ownership model. The
canonical campaign/timeline/evidence stores remain the source of truth; only the
authority of the production adapter is narrowed.

**Dependencies:** ADR-A4-005 documentation/stop rule, ADR-A4-006 ownership
boundary, ADR-A4-007 host/transport/auth boundary, the A4-09 canonical runtime,
#422/A4-15 at exact base `275bc509bc1cc6e6f06eb03d053f077ae63d5a94`,
and issue #443. Downstream integration preserves #428/A4-19 snapshot-bound
campaign paging and #442/A4-20 stale-response invalidation.

## Ownership

`worker/app/agent4/production_bootstrap.py` is the single production composition
adapter for read mode. It delegates to
`worker/app/agent4/operator_read_context.py`, which composes only:

- the canonical campaign repository behind a two-method campaign reader;
- a verified timeline read facade and timeline query service;
- a verified evidence-record read facade and evidence query service;
- the existing campaign and evidence operator services.

The read context deliberately does **not** construct or retain:

- `CampaignSchedulerService` or `ResourceAwareCampaignHandoffSchedulerService`;
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

## Structural campaign-read contract

A4-21 changes the operator layer itself from a concrete scheduler dependency to
`Agent4CampaignReadSource`, a runtime-checkable structural protocol containing
only:

```text
get(campaign_id)
list()
```

The full canonical scheduler satisfies that protocol for existing dormant/test
compositions, so no parallel domain model is introduced. Production read mode
instead supplies `ReadOnlyCampaignReader`, which does **not** inherit the
scheduler and therefore has no submit, dispatch, pause, resume, cancel,
completion, recovery, queue, resource or handoff entrypoint to call.

This also makes the boundary forward-safe: adding a future public lifecycle
method to `CampaignSchedulerService` cannot silently add authority to the
production reader through inheritance.

Timeline and evidence stores must still satisfy their existing structural store
protocols, so their public `append` members are explicit rejecting facades. Each
raises `CampaignValidationError` before touching the underlying canonical store.

## Why A4-21 is required

The superseded A4-15 composition constructed the full runtime with a synthetic
`operator-read` capacity and relied on a rejecting handoff executor. An
in-process caller could therefore execute scheduler admission and persistence
before the executor rejected the external handoff.

A4-21 removes that admission path entirely. The production composition has no
scheduler object, queue, lease manager or handoff executor, rather than trying
to make those mutation-capable components safe after construction.

## Filesystem behavior

Composition validates paths and wires read objects only. It does not create the
configured root or any child directory. Campaign reads over an empty root and
all rejected timeline/evidence append attempts leave the dataroot byte-identical.
Startup itself performs no persistence.

## Network and API boundary

A4-15/A4-21 change no network binding and create no new listener. The operator
API remains:

- worker-hosted;
- GET-only;
- default-off;
- backend-proxied;
- protected by paired-device Bearer plus `agent4:read`;
- free of submit, dispatch, signal, recovery or grant administration routes.

## Qualification lineage

The standalone A4-21 slice is qualified at
`15ebbf2dbdedc3f6b35a14f050f507063df767c9` with CI #3560,
agent3-diagnostics #1697 and agent3-full-diagnostics #2779.

The A4-19/A4-20-preserving integration candidate was qualified before merge at
`1b11e95340c689fc566ae2bae3d3b73697896d28` with CI #3562,
agent3-diagnostics #1699 and agent3-full-diagnostics #2781, including focused
A4-21, campaign-list query/API, snapshot paging and full read-product contracts.

The validation-only merge to `agent/a4-read-product-integration` created
`6e57a6854a818b56f3e47a48272bdc8d83be277a`. Its first full diagnostic run
proved the code path but exposed stale ADR metadata on long-lived PR #426. The
PR metadata and this traceability section were then updated; only a subsequent
clean exact head may authorize downstream physical-candidate refresh.

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
- the campaign reader is not a scheduler and exposes no lifecycle method;
- mutation-oriented runtime services are absent from the context;
- campaign reads leave an existing dataroot byte-identical;
- timeline/evidence append attempts fail before any filesystem change;
- the synthetic resource-admission workaround is absent from production
  bootstrap source;
- the narrow context constructs no scheduler or resource manager;
- the canonical-root owner guard is shared with the full runtime.

Existing A4-14 worker and backend tests continue to cover route inventory,
GET-only behavior, grant enforcement and proxy byte preservation.
