# ADR-DC-105 — Product-pilot executor capability on existing Tier-A substrate

## Decision

The product pilot does not get a second executor.

ADR-DC-105 consumes one live ADR-DC-104 execution admission and uses the same
non-executing Tier-A substrate verification as legacy ADR-DC-036:

- the reviewed one-command catalog;
- exact Toolchain;
- Windows physical-isolation verification and lease;
- signed runtime closure;
- trusted runtime root;
- staged Trusted Git runtime;
- canonical workspace identity; and
- Tier-A control-plane/toolhost identity.

The common verification was extracted into one internal helper. Legacy ADR-DC-036
still constructs its existing receipt and retains its existing authority model.
ADR-DC-105 constructs a product-pilot-specific receipt only after the identical
substrate verifier passes.

## First pilot command

The first product pilot is deliberately pinned to the existing reviewed
`modelrig.version.check` command and its one-file runtime closure. No second
catalog entry or model-defined command is introduced.

## Authority

A positive ADR-DC-105 receipt means the reviewed executor substrate is live and
may proceed to a separate exact workspace-snapshot plan boundary.

It may set:

- `execution_plan_materialization_authorized=true`

It still keeps:

- `execution_plan_materialized=false`;
- `task_execution_authorized=false`;
- task started/completed false;
- local commit false;
- all remote/GitHub/release/deploy/production mutation authority false; and
- nonce reuse false.

The next boundary must perform another fresh substrate revalidation and freeze
the exact GitWorkspaceSnapshot before a plan can exist.
