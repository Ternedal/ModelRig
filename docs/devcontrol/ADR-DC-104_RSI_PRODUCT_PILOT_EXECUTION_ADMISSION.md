# ADR-DC-104 — Product-pilot execution admission

## Decision

A completed product-pilot start does not directly grant task execution.

ADR-DC-104 admits exactly one completed started session to the existing Tier-A
executor-capability path. The source must be either:

- a live authenticated ADR-DC-102 final start receipt; or
- a live authenticated ADR-DC-103 `completed_verified` recovery receipt.

Lock-only ADR-DC-103 recovery is never execution-admissible.

## Host registry revalidation

Admission re-reads the canonical host-admin-controlled ADR-DC-035
DevelopmentTask registry.

The registry digest must be unchanged from product-pilot start. The exact
selected pilot task must still resolve to the same DevelopmentTask digest and
the same single fixed command. Any registry/task drift fails closed.

This deliberately reuses the existing DevelopmentTask authority instead of
creating a parallel product executor registry.

## Freshness

A live ADR-DC-102 receipt must be admitted within 60 seconds of
`started_at_utc`.

After restart, a completed ADR-DC-103 recovery may be admitted within 60 seconds
of the fresh recovery classification. The historical ADR-DC-102 receipt remains
the exact start identity, but the recovery operation becomes the fresh host
observation.

## Authority

A positive receipt authorizes only:

- `executor_capability_materialization_authorized=true`

It explicitly keeps:

- execution-plan materialization false;
- task execution false;
- local commit false;
- all remote/GitHub/release/deploy/production mutation authority false; and
- nonce reuse false.

The next boundary must bridge this admission into the existing ADR-DC-036
Tier-A substrate with fresh runtime and workspace revalidation.
