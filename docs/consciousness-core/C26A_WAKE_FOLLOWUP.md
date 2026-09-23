# C26-A — Authoritative wake-followup event admission

Status: draft, event-admission only, `production_activation=false`.

C26-A connects the already-authoritative C12/C13 wake continuity receipt to the
existing C18 event queue.

It does not perform cognition by itself.

> **Wake is evidence of continuity. A wake-followup event is attention, not a model call.**

## Existing wake authority

C12/C13 already provide a strict `WakeReceipt` with:

- exact `self_id`;
- exact Person Revision;
- dormancy kind;
- wake temporal anchor;
- known/unknown offline duration;
- continuity preserved;
- `cognition_during_gap=false`;
- no execution/scheduling/memory-write authority.

C19-A already consumes that same receipt to rebuild a fresh runtime
WorldState/Workspace and to represent wake continuity as observed context.

Before C26-A, no `CognitionEvent` was queued from that receipt.

## Projection

C26-A creates exactly one:

```text
kind = wake_followup
```

event from the validated receipt.

The event is deterministic.

Its source ref is the canonical SHA-256 reference of the exact WakeReceipt.

Its event id is derived from:

```text
wake-followup-v1 + canonical WakeReceipt ref
```

Therefore the same validated receipt produces the same event id.

## Identity binding

Before projection:

```text
WakeReceipt.self_id == live SelfState.self_id
WakeReceipt.person_revision == live SelfState.person_revision
WakeReceipt.cognition_during_gap == false
```

Any mismatch fails closed.

C26-A cannot use a wake receipt from another self or Person Revision.

## Event content

The bounded summary records only:

- planned vs unplanned dormancy;
- known offline duration in milliseconds, or that duration is unknown;
- the verified fact that cognition did not continue during the offline gap.

It does not invent thoughts, memories or actions that supposedly occurred while
the process was off.

## Salience

Wake-followup salience is fixed Core policy:

```text
0.96
```

It is not supplied by the replaceable ThoughtEngine.

The event's `observed_sequence` comes from the trusted wake temporal anchor.

## Production admission

During C19 production session construction:

```text
persisted SelfState
+ exact active Person Revision
+ optional WakeReceipt
-> C19 fresh runtime bootstrap
-> live ProductionCognitiveSession
-> if WakeReceipt exists:
     build deterministic wake_followup
     submit to existing C18 queue
```

No WakeReceipt means no wake-followup event.

## Idempotency

C18 already treats duplicate event ids idempotently when the event contents are
identical.

Therefore re-admitting the same C26-A event:

- does not duplicate the pending event;
- does not advance supervisor revision;
- does not call a model.

Reusing the same event id with conflicting content remains a C18 contract error.

## Relationship to C25

C26-A is the first authoritative non-user production source for the autonomous
cognition path.

With C25-A/B/C deliberately enabled:

```text
WakeReceipt
-> C26-A wake_followup event
-> C18 pending queue
-> existing scheduler cadence
-> C25-C
-> C25-B
-> C25-A policy
-> exact-event cognitive step
```

C25-A still owns whether that pending wake event is eligible at the current
time.

C26-A itself does not bypass cooldown, rolling budget, supervisor pacing or
single-flight.

## Authority boundary

C26-A adds no:

- model call;
- ThoughtEngine authority;
- scheduler;
- timer;
- thread;
- polling;
- retry;
- durable state write;
- Memory 4 mutation;
- Agent 3/tool execution;
- BodyRig actuation;
- VoiceRig actuation.

The produced event remains:

```text
production_activation=false
```

and stays pending until an existing separately reviewed cognitive-step path
selects it.
