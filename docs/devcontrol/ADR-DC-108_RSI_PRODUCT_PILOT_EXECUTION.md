# ADR-DC-108 — Execute the first product-pilot Tier-A task exactly once

## Decision

ADR-DC-108 is the first boundary in the product pilot that may actually launch a
process.

It consumes one live ADR-DC-107 execution plan and delegates execution to the
existing `run_single_verified_tier_a_command_with_receipt` path. No alternate
executor is introduced.

Immediately before launch, the Tier-A receipt orchestrator must capture its own
pre-execution Git snapshot and prove that its SHA-256 exactly matches the
ADR-DC-106 snapshot bound into ADR-DC-107. This closes the staged-patch
substitution gap between planning and process launch.

## One-shot consumption

Execution authority is consumed by the signed `execution_nonce_sha256`, not by
Python object identity.

Once one ADR-DC-107 plan with that nonce reaches the launch boundary, any second
plan carrying the same nonce is rejected before the Tier-A executor is called.
A failed/uncertain launch attempt remains spent; recovery requires a fresh
product-pilot authorization chain.

## Receipt

A completed launch produces one
`PilotExactTaskProductPilotExecutionReceipt` containing the complete canonical
Tier-A command receipt and exact bindings back to:

- ADR-DC-107 execution plan;
- ADR-DC-106 workspace snapshot;
- ADR-DC-105 executor capability;
- ADR-DC-104 execution admission;
- execution nonce;
- exact DevelopmentTask and `modelrig.version.check` command.

The receipt records whether the Tier-A command passed, whether the workspace
remained unchanged, whether an exact-base reset was required, and whether the
next verification/recovery boundary is required.

## Authority after execution

ADR-DC-108 never grants:

- local commit authority;
- remote write or push authority;
- PR mutation or merge authority;
- release/deploy authority; or
- production activation authority.

The execution nonce remains non-reusable.

Even a passing command requires the next verification boundary. A non-passing
receipt sets `recovery_required=true`.
