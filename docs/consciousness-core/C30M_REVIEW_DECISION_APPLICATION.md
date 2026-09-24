# C30-M — Exact trusted review decision application

Status: draft, stacked on C30-L, `production_activation=false`.

C30-M binds one C30-L one-shot consume receipt to one explicit C30-I trusted
semantic review.

For APPROVE it additionally requires one real C7 `ExperienceCandidate`.
For REJECT no candidate is accepted.

## Exact consume binding

The decision applier requires:

- the consumed C30-J request;
- the C30-L consume receipt;
- an explicit C30-I `TrustedEpisodeExperienceReview`;
- optionally one real C7 candidate for APPROVE.

Before semantic evaluation it verifies that request id, canonical request ref
and closure-evidence ref all match exactly.

A receipt from another request cannot authorize a review decision.

## Decision semantics

### REJECT

REJECT must carry no candidate.

C30-I returns a negative evaluation with no C7 handoff.

### APPROVE

APPROVE requires one real candidate already carrying real cognitive-cycle
provenance.

C30-M delegates candidate validation to C30-I. The resulting C7 handoff must
still be `trusted_review_required`; C30-M does not grant automatic completed-
turn or durable-memory authority.

## Exact-once decision ledger

`TrustedEpisodeReviewDecisionApplier` maintains a bounded process-local replay
ledger of canonical request refs.

A successfully applied request cannot be applied a second time in the same
applier lifecycle.

Failed binding or semantic validation does not enter the replay ledger, so a
caller may correct the invalid input without losing the consumed review request.

The ledger is capped at 4096 refs and fails closed when full.

## Lifecycle

`close()` clears the replay ledger and permanently closes the applier.

No applied decision becomes durable merely by entering this ledger.

## Authority boundary

C30-M adds no:

- model call;
- Memory 4 service call or durable write;
- completed-turn authority;
- public route/authentication authority;
- persistent storage;
- background task/retry;
- scheduler/timer;
- Agent 3/tool execution;
- production activation.

## Qualification

Focused tests prove APPROVE and REJECT paths, C7 review-required preservation,
exact consume binding, replay rejection, failed-validation non-burning
semantics, rejection of a candidate on REJECT and lifecycle clearing.

## Next slice

C30-N may compose C30-L consume plus C30-M decision application into one
trusted backend service boundary with explicit claim/abandon semantics so an
operator crash between consume and decision cannot silently lose a pending
review.
