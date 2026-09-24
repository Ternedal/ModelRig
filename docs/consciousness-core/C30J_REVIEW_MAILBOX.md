# C30-J — Bounded process-local review mailbox

Status: draft, stacked on C30-I, `production_activation=false`.

C30-J adds a small in-memory mailbox for C30-I episode experience review
requests. It is deliberately **not** a durable memory queue and is not wired
into C19 episode segmentation yet.

## Request creation

`build_episode_experience_review_request` accepts only bounded C30-H closure
evidence.

- Empty episodes return no request.
- Non-empty episodes produce one deterministic request.
- The request carries the bounded closure evidence and C30-I review plan only.
- Raw user text and model chain-of-thought remain absent.

## Bounded mailbox

`EpisodeExperienceReviewMailbox` has an explicit capacity between 1 and 32.
The default is 8.

If capacity is reached, enqueue fails closed. It never silently drops or
overwrites a pending review request.

## Exact-once lifecycle

A request id may be admitted only once during one mailbox lifetime.

- enqueue records the request id in a bounded process-local replay ledger;
- consume removes the pending request exactly once;
- a second consume fails because the request is no longer pending;
- re-enqueue of the same request id also fails;
- the replay ledger is capped at 4096 ids and refuses further admission when
  full rather than becoming unbounded.

## Close lifecycle

`close()` clears pending requests and replay tombstones and permanently closes
the mailbox instance. This ensures process/session-local evidence cannot leak
across a lifecycle boundary.

## No automatic wiring yet

C30-J is intentionally not called automatically from C30-G/C19.

Episode segmentation must not become dependent on review capacity. A later
slice can define explicit non-blocking session wiring and overflow policy after
the mailbox contract is qualified.

## Authority boundary

C30-J adds no:

- persistent storage;
- Memory 4 service call;
- model call;
- background task/thread/retry;
- scheduler or timer;
- Agent 3/tool execution;
- SelfState or Person mutation;
- production activation.

## Qualification

Focused tests prove empty-episode suppression, deterministic bounded request
construction, capacity refusal without dropping pending requests, exact-once
consume, duplicate rejection, lifecycle clearing and absence of hidden storage
or background runtime.

## Next slice

C30-K may add explicit, non-blocking C19 session wiring that publishes eligible
C30-H closure evidence into a process-local mailbox while preserving episode
boundary application even when review admission is unavailable.
