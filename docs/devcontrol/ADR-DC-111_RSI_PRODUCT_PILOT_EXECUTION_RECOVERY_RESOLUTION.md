# ADR-DC-111 — Resolve interrupted execution without reopening launch authority

## Decision

ADR-DC-111 consumes exactly one **live authenticated** ADR-DC-110 recovery
receipt and produces a fail-closed recovery disposition.

It does not read or write Git, launch a process, modify the ADR-DC-108 ledger,
promote a pending receipt, remove a lock, retry execution, or authorize a new
execution nonce.

The source ADR-DC-110 receipt must still be bound to the same live durable
ledger state. Serialization/reload of ADR-DC-110 is audit evidence only and
cannot enter ADR-DC-111.

## Resolution classes

`completed_verified` becomes:

`completed_ready_for_post_restart_verification`

This means an exact final ADR-DC-108 receipt exists and the recovery can move to
a **later fresh post-restart verification boundary**. ADR-DC-111 does not itself
declare the product-pilot task closed after restart.

For `receipt_publication_uncertain`, the resolution is:

`pending_receipt_manual_resolution_required`

For `consumed_uncertain`, the resolution is:

`consumed_uncertain_manual_resolution_required`

Those two states do not advance automatically. They remain manual intervention
cases because the execution nonce was consumed before process launch and the
available durable evidence cannot prove a unique safe completion state.

## No retry

Every disposition keeps:

- `execution_nonce_consumed=true`;
- `retry_authorized=false`;
- `task_execution_authorized=false`;
- `nonce_reusable=false`; and
- all commit, remote, PR, merge, release, deploy and production authority false.

ADR-DC-111 never converts recovery into a second launch.

## Live resolution provenance

Only the receipt returned by the live ADR-DC-111 call receives process-local
`resolution_authenticated` provenance. It remains bound to the original live
ADR-DC-110 receipt and therefore loses authentication if the canonical durable
execution ledger changes underneath that recovery evidence.

Serialization/reload preserves audit evidence only.

## Next boundary

Only `completed_ready_for_post_restart_verification` may enter the next
post-restart verification boundary. That later boundary must independently
re-establish current Trusted-Git/workspace evidence before it can claim the
recovered product-pilot execution is closed.

Pending or lock-only recovery remains a manual-resolution path.
