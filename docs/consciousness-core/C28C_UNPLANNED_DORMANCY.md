# C28-C — Unplanned dormancy detection from wake acknowledgement marker

Status: draft, continuity classification only,
`production_activation=false`.

C28-C turns the C28-B wake acknowledgement marker into honest evidence of an
unclean runtime termination.

> **A surviving awake marker proves the previous runtime did not write a new
> clean sleep boundary. It does not prove when the crash happened.**

## Detection

At C13 startup the existing lifecycle store can contain:

- a pending SleepRecord;
- a SleepWakeAcknowledgement marker;
- no payload.

The interpretation is:

```text
SleepRecord
-> PLANNED_SLEEP wake

SleepWakeAcknowledgement
-> previous planned wake was already accepted
-> no later clean SleepRecord replaced it
-> UNPLANNED_DORMANCY

no payload
-> no sleep/dormancy receipt
```

## Identity

Before an acknowledgement marker may produce a wake receipt, its:

- self id;
- Person Revision;

must match the current authoritative SleepBinding.

Mismatch fails closed.

The marker's historical C28-A durable SelfState ref/revision is deliberately not
projected into the unplanned WakeReceipt.

The previous runtime may have legitimately advanced and checkpointed SelfState
after the marker was created.

## Time honesty

The acknowledgement marker does not contain a trusted crash timestamp.

C28-C therefore creates an unplanned WakeReceipt with:

```text
dormancy_kind = UNPLANNED_DORMANCY
sleep_id = null
entry_anchor_ref = null
offline_duration_ms = null
duration_known = false
duration_confidence = 0.0
cognition_during_gap = false
```

The current wake anchor remains trusted C11 evidence.

No elapsed duration is inferred from the old planned wake time, because that
would incorrectly include time when the previous runtime was actually active.

## C19 integration

The existing production session factory receives the unplanned WakeReceipt and
performs the normal C19 wake bootstrap:

- exact Self/Person verification;
- fresh transient WorldState/Workspace;
- no claim of cognition during the gap;
- one wake-followup attention event;
- zero automatic model calls.

Because the unplanned receipt has `sleep_id=null`, C28-B
`acknowledge_wake()` is a no-op.

The existing acknowledgement marker remains in the lifecycle store while that
runtime is active.

## Clean shutdown after recovery

If the recovered runtime later shuts down cleanly, C13 writes a new SleepRecord.

That atomically replaces the acknowledgement marker.

The following startup therefore returns to the ordinary PLANNED_SLEEP path.

## Repeated crashes

If another crash occurs before a clean shutdown, the same acknowledgement marker
still proves that no new clean sleep boundary was written.

C28-C may therefore classify the next startup as UNPLANNED_DORMANCY again.

It still does not claim an outage duration.

## Authority boundary

C28-C adds no:

- new store;
- route;
- activation flag;
- model call;
- scheduler;
- timer;
- thread;
- polling;
- retry;
- Memory 4 write;
- Agent 3/tool execution;
- BodyRig/VoiceRig mutation.

It only changes how the already-persisted C28-B marker is interpreted at
startup.
