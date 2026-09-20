# ADR-DC-106 — Product-pilot clean workspace execution plan

## Decision

A started product pilot may materialize an execution plan only from one **live**
ADR-DC-105 executor capability.

The boundary reuses the exact reviewed Tier-A substrate retained by ADR-DC-105,
forces a fresh substrate revalidation, and then captures a fresh
`GitWorkspaceSnapshot` through the staged Trusted-Git runtime.

The snapshot is admissible only when:

- `HEAD` equals the exact ADR-DC-035 DevelopmentTask `base_sha`;
- the staged patch is empty;
- the unstaged patch is empty;
- there are no untracked paths; and
- Trusted-Git runtime evidence is identical before and after capture.

The plan binds that snapshot hash to the exact DevelopmentTask, the existing
`modelrig.version.check` command specification, catalog/toolchain, physical
lease, signed runtime closure, execution nonce, process limits, and task budget.

## Authority

A live ADR-DC-106 plan may set:

- `execution_plan_materialized=true`;
- `task_execution_authorized=true`; and
- `one_shot_execution_required=true`.

That authority is process-local. A serialized/reloaded plan is evidence only and
cannot start the task.

The plan still keeps:

- task started/completed false;
- local commit false;
- every remote/GitHub/release/deploy/production mutation authority false; and
- `nonce_reusable=false`.

The next boundary must revalidate both the Tier-A substrate and the exact frozen
workspace snapshot immediately before launching the single reviewed command.

## Non-actions

ADR-DC-106 does not stage a runtime closure, run the product command, reset or
clean the workspace, perform network I/O, write durable state, or publish
anything.
