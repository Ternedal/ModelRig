# C30-O — Private loopback-only episode review API

Status: draft, stacked on C30-N, independently default-off.

C30-O exposes the already-bounded C30-N trusted review service through a small
private HTTP surface for local operator/UI integration.

The route set is absent unless:

KALIV_CONSCIOUSNESS_EPISODE_REVIEW_ENABLED=1

The mount does not construct a mailbox, claim service, reviewer, model client,
Memory 4 bridge or durable store.

## Prefix

/experimental/consciousness/episode-review

Routes:

- GET /pending
- POST /claim
- POST /abandon
- POST /commit

All routes are loopback-only.

For POST routes, loopback admission happens before body parsing.

## Pending

GET /pending?limit=8 delegates to the C30-N bounded listing surface.

The limit must be an exact integer from 1 through 32.

Only reference-level episode review metadata is returned. Raw user text and
model chain-of-thought are absent.

## Claim

POST /claim requires the deterministic request id and canonical request ref.

A successful claim leaves the request pending in the process-local mailbox.

The response contains only the bounded C30-J request plus the C30-N claim and
fixed authority-denial metadata.

## Abandon

POST /abandon removes only the process-local claim. The underlying review
request remains pending.

## Commit

POST /commit requires:

- active claim id;
- exact request ref;
- explicit C30-I trusted review;
- a real C7 ExperienceCandidate for APPROVE, or no candidate for REJECT.

C30-N performs semantic preflight before consume. C30-M still preserves
trusted_review_required for approved episode-derived candidates.

## Generic errors

Invalid private bodies return one generic validation error. Claim/state mismatch
returns a generic conflict response.

Rejected private values are not reflected in HTTP errors.

## Independent runtime boundary

C30-O reads an already-constructed TrustedEpisodeReviewClaimService from
application state.

If the route flag is enabled but no service exists, requests return 503.

This slice therefore does not silently activate the C30-K mailbox or C30-N
review runtime merely because the transport route is mounted.

## Authority boundary

C30-O adds no new authentication authority, no non-loopback access, no durable
storage, no automatic review, no model call, no Memory 4 write, no scheduler,
timer, background worker, retry or Agent 3/tool execution.

production_activation remains false.

## Qualification

Focused tests cover exact flag behavior, flag-off no-route behavior, loopback
rejection before body parse, unavailable service, bounded pending listing,
claim-without-consume, generic mismatch handling, abandon semantics, explicit
REJECT and APPROVE commit flows, C7 trusted-review preservation and private body
error hygiene.

## Next slice

C30-P may define the separately default-off process lifecycle that constructs
the optional C30-J mailbox and C30-N claim service and injects them into the
existing C19 session plus app state without making review infrastructure a
requirement for Consciousness Core operation.
