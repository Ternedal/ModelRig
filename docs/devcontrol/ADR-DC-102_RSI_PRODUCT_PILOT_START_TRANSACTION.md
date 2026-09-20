# ADR-DC-102 — One-shot product-pilot start transaction

## Decision

One live authenticated ADR-DC-097 product-pilot start authorization may be
consumed exactly once into a separate host-admin-controlled start-transaction
ledger.

The transaction writes a durable lock first, revalidates the same live
authorization after that lock, checks that the ADR-DC-097 expiry window is still
open, and only then publishes the immutable start receipt.

## What "started" means

A successful receipt may set:

- `product_pilot_start_authorized=true`;
- `product_pilot_started=true`;
- `one_shot_start_consumed=true`;
- `start_receipt_issued=true`; and
- `next_boundary_execution_authorization_required=true`.

This starts the bounded pilot session only. It does **not** execute the selected
DevelopmentTask and does not authorize local commits.

The receipt preserves the exact ADR-DC-096-v2/098/099/100 lineage, fresh human
GO, host DevelopmentTask registry, DevelopmentTask/fixed-command identity and
post-production candidate through the authenticated ADR-DC-097 live receipt.

## Fail-closed behavior

The transaction performs no subprocess or network operation and grants no
remote-write, push, PR, merge, release, deploy or production-activation
authority.

A duplicate start fails. A serialized ADR-DC-097 receipt is not sufficient live
authority. An expired authorization fails before reservation.

If the process crashes or the authorization expires after the durable lock but
before receipt publication, the lock remains and future starts fail closed.
Recovery from such a lock is intentionally a separate boundary.
