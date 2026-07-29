# Agent 4 T-033 — durable retry scheduling

This slice applies the pure T-033 retry decision to durable campaign state. It
remains caller-driven: the host explicitly reports a stopped runtime attempt,
and normal explicit scheduler dispatch later starts the next attempt.

## State contract

- `RUNNING -> SCHEDULED` is the only new lifecycle edge.
- The failed attempt number is retained while waiting.
- The next explicit `SCHEDULED -> RUNNING` transition increments the attempt.
- Retry failure details remain in the ordered `RETRY_SCHEDULED` event; the
  campaign state does not pretend to be terminal while a retry is pending.
- Permanent, cancelled-classified and budget-exhausted failures become durable
  terminal `FAILED` records.

## Ordering and crash safety

`CampaignRetrySchedulingService.handle_failure()` performs work in this order:

1. load and validate a durable `RUNNING` campaign
2. compute the pure retry decision
3. persist either terminal `FAILED` or retry `SCHEDULED`
4. enqueue the persisted retry specification
5. emit the ordered audit event
6. release optional resource ownership

A crash after persistence but before enqueue leaves a durable `SCHEDULED`
record. The existing T-031 startup recovery service rehydrates it, avoiding lost
work. No retry is dispatched by this service.

## Resource boundary

The service accepts an optional release callback. Resource-aware composition can
release the completed attempt only after its replacement state is durable. A
persistence failure therefore keeps ownership fail-closed rather than allowing
premature reuse.

## Validation

The existing Agent 4 foundation workflow gate covers retry scheduling,
next-attempt dispatch, terminal failures, exhausted budgets, invalid lifecycle
states and recovery of a persisted retry whose in-memory queue entry was lost.

## Deferred

Automatic runtime failure ingestion, durable failure-envelope storage, operator
retry overrides, jitter, distributed queues and background dispatch remain
separate slices.
