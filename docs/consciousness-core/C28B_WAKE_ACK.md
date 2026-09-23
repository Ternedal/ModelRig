# C28-B — Single-use planned sleep wake acknowledgement

Status: draft, continuity hardening only, `production_activation=false`.

C28-B prevents an already-accepted planned SleepRecord from being reused as a
future planned wake.

## Problem

Before C28-B, C13 left the last planned SleepRecord in place after startup.

If the process later crashed before writing a new clean SleepRecord, the next
startup could read that same old record again and incorrectly treat continuity
as another `PLANNED_SLEEP`.

## Store evolution

The existing C13 SleepStateStore file remains the only lifecycle store.

Its existing `sleep-envelope/v1` may now contain either:

- `sleep-record/v1` — pending planned sleep;
- `sleep-wake-ack/v1` — that planned sleep was already accepted by C19.

`SleepStateStore.read()` remains backward-compatible: it returns only a pending
SleepRecord.

A wake acknowledgement therefore behaves as "no pending planned sleep" for the
next startup.

## Wake acknowledgement

The marker binds:

- sleep id;
- wake id;
- self id;
- Person Revision;
- optional C28-A durable SelfState ref/revision;
- `planned_sleep_consumed=true`.

The acknowledgement is written atomically using the same fsync + replace path
as SleepRecord persistence.

## Ordering

The planned SleepRecord is **not** consumed merely because C13 can construct a
WakeReceipt.

The production order is:

```text
SleepRecord
-> C13 WakeReceipt
-> C19 durable SelfState/person verification
-> C19 fresh runtime bootstrap
-> wake_followup CognitionEvent admission
-> C28-B acknowledge_wake()
-> atomic SleepWakeAcknowledgement replacement
-> session may be exposed
```

If C19 bootstrap or wake-followup admission fails, the SleepRecord remains
pending and can be retried on a later startup.

If acknowledgement itself fails, session creation fails closed and the session
is closed before exposure.

## Idempotence / conflict

Repeating acknowledgement for the exact same wake is idempotent.

A conflicting acknowledgement fails closed when any of these differ:

- sleep id;
- wake id;
- self id;
- Person Revision;
- C28-A durable SelfState binding.

## Clean shutdown

A later clean shutdown writes the next SleepRecord through the existing C13
atomic writer.

That naturally replaces the acknowledgement marker.

The file therefore alternates conceptually:

```text
SleepRecord
-> accepted wake acknowledgement
-> next clean SleepRecord
-> accepted wake acknowledgement
...
```

## Lifecycle ownership

While C13 is active, the runtime is exposed internally as:

```text
app.state.consciousness_sleep_runtime
```

C19 uses that private in-process owner to acknowledge the exact WakeReceipt.

The app-state runtime and wake receipt are removed when C13 teardown completes.

No HTTP route or model-visible capability is introduced.

## Crash semantics

C28-B guarantees only this:

> an accepted planned SleepRecord cannot later be replayed as another planned
> wake.

An acknowledgement marker surviving a crash is **not yet** converted into a
full `UNPLANNED_DORMANCY` receipt and does not estimate crash/offline duration.

That requires separately reviewed trusted last-running temporal evidence.

## Authority boundary

C28-B adds no:

- model call;
- scheduler;
- thread;
- timer;
- polling;
- retry loop;
- Memory 4 write;
- Agent 3/tool execution;
- BodyRig/VoiceRig mutation;
- new store;
- route;
- activation flag.

It only changes the lifecycle payload state of the existing C13 store after C19
has successfully accepted a planned wake.
