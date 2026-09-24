# C30-T — Compact operator review summary

Status: draft, stacked on C30-S, read-only.

C30-T combines the privacy-safe C30-Q status, C30-R aggregate counters and
C30-S attention evaluation into one bounded operator/dashboard projection.

It does not expose individual review items.

## Summary contents

The summary contains:

- runtime state and attention level;
- attention signal codes;
- runtime/transport presence flags;
- mailbox capacity, pending count and claimed count;
- mailbox-full state;
- latest publication status;
- selected aggregate publication counters;
- aggregate successful claim/abandon/approve/reject counters.

The aggregate counters retain the C30-R signed 64-bit saturation bound.

## Deliberately excluded

The summary contains no:

- review request payload;
- request id/ref;
- claim id;
- closure evidence;
- participant refs;
- active-goal refs;
- source refs;
- user text;
- assistant text;
- model chain-of-thought.

It is therefore suitable for an operator dashboard without turning the dashboard
into a review-data export surface.

## Read-only composition

build_episode_review_operator_summary performs:

C30-Q status
  -> C30-S attention evaluation
  -> compact projection

It does not mutate the mailbox, claim service, observability recorder or
cognitive session.

Repeated evaluation against unchanged state returns the same summary.

## Private route

C30-O now also exposes:

GET /experimental/consciousness/episode-review/summary

The route uses the same independently default-off transport flag and loopback
boundary as the rest of the review API.

It does not require a live review service. For example, transport-only state can
still return a useful bounded summary.

## Authority boundary

C30-T sends no notification, takes no automatic action, writes no durable state,
calls no model or Memory 4 service, starts no timer/scheduler/background task,
and grants no semantic review or execution authority.

production_activation remains false.

## Qualification

Focused tests prove:

- OFF summary is compact and zeroed;
- TRANSPORT_ONLY is visible without being treated as an alert;
- aggregate metrics and attention codes compose correctly;
- no individual review identity is serialized;
- repeated summary reads are mutation-free;
- the private summary route is loopback-only and works without a live service.

## Next slice

C30-U may add a single review-runtime contract/qualification manifest that
summarizes the C30-H through C30-T feature gates, authority invariants and
operator surfaces so the stacked implementation can be qualified and landed as
one coherent capability.
