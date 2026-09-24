# C30-P — Episode review runtime lifecycle

Status: draft, stacked on C30-O, independently default-off.

C30-P constructs and owns the optional process-local episode review runtime that
C30-K, C30-N and C30-O can share.

The runtime is absent unless:

KALIV_CONSCIOUSNESS_EPISODE_REVIEW_RUNTIME_ENABLED=1

This flag is independent from the C30-O transport flag.

## Runtime ownership

One EpisodeReviewRuntime owns exactly:

- one bounded C30-J EpisodeExperienceReviewMailbox;
- one C30-N TrustedEpisodeReviewClaimService bound to that same mailbox.

The default mailbox capacity is 8 and remains bounded by the C30-J contract.

No durable store is created.

## Lifecycle ordering

The review lifespan is composed inside the C19 cognitive-session lifespan and
outside the lower supervisor/sleep lifecycles.

Startup order is therefore:

lower runtime lifecycles
  -> C30-P review runtime
  -> C19 production cognitive session
  -> outer services

Before production_cognitive_session_factory runs, C30-P exposes:

- app.state.consciousness_episode_review_runtime
- app.state.consciousness_episode_review_mailbox
- app.state.consciousness_episode_review_service

C19 reads the exact mailbox object from app state and injects it into
ProductionCognitiveSession.

C30-K publication and C30-N operator review therefore operate on the same
process-local mailbox.

## Independent transport

C30-P does not inspect the C30-O API flag.

This allows four explicit states:

- runtime off / transport off: no review infrastructure;
- runtime on / transport off: internal review mailbox only;
- runtime off / transport on: route exists but returns 503;
- runtime on / transport on: private loopback review workflow available.

No flag silently enables another authority boundary.

## Shutdown

C19 closes its session first and clears its transient episode state.

C30-P then closes the claim service and mailbox and removes all three app-state
bindings.

Mailbox close is idempotent, so shared lifecycle cleanup remains safe when C19
has already closed the same mailbox.

No review request or claim survives process shutdown.

## Production factory validation

production_cognitive_session_factory accepts the optional app-state mailbox only
when it is an exact EpisodeExperienceReviewMailbox.

Unexpected app-state types fail closed.

## Authority boundary

C30-P adds no HTTP route, no model call, no Memory 4 read/write, no persistent
storage, no automatic semantic review, no timer/scheduler/background worker,
no retry loop and no Agent 3/tool execution.

production_activation remains false throughout the contained review contracts.

## Qualification

Focused tests prove exact runtime opt-in, flag-off inertness, bounded factory
construction, deterministic cleanup, review-runtime-before-C19 ordering, exact
mailbox identity injection into the production session factory and fail-closed
handling of invalid app-state mailbox types.

## Next slice

C30-Q may add read-only operator status/health projection for the review runtime
so UI and diagnostics can distinguish runtime-off, transport-only, active,
mailbox-full and claimed-work states without exposing request contents.
