# ADR-DC-107 — Bind product-pilot execution plan to the frozen workspace

## Decision

ADR-DC-107 materializes the first product-pilot execution plan only from one
**live ADR-DC-106 workspace-snapshot receipt**.

The plan must use the exact snapshot already frozen by ADR-DC-106. It may ask
ADR-DC-106 to revalidate that the current workspace still equals that snapshot,
but it may not capture, replace, refresh or substitute the snapshot itself.

The plan binds:

- the ADR-DC-106 receipt and exact `GitWorkspaceSnapshot` hash/content;
- the live ADR-DC-105 executor capability and ADR-DC-104 execution admission;
- the exact DevelopmentTask and `modelrig.version.check` command specification;
- repository and merge identity;
- catalog, toolchain and physical lease;
- signed runtime-closure and Trusted-Git identities;
- workspace/toolhost/source-environment identities; and
- reviewed task/runtime/output/process budgets.

A staged patch, if present, remains part of the exact ADR-DC-106 snapshot. The
plan neither applies nor rewrites it. Unstaged or untracked material remains
forbidden by ADR-DC-106.

## Authority

A live ADR-DC-107 plan may set:

- `execution_plan_materialized=true`;
- `task_execution_authorized=true`; and
- `one_shot_task_execution_required=true`.

This authority is process-local. Deserializing the plan produces durable
evidence only and never restores launch authority.

Before launch, the next boundary must revalidate both:

1. the reviewed Tier-A substrate; and
2. the exact ADR-DC-106 workspace snapshot.

Any workspace drift revokes live ADR-DC-107 authentication.

## Non-actions

ADR-DC-107 does not:

- invoke Git directly;
- create a second workspace snapshot;
- stage the runtime closure;
- run the Tier-A command;
- mutate the repository;
- commit or write remotely;
- mutate a PR; or
- release, deploy or activate production.

All mutation/publication authority remains false, and the execution nonce remains
non-reusable.

The next boundary is the one-shot Tier-A launch and command receipt for the
single reviewed `modelrig.version.check` task.
