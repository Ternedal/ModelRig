# ADR-DC-099 — Fresh-GO exact product-pilot task registry

## Decision

ModelRig may derive one **inert task-registry receipt** only when a live
ADR-DC-098 lineage attestation and a freshly host-verified human pilot GO agree
on the exact DC-L16 scope.

The receipt narrows authority to exactly one task: the task already selected by
the verified lineage and present in the fresh human allowlist. It does **not**
create a second registry. Instead it verifies that the existing canonical
ADR-DC-035 host-admin-controlled DevelopmentTask registry contains that exact
pilot-task mapping and records the resulting DevelopmentTask/fixed-command
identity.

## Required binding

The boundary rechecks repository, campaign/task identity, base/requested-main
identity, operator surface, workspace, local-commit scope, historical
human-selection/preflight lineage, the selected task and the existing ADR-DC-035
host registry's DevelopmentTask/base/fixed-command mapping. The fresh GO must be
issued after the live post-production lineage attestation and verified no more
than 60 seconds before registry evaluation.

## Authority

A positive receipt may state `task_registry_ready=true` only after the existing
host-controlled ADR-DC-035 registry has been verified and narrowed to this inert
single-task allowlist. It must keep all of the following false:

- executor wired;
- runtime preflight satisfied;
- product-pilot start ready/authorized/started;
- task execution authorized;
- local or remote mutation authority;
- push/PR/merge/release/deploy/production authority;
- nonce reuse.

Serialized/replayed registry receipts are not authenticated authority. The next
boundary must consume the live process-local provenance and independently
reverify current runtime preflight before any pilot-start readiness can become
true.
