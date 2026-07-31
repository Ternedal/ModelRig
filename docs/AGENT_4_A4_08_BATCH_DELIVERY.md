# Agent 4 A4-08 — bounded durable consumer batches

A4-08 composes the existing A4-06 durable delivery cursor and shared
process-local single-flight guard into one bounded consumer operation. It does
not introduce a second offset store or cursor format.

## Why this slice exists

A4-06 deliberately exposes one explicit `deliver_next()` operation. That is the
smallest safe at-least-once primitive, but an operator-facing worker should not
have to recreate batching, bounds and flight scope at every call site.

`CampaignTimelineBatchDeliveryService.deliver_batch()` therefore:

1. acquires one shared flight for the complete `(consumer_id, campaign_id)` batch;
2. delivers at most `max_entries` contiguous verified entries;
3. invokes the caller's handler before each durable cursor advancement;
4. persists progress after every accepted entry through the A4-06 cursor store;
5. returns the delivered entries, final durable cursor and remaining count;
6. releases the flight after success or any failure.

The batch size is explicitly bounded to 1..1,000 entries.

## Failure semantics

The contract remains at-least-once:

- if a handler fails, that entry is not acknowledged and is offered again later;
- earlier entries accepted in the same batch remain durably acknowledged;
- if cursor persistence fails after handler acceptance, the entry may be offered
  again because the side effect cannot be proven durable;
- overlapping batches for the same consumer and campaign fail before a second
  handler runs;
- different consumer/campaign keys retain independent durable progress.

A4-08 intentionally reuses `CampaignTimelineCursor`,
`JsonCampaignTimelineCursorStore` and
`InMemoryCampaignTimelineDeliverySingleFlight`. The retired parallel prototype
that declared a second consumer-offset envelope is not part of this line.

## Safety boundary

- caller-driven and dormant;
- no thread, timer, polling loop, background tailer or automatic replay;
- no API route, runtime mount or network access;
- no timeline append, repair, compaction, deletion or truncation;
- no Agent 3 contract or production activation change.

## Validation

The shared Agent 4 workflow gate covers:

- bounded delivery and durable resume;
- per-entry acknowledgement inside a batch;
- handler failure and deterministic redelivery;
- independent consumer progress;
- one shared flight across the whole batch;
- flight release after completion;
- empty timelines and strict batch-size validation.
