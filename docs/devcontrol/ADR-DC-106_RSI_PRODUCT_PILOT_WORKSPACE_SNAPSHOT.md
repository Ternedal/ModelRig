# ADR-DC-106 — Freeze the exact product-pilot Git workspace before planning

## Decision

The first product-pilot execution plan may not be materialized directly from the
ADR-DC-105 executor capability.

ADR-DC-106 consumes one live ADR-DC-105 capability, forces that capability to
revalidate the reviewed Tier-A substrate again, then captures one canonical
`GitWorkspaceSnapshot` through the existing trusted Git runtime.

The snapshot must prove:

- `HEAD` equals the exact DevelopmentTask base SHA;
- unstaged patch bytes are zero;
- untracked path count is zero; and
- the snapshot remains bound to the same live capability, catalog, toolchain,
  physical lease, signed runtime closure, trusted Git runtime, workspace
  authority, toolhost and source environment.

A staged patch is represented and hashed by the existing canonical snapshot
format; ADR-DC-106 does not alter or apply it.

## Read-only Git boundary

The implementation reuses the existing `_GitWorkspaceEvidence.snapshot()`
path. That path issues only bounded trusted Git evidence reads. ADR-DC-106 does
not call reset, clean, checkout, add, commit, merge, rebase, push, fetch, pull or
any Tier-A task executor.

The receipt is process-local authenticated evidence. Deserializing it never
restores live authority. If the workspace changes after capture, a fresh
snapshot no longer matches and the receipt loses live authentication.

## Authority

A positive ADR-DC-106 receipt means only that a fresh exact workspace snapshot
exists and may be consumed by a separate execution-plan materialization boundary.

It may set:

- `workspace_snapshot_materialized=true`;
- `execution_plan_materialization_authorized=true`.

It still keeps:

- `execution_plan_materialized=false`;
- `task_execution_authorized=false`;
- task started/completed false;
- local commit false;
- all remote/GitHub/release/deploy/production mutation authority false; and
- nonce reuse false.

The next boundary must bind an execution plan to this exact snapshot and must
not silently refresh or replace it.
