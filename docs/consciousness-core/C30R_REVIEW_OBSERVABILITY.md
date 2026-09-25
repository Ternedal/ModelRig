# C30-R — Privacy-safe aggregate review observability

Status: draft, stacked on C30-Q, process-local and non-durable.

C30-R adds aggregate counters for the episode-review workflow without creating
a per-request audit log.

The recorder stores counts only.

## Counted publication outcomes

C30-K publication records one counter for each completed publication outcome:

- NOT_APPLICABLE
- MAILBOX_UNAVAILABLE
- NO_REVIEW
- ENQUEUED
- DUPLICATE
- CAPACITY_REACHED
- MAILBOX_CLOSED
- REPLAY_LEDGER_FULL

Each invocation contributes to exactly one publication counter when an
observability recorder is supplied.

## Counted review workflow outcomes

C30-N records only successful state transitions:

- successful claim;
- successful abandon;
- successful APPROVE commit;
- successful REJECT commit.

Invalid request refs, duplicate claims, failed semantic preflight and failed
decision application do not increment success counters.

The metrics therefore describe completed workflow outcomes rather than attempts.

## One shared production recorder

C30-P constructs one EpisodeReviewObservability instance alongside the mailbox.

That exact recorder is injected into:

- C30-N TrustedEpisodeReviewClaimService;
- app.state.consciousness_episode_review_observability;
- C19 ProductionCognitiveSession;
- C30-K publish_episode_closure_review calls.

Publication and operator-review counters therefore describe the same
process-local review runtime.

The recorder remains optional on lower-level primitives so existing isolated
tests and explicit callers remain valid.

## Bounded counters

Every counter is a saturating signed 64-bit non-negative integer with maximum:

9223372036854775807

A very long-lived process therefore cannot turn an aggregate counter into
unbounded integer state.

## No audit content

The recorder explicitly stores no:

- request ids;
- request refs;
- claim ids;
- closure evidence;
- timestamps;
- event history;
- user text;
- assistant text;
- model chain-of-thought.

It is not a substitute for a durable audit system and does not create one.

## Status projection

C30-Q status may include the aggregate observability snapshot when the recorder
is present.

The existing /experimental/consciousness/episode-review/status route therefore
gains operational counts without exposing any review item identity.

C30-Q also verifies that a production runtime's observability app-state binding
is the exact recorder owned by that runtime. A mismatched binding reports
RUNTIME_UNAVAILABLE.

## Lifecycle

C30-R adds no independent persistence or lifecycle.

The recorder is owned by C30-P and becomes unreachable when the review runtime
app-state bindings are removed at shutdown.

## Authority boundary

C30-R adds no model call, Memory 4 call/write, semantic review authority,
scheduler, timer, retry, background worker, durable storage, route mutation or
Agent 3/tool execution.

production_activation remains false.

## Qualification

Focused tests prove zeroed/privacy-safe snapshots, publication outcome counts,
success-only claim/abandon counts, semantic-failure non-counting,
APPROVE/REJECT counters, shared production recorder behavior and status
serialization without request/claim identifiers.

## Next slice

C30-S may define bounded operator alert thresholds derived from aggregate
counters and mailbox state, such as sustained capacity pressure, without
introducing timers, notifications, background monitoring or autonomous action.
