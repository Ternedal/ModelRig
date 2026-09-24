# C30-Q — Privacy-safe episode review status

Status: draft, stacked on C30-P, read-only.

C30-Q adds a bounded operator/diagnostic projection for the C30 review runtime.

The projection contains lifecycle state and counts only. It never exposes review
request ids/refs, claim ids, closure evidence, user text or model
chain-of-thought.

## States

The status state is one of:

- OFF
- TRANSPORT_ONLY
- RUNTIME_UNAVAILABLE
- ACTIVE_IDLE
- ACTIVE_PENDING
- ACTIVE_CLAIMED
- MAILBOX_FULL
- CLOSED

TRANSPORT_ONLY explicitly identifies the safe configuration where the C30-O
route flag is on while the C30-P runtime flag is off.

RUNTIME_UNAVAILABLE covers runtime opt-in without a valid complete runtime
binding in app state.

## Counts

When a valid runtime is present the snapshot may expose:

- mailbox capacity;
- pending request count;
- claimed request count;
- mailbox-full boolean;
- runtime/mailbox closed state;
- latest C30-K publication status when an active C19 session has one.

No request-level identifiers are included.

## Private status route

C30-O now includes:

GET /experimental/consciousness/episode-review/status

The route is loopback-only but does not require a live review service. This
allows operators to distinguish transport-only or unavailable runtime states
instead of receiving only a generic 503.

## Privacy contract

Every snapshot fixes:

request_refs_included=false
claim_ids_included=false
closure_evidence_included=false
raw_text_included=false
raw_chain_of_thought_included=false
memory4_called=false
model_calls=0
production_activation=false

## Binding validation

A runtime is considered active only when the app-state runtime, mailbox and
claim service are all present and the runtime owns those exact instances.

Partial or inconsistent app-state bindings report RUNTIME_UNAVAILABLE.

## Qualification

Focused tests cover off/transport-only/unavailable states, idle/pending/claimed
runtime states, mailbox-full priority, closed lifecycle state, exact-instance
binding validation, privacy exclusion of request/claim references, service-less
status reporting and loopback-only HTTP access.

## Next slice

C30-R may add operator-side review observability counters for publication,
claim, abandon, approve and reject outcomes without storing per-request audit
content or creating a durable review log.
