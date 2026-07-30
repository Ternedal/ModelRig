# A4-08 durable timeline consumer offsets

A4-08 adds explicit, durable consumer progress above A4-07 verified replay. It is
caller-driven and implements **at-least-once** delivery: a handler success is
followed by an atomic offset write for that exact hash-bound timeline entry.

## Contract

- offsets are keyed by campaign and consumer and stored as strict versioned JSON;
- every durable offset contains the A4-07 cursor sequence and content hash;
- progress may advance or be saved idempotently, but it may never regress or
  replace a sequence with a different hash;
- one explicit batch reads a verified A4-07 snapshot and persists progress after
  every accepted entry;
- a handler failure leaves the failed entry uncommitted and exposes the last
  durable cursor;
- an offset-write failure after handler success exposes both durable and attempted
  cursors. Retrying may deliver that accepted entry again, but can never skip it;
- consumers advance independently and survive process restart.

## Storage

The JSON store writes a temporary `0600` file, fsyncs it and atomically replaces
the prior offset. Construction and missing-offset reads create no directory.
The store is process-local; cross-process locking and distributed ownership are
not part of A4-08.

## Safety boundary

A4-08 adds no thread, timer, polling loop, API route, runtime mount or automatic
consumer. It never changes timeline bytes, Agent 3 contracts or campaign
lifecycle state. Durable exactly-once side effects are impossible without a
transaction shared with the consumer's own destination, so A4-08 states and
tests at-least-once semantics explicitly.
