# Agent 4 A4-06 — shared process-local delivery single-flight

A4-06 timeline delivery is intentionally at-least-once. The durable cursor prevents
silent acknowledgement loss, but two independently constructed delivery-service
instances can otherwise invoke the same consumer/campaign handler concurrently
before one cursor compare-and-swap loses.

This slice adds an explicit shared process-local guard for that overlap window.

## Contract

`InMemoryCampaignTimelineDeliverySingleFlight` owns at most one active flight for
each `(consumer_id, campaign_id)` key.

- `acquire()` returns an immutable monotonically numbered flight token;
- a second acquire for the same key fails before its handler is invoked;
- different consumers or campaigns remain independent;
- `release()` accepts only the currently active exact token;
- stale and foreign tokens fail closed;
- `run()` always releases in `finally`, including handler and cursor failures;
- `snapshot()` and `is_active()` expose process-local operator diagnostics only.

`SingleFlightCampaignTimelineDeliveryService` wraps the existing
`CampaignTimelineDeliveryService`. All service instances that must coordinate
have to share the same guard instance. The wrapper does not hide that requirement
or install a global singleton.

## Delivery semantics

The guard narrows concurrent duplicate execution inside one process. It does not
change the durable delivery guarantee:

- handler failure leaves the cursor unchanged;
- handler success followed by cursor persistence failure may still redeliver;
- consumer side effects must therefore remain idempotent or deduplicate using the
  stable event ID or entry hash;
- exactly-once effects are not claimed.

## Safety boundary

- process-local only;
- cooperative callers must use the wrapper and share one guard instance;
- no filesystem, distributed or cross-process lease;
- no background dispatcher, thread, timer or polling loop;
- no API route, runtime mount, network call or Agent 3 contract change;
- no production activation.

## Validation

The existing Agent 4 root workflow gate covers:

- same-key overlap rejection before the second handler;
- concurrent delivery for different consumers;
- release after handler failure;
- release after cursor persistence failure;
- stale and foreign token rejection;
- validation, pending-count delegation and dormant construction.
