# C20-B — Atomic world-evidence admission into live session

Status: draft, in-process only, `production_activation=false`.

C20-B connects C20-A's epistemic world reducer to the C19-B production session.

> **A fact may enter the world model without automatically triggering cognition;
> when it does request attention, the attention event is bound to that exact
> evidence object.**

## Admission flow

```text
LiveCognitiveSessionState
+ WorldEvidenceEvent
+ explicit attention salience
        |
        v
pure C20-A reduction
        |
        v
prospective next LiveCognitiveSessionState
        |
        v
canonical CognitionEvent from exact evidence ref
        |
        v
C18-B submit()
        |
        v
adopt prospective live world only after queue succeeds
```

The ordering is intentional.

World reduction is pure. The only side effect is supervisor event admission. If
the bridge rejects admission, the new live world is never adopted.

## Canonical attention event

New evidence produces exactly one deterministic cognition event:

- `kind=world_change`;
- source_ref = canonical SHA-256 WorldEvidenceEvent ref;
- summary = exact evidence proposition;
- observed sequence = evidence observed sequence;
- salience = explicit bounded caller input;
- event id = deterministic hash of the canonical evidence ref.

This makes the attention request auditable back to one exact epistemic event.

## Replay

An identical WorldEvidenceEvent replay is handled by C20-A as idempotent.

C20-B then performs:

```text
world change: no
SelfState change: no
new CognitionEvent: no
model call: no
```

This is important after the original attention event has already been consumed:
replaying storage/delivery of the same evidence must not make Kaliv think about
the same fact again as if it were new.

A conflicting reuse of the same evidence event id still fails closed.

## Atomic failure behavior

Before supervisor admission, C20-B constructs and validates the complete
prospective LiveCognitiveSessionState.

Only then does it call C18-B `submit()`.

If submit fails—for example because one cognitive step is already in flight:

- supervisor state rejects the event;
- live WorldState remains unchanged;
- live SelfState remains unchanged;
- no partial transition is observable.

The bridge's C18-B single-flight rule therefore extends cleanly into epistemic
state updates.

## Separation from cognition

Evidence admission performs no ThoughtEngine call.

The event simply becomes pending attention.

A later explicit:

```python
await session.step(profile=...)
```

may process it through:

```text
C18-A -> C15 -> C16
```

At that point the already-updated live WorldState is part of the C15 context.

## Authority boundary

Every WorldEvidenceAdmissionResult fixes:

```text
model_calls=0
self_state_store_write_applied=false
durable_memory_write_authority=false
execution_authority=false
scheduling_authority=false
production_activation=false
```

C20-B adds no:

- external route;
- automatic cognition;
- scheduler/thread/timer;
- durable SelfState write;
- Memory 4 write;
- tool/Agent3 execution;
- BodyRig/VoiceRig actuation.

## What this unlocks

The production cognitive session can now represent:

```text
the world changed
        +
this deserves attention
```

as two linked but distinct Core facts.

A later event-source adapter can translate one reviewed runtime source into an
exact WorldEvidenceEvent, rather than letting arbitrary chat/model prose update
the world model directly.
