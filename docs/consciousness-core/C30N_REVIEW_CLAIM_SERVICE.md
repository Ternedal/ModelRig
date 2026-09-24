# C30-N — Trusted review claim service

Status: draft, stacked on C30-M, production_activation=false.

C30-N closes the operator lifecycle gap between inspecting a review request and
applying the semantic decision.

The request is claimed without being consumed. It remains in the bounded C30-J
mailbox until an explicit review decision has passed semantic preflight.

## Claim

claim_exact(request_id, expected_request_ref) verifies the canonical request
ref and creates one process-local claim.

A claimed request:

- remains pending in the mailbox;
- cannot be claimed a second time through the same service;
- has no automatic expiry or timer;
- is not durable.

This means an operator/UI failure after claim does not silently remove the
pending review request.

## Abandon

abandon(claim_id, expected_request_ref) removes only the claim.

The original review request must still be pending and remains available for a
later claim.

## Commit decision

commit_decision requires the active claim plus an explicit C30-I trusted review
and, for APPROVE, a real C7 ExperienceCandidate.

The order is deliberate:

verify claim/request binding
  -> C30-I semantic preflight while request is still pending
  -> C30-L exact consume
  -> C30-M exact decision application
  -> remove claim

Invalid semantic input therefore fails before mailbox consume and leaves the
claimed request pending.

## Crash scope

C30-N removes the normal operator gap where a request was consumed before the
review decision was ready.

It does not claim durable exactly-once recovery from process failure during the
final synchronous consume/apply commit section. Achieving that would require a
durable transactional/outbox authority, which this slice intentionally does not
create.

## Lifecycle

Claims are bounded to 32 active requests.

Service close clears only claim state and closes its process-local decision
applier. It does not consume or close the underlying mailbox, because mailbox
lifecycle remains owned by C19/C30-K.

## Authority boundary

C30-N adds no HTTP/API route, persistent claim store, automatic timeout/expiry,
timer/scheduler, background worker/retry, model call, Memory 4 write,
automatic C7 persistence, Agent 3/tool execution, or production activation.

## Qualification

Focused tests prove claim-without-consume, abandon/reclaim, semantic failure
before consume, APPROVE and REJECT commit ordering, duplicate-claim refusal,
exact-ref abandonment, lifecycle ownership and absence of timers/durable
recovery.

## Next slice

C30-O may define a private, independently default-off transport boundary for
listing, claiming, abandoning and committing review decisions by reusing
existing loopback/authenticated worker patterns rather than creating new auth
authority.
