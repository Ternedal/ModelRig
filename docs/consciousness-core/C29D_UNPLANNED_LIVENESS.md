# C29-D — Liveness-bounded unplanned dormancy

Status: draft, default-off startup evidence only,
`production_activation=false`.

C29-D lets the C28-C unplanned-dormancy path use the latest durable C29-A
runtime-liveness witness as bounded temporal evidence.

> **Last known alive is not crash time.**

## Activation

C29-D has its own exact opt-in:

```text
KALIV_CONSCIOUSNESS_UNPLANNED_LIVENESS_ENABLED=1
```

The ordinary C13 sleep lifecycle must already be enabled for C28-C to run.

The liveness witness is read from the same bounded C29-A store used by C29-C:

```text
KALIV_CONSCIOUSNESS_LIVENESS_STATE
default: ./kaliv-consciousness-liveness.json
```

## When the store is touched

C29-D reads the liveness store only when all of these are true:

1. C13 is active;
2. there is no pending planned SleepRecord;
3. a C28-B WakeAcknowledgement marker survives;
4. the current Self/Person binding authenticates that marker;
5. the separate C29-D gate is on.

A normal PLANNED_SLEEP wake never checks the C29-D gate and never reads the
liveness store.

With the C29-D gate off, C28-C behavior is unchanged.

## Evidence semantics

A C29-A witness proves:

```text
runtime was alive at trusted anchor T
while bound to durable SelfState S
```

At a later unplanned wake W, C29-D may derive:

```text
maximum possible offline duration <= W - T
```

when trusted temporal evidence can relate T to W without moving backwards.

It does **not** derive:

- a crash timestamp;
- an exact offline duration;
- cognition after T;
- a claim that the process stayed alive until T + 1 ms.

## WakeReceipt

The existing WakeReceipt remains an unplanned-dormancy receipt:

```text
dormancy_kind = UNPLANNED_DORMANCY
sleep_id = null
entry_anchor_ref = null
offline_duration_ms = null
duration_known = false
duration_confidence = 0.0
cognition_during_gap = false
```

C29-D adds optional evidence fields:

```text
last_known_alive_witness_ref
last_known_alive_anchor_ref
offline_duration_upper_bound_ms
offline_duration_upper_bound_confidence
```

The upper-bound fields are deliberately separate from the exact-duration
fields. A validator prevents an upper bound from being represented as a known
offline duration.

If the witness is valid but wall time rolled backwards across runtime epochs,
the last-known-alive witness/anchor references may still be carried while the
numeric upper bound remains unknown.

## Identity and durable-state checks

A configured C29-D witness must match the current:

- Self id;
- Person Revision.

A witness whose durable SelfState revision is greater than the current
authoritative durable revision fails closed.

At the same durable revision, a conflicting canonical SelfState ref fails
closed.

An older witness from the same identity may still be used as older
last-known-alive evidence. It does not replace or downgrade the current
SelfState.

The historical C28-B marker still does not project its old durable SelfState
binding into the unplanned WakeReceipt.

## Cognitive projection

C19-A and C26-A continue to receive the normal WakeReceipt.

When a numeric upper bound exists, their bounded wake summary says that the
exact offline duration is unknown and that last-known-alive evidence bounds the
possible offline duration to at most the derived value.

The summary explicitly states that this is not a crash timestamp.

No model call is triggered by C29-D itself.

## Authority boundary

C29-D adds no:

- scheduler;
- timer;
- heartbeat thread;
- polling loop;
- retry loop;
- route;
- model call;
- Memory 4 write;
- Agent 3/tool execution;
- BodyRig/VoiceRig mutation.

It only strengthens the evidence carried by an already-classified C28-C
unplanned wake.

## Qualification target

Focused qualification proves:

1. exact flag semantics;
2. planned sleep performs zero C29-D/liveness IO;
3. gate-off preserves C28-C exactly;
4. trusted liveness yields an upper bound while exact duration stays unknown;
5. wall-clock rollback yields no numeric bound;
6. foreign identity fails closed;
7. same-revision conflicting SelfState evidence fails closed.

## Next slice

C29-E may project this bounded continuity evidence into a dedicated
post-wake temporal/continuity state so later cognition can distinguish
"exact sleep duration" from "unplanned gap bounded by last-known-alive".

That projection must remain descriptive evidence only and must not create a
scheduler or automatic cognition source.
