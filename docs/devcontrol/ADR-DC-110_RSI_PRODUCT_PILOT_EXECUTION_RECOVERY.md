# ADR-DC-110 — Classify interrupted product-pilot execution without retry

## Decision

ADR-DC-110 is the read-only recovery boundary for durable ADR-DC-108 execution
state.

It accepts only an execution nonce and observes the canonical host-controlled
ADR-DC-108 ledger twice. It never launches the Tier-A command, never changes
Git, never promotes a pending receipt, and never removes or rewrites a lock.

The durable state is classified as exactly one of:

- `completed_verified`: the exact lock and exact final ADR-DC-108 receipt exist;
- `receipt_publication_uncertain`: the lock and an exact pending ADR-DC-108
  receipt exist, but final publication is absent;
- `consumed_uncertain`: the execution lock exists with no final or pending
  receipt.

A final and pending receipt coexisting is rejected for manual inspection rather
than normalized automatically.

## No retry authority

All three classifications keep the signed execution nonce spent:

- `execution_nonce_consumed=true`
- `retry_authorized=false`
- `task_execution_authorized=false`
- `nonce_reusable=false`

This is intentional. A lock is written before ADR-DC-108 launches the process,
so lock-only state cannot prove whether launch occurred. Retrying could execute
the reviewed command twice.

## Race and tamper handling

ADR-DC-110 parses the exact canonical lock and, when present, the complete
ADR-DC-108 receipt. Receipt identity must match the lock, ledger root, execution
plan, snapshot, capability, admission, task and fixed command.

The state is observed twice. Any change between observations fails closed.

## Authority

The recovery receipt is classification evidence only. It grants no Git,
commit, remote, PR, merge, release, deploy or production authority. Every
classification requires an explicit later recovery-resolution/manual decision.
