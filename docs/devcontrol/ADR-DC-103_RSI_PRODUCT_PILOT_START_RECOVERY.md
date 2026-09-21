# ADR-DC-103 — Product-pilot start recovery

## Decision

Recovery of ADR-DC-102 is write-free with respect to the start transaction
itself. It never retries start, never backfills an ADR-DC-102 receipt and never
removes the transaction lock.

The recovery boundary reads the canonical host-controlled ADR-DC-097
authorization ledger and ADR-DC-102 transaction ledger, observes them twice
around a separate create-once recovery lock, and emits one recovery receipt.

## Recovery states

### `completed_verified`

The exact canonical ADR-DC-102 lock and final receipt both exist and agree with
the durable ADR-DC-097 authorization.

The recovery receipt may state `product_pilot_started=true` as recovered
historical state, while keeping current start authorization and task-execution
authority false. The next execution-authorization boundary may consume the
authenticated recovery receipt.

### `reserved_not_started`

The exact canonical ADR-DC-102 lock exists, the durable ADR-DC-097
authorization matches it, but no ADR-DC-102 final receipt exists.

Because ADR-DC-102 performs no product/task side effect before final receipt
publication, this state is classified as **not started**. Recovery sets
`manual_intervention_required=true`, leaves the original lock untouched and
does not permit execution. A fresh authority path is required for any later
start attempt.

## Authority

Recovery never grants reusable start authority, task execution, local commit,
remote write, push, PR, merge, release, deploy, production activation or nonce
reuse.
