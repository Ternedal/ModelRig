# ADR-DC-101 — Product-pilot start-readiness authority closure

## Problem

The original ADR-DC-096 readiness receipt could become
`product_pilot_start_ready=true` from fresh post-production activation state
alone. The separately restored start-requirements manifest correctly required a
fresh human GO, exact task registry, runtime-preflight revalidation and the
remaining fail-closed controls, but the positive readiness boundary did not
consume those proofs.

That made ADR-DC-097 structurally capable of authorizing a start from evidence
that was fresh but incomplete.

## Decision

The readiness receipt is upgraded to schema v2. A positive readiness now
requires one coherent live chain:

1. fresh authenticated ADR-DC-095 post-production activation;
2. the exact ADR-DC-096 requirements manifest rebuilt from that live source;
3. live ADR-DC-098 lineage provenance;
4. live ADR-DC-099 fresh-human-GO / host DevelopmentTask-registry binding; and
5. live authenticated ADR-DC-100 fresh runtime-preflight revalidation.

The ADR-095 object carried by ADR-098 must be the same live object supplied to
readiness. The ADR-099 object carried by ADR-100 must likewise be the same live
object supplied to readiness. Matching serialized hashes alone are insufficient.

## Freshness

At readiness evaluation, each of these must be no more than 60 seconds old:

- the post-production observation;
- verification of the fresh human GO; and
- verification of the fresh runtime preflight.

## Meaning of positive readiness

`product_pilot_start_ready=true` means only:

> the complete pre-authorization evidence is fresh and coherent, so ADR-DC-097
> may be asked for its separate dual-authorized, durable one-shot start
> authorization.

It does not mean the pilot has started.

The receipt therefore keeps `product_pilot_start_authorized=false`,
`product_pilot_started=false`, task-execution authority false, every
Git/GitHub/release/deploy/production mutation authority false, and
`nonce_reusable=false`.

It also retains these still-unfulfilled downstream requirements as true
requirements: one-shot start authorization, host-local replay guard and final
start receipt.

## Compatibility

The Python receipt type remains
`PilotExactTaskProductPilotStartReadinessReceipt` so ADR-DC-097 retains its
narrow API boundary. The receipt schema changes from v1 to v2; v1 audit
artifacts are not accepted as live readiness authority.

ADR-DC-097's signed start intent already includes the readiness receipt SHA-256,
so the stronger v2 evidence is transitively bound into every new start
authorization without widening ADR-DC-097 authority.
