# C30-L — Trusted in-process review adapter

Status: draft, stacked on C30-K, `production_activation=false`.

C30-L gives a trusted backend/UI integration point a bounded way to inspect and
consume pending C30-J episode review requests.

It deliberately does **not** add an HTTP route, authentication policy, reviewer
decision engine, Memory 4 bridge or persistent queue.

## Bounded listing

`TrustedEpisodeReviewAdapter.list_pending(limit=8)` returns at most 32
reference-level items.

Each item contains only bounded C30-H/C30-I metadata:

- request and closure refs;
- closed episode ref;
- Self / Person Revision binding;
- open/close reason and sequence range;
- objective elapsed time;
- moment counts;
- salient source refs;
- participant refs;
- active-goal refs;
- maximum retained salience.

Raw user text and model chain-of-thought remain absent.

Listing is read-only and does not consume or mutate mailbox state.

## Exact one-shot consume

`consume_exact(request_id, expected_request_ref)` requires both the deterministic
request id and its canonical request ref.

The adapter locates the pending request, verifies the exact ref **before**
calling the mailbox consume primitive, and then consumes once.

A wrong id or wrong ref fails without removing the pending request.

The returned request remains bounded C30-J data. The consume receipt explicitly
states that no reviewer decision was applied and no C7 candidate was created.

## Why consume precedes review

C30-L separates transport/lifecycle authority from semantic review authority.

The trusted caller may take one bounded request out of the process-local
mailbox and then perform C30-I APPROVE/REJECT handling in a separately reviewed
step. This prevents a UI adapter from silently becoming a semantic reviewer.

## No route yet

C30-L is in-process only.

A future route requires a separate slice that reuses an existing trusted
authentication/loopback boundary. It must not invent a new auth authority merely
to expose episode review.

## Authority boundary

C30-L adds no:

- HTTP/API route;
- authentication authority;
- semantic reviewer authority;
- ExperienceCandidate creation;
- Memory 4 read/write;
- persistent storage;
- background task/retry;
- scheduler/timer;
- Agent 3/tool execution;
- production activation.

## Qualification

Focused tests prove bounded/truncated listing, read-only listing, exact one-shot
consume, non-consuming ref mismatch, wrong-id isolation, invalid-limit
fail-closed behaviour and absence of route/storage/background runtime.

## Next slice

C30-M may add a trusted decision application primitive that binds one consumed
C30-L request to one explicit C30-I APPROVE/REJECT review and, for APPROVE, one
real C7 ExperienceCandidate without granting automatic Memory 4 persistence.
