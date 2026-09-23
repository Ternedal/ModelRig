# C29-A — Durable runtime liveness witness primitive

Status: draft, primitive only, `production_activation=false`.

C29-A adds one bounded durable witness proving that the Consciousness Core
runtime was alive at one trusted C11 temporal anchor while bound to one exact
durable C14 SelfState.

It does **not** claim when a later crash happened.

> **Alive at T is evidence. Crashed at T is not.**

## Input

A witness is built from:

- one exact `PersistentSelfState`;
- one trusted C11 `TemporalAnchor`;
- one bounded source ref.

The builder derives the canonical SelfState ref itself.

## Trusted temporal evidence

A C29-A witness requires an anchor with:

- runtime epoch id;
- monotonic time;
- wall-clock time;
- confidence exactly `1.0`.

An incomplete or lower-confidence temporal anchor is rejected.

This prevents a heuristic or inferred time from becoming durable liveness
evidence.

## Witness

`RuntimeLivenessWitness` binds:

- Self id;
- Person id;
- Person Revision;
- exact durable SelfState ref;
- exact durable SelfState revision;
- trusted temporal anchor;
- bounded source ref.

It fixes:

```text
runtime_alive_at_anchor = true
cognition_after_anchor_claimed = false
durable_memory_write_authority = false
execution_authority = false
scheduling_authority = false
production_activation = false
```

The witness says nothing about what happened after the anchor.

## Store

`RuntimeLivenessStore` owns one bounded atomic witness.

The envelope uses:

- canonical JSON;
- SHA-256 payload digest;
- bounded size;
- fsync;
- atomic replace.

It is not an event log and stores no liveness history.

## Write ordering

### No previous witness

The first valid witness is written as `CREATED`.

### Exact same witness

An exact repeat is `IDEMPOTENT` with `store_write_applied=false`.

### Higher durable SelfState revision

A witness may replace the previous one when the durable SelfState revision is
higher. A higher durable revision may legitimately cross a runtime epoch
boundary.

### Same durable SelfState revision

A witness may move forward at the same revision only when:

- canonical SelfState ref is unchanged;
- runtime epoch is unchanged;
- temporal sequence is strictly newer;
- monotonic time does not move backwards.

This permits multiple liveness witnesses while the same durable state remains
current inside one process runtime. An equal-revision witness from another
runtime epoch is rejected.

### Backward durable revision

Any lower durable SelfState revision fails closed.

### Conflicting ref at same revision

The same durable revision may never be associated with two different canonical
SelfState refs.

### Identity change

Self id, Person id or Person Revision changes fail closed.

## What C29-A proves

C29-A can prove that the runtime was alive at anchor T with durable SelfState S
at revision N.

It cannot prove that the runtime crashed at T, that it was offline after T, or
that cognition continued after T.

If the process later disappears, the duration between the last witness and the
next startup is therefore only a possible **upper bound** for offline time.
It is never an exact crash duration.

## No production cadence

C29-A adds no:

- lifecycle wiring;
- environment switch;
- scheduler hook;
- timer;
- thread;
- polling loop;
- retry;
- HTTP route;
- model call;
- Memory 4 write;
- Agent 3/tool execution;
- BodyRig/VoiceRig mutation.

The store requires an explicit path and can only be written by an explicit
caller.

## Next slice

C29-B may connect witness creation to an already-authorized runtime event such
as a successful durable SelfState checkpoint.

That integration must reuse an existing trusted clock/cadence and must not
invent a second heartbeat thread or timer.
