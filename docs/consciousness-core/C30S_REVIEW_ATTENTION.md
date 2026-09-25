# C30-S — Read-only episode review attention policy

Status: draft, stacked on C30-R, pure evaluation only.

C30-S converts the privacy-safe C30-Q status plus C30-R aggregate counters into
bounded operator-attention signals.

It is deliberately not an alerting system.

## Default policy

The default policy evaluates:

- mailbox occupancy at or above 75 percent;
- mailbox full;
- 24 or more simultaneously claimed reviews;
- three or more capacity-rejected publications;
- any replay-ledger exhaustion publication;
- any publication attempt against a closed mailbox;
- ten or more duplicate publications.

These are process-lifetime aggregate thresholds, not time-windowed or behavioral
claims.

C30-S therefore uses names such as REPEATED_CAPACITY_REJECTION rather than
claiming sustained pressure over a time interval it does not measure.

## Levels

The aggregate level is:

- OK when no signal is present;
- ATTENTION when one or more attention signals are present;
- DEGRADED when any degraded signal is present.

Current degraded signals are:

- RUNTIME_UNAVAILABLE;
- MAILBOX_FULL;
- REPEATED_CAPACITY_REJECTION;
- REPLAY_LEDGER_EXHAUSTION.

Current attention signals are:

- MAILBOX_PRESSURE;
- CLAIM_PRESSURE;
- PUBLICATION_TO_CLOSED_MAILBOX;
- REPEATED_DUPLICATE_PUBLICATION.

## No automatic alerting

Every result fixes:

notifications_sent=0
timers_started=0
scheduler_jobs_created=0
background_tasks_started=0
automatic_actions_taken=0

The evaluator does not retain historical snapshots and does not schedule another
evaluation.

A caller decides when to evaluate and what, if anything, a human operator does
with the result.

## Privacy

Signals contain only:

- signal code;
- severity;
- observed aggregate value;
- configured threshold.

They contain no request refs, claim ids, closure evidence, raw user text or model
chain-of-thought.

## Private read surface

C30-O now also exposes:

GET /experimental/consciousness/episode-review/attention

The route is covered by the same independently default-off C30-O transport flag
and loopback boundary.

It requires no live claim service because it derives its result from the existing
privacy-safe status projection. In transport-only state it reports OK rather than
treating an explicitly disabled runtime as an incident.

## Authority boundary

C30-S creates no notification, email, push message, scheduler job, timer,
background worker, retry, persistence, Memory 4 call, model call, semantic review
decision, Agent 3/tool execution or production activation.

## Qualification

Focused tests prove:

- OFF and TRANSPORT_ONLY remain non-alerting states;
- unavailable runtime becomes DEGRADED;
- pressure and full mailbox are distinct;
- aggregate thresholds produce only identity-free signals;
- claim pressure is informational;
- repeated evaluation is pure and deterministic;
- no notification/timer/action side effects exist;
- the private attention route remains loopback-only.

## Next slice

C30-T may add an operator-facing summary projection that combines C30-Q status
and C30-S attention into one bounded dashboard object without adding new review
authority or exposing individual review requests.
