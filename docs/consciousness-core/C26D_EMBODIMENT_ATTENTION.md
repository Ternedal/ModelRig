# C26-D — Semantic embodiment-change attention

Status: draft, event-admission only, `production_activation=false`.

C26-D connects evidence-bound semantic C8 embodiment inference to the existing
C18 pending-event queue.

It deliberately does **not** turn every renderer/body observation into cognition.

> **Body evidence may deserve attention. Sensor-frame churn does not.**

## Input authority

C26-D consumes:

- one exact `EmbodimentState`, normalized from BodyRig-performed state plus
  renderer/body observations;
- one exact `InferredEmbodimentState`, already required by C8 to retain
  observation provenance.

Before any event is created, C26-D requires exact agreement on:

```text
cycle_id
person_id
person_revision
body_revision
```

The inference's complete evidence-observation set must be contained in the exact
`EmbodimentState.observation_refs`.

An inference cannot cite evidence from another body state.

## Noise policy

Only semantic inference kinds that can materially change cognitive orientation
may create autonomous attention:

```text
action_outcome            -> salience 0.90
reachability              -> salience 0.90
locomotion_blocked        -> salience 1.00
interaction_result        -> salience 0.95
tracking_interpretation   -> salience 0.95
```

`gaze_state` creates no C18 event in C26-D.

This is intentional. Eye/gaze/frame telemetry can change at renderer frequency
and must not fill the bounded supervisor queue or spend autonomous cognition
budget merely because a sensor updated.

## Event

A qualifying inference creates one deterministic:

```text
kind = embodiment_change
observed_sequence = EmbodimentState.last_observed_sequence
```

The event source ref binds the exact canonical:

- `EmbodimentState` ref;
- `InferredEmbodimentState` ref.

The event id is then derived from that combined provenance.

The summary is explicitly marked as **inferred**, includes the inference kind
and confidence, and is hard-bounded to C18's 2048-character event-summary
limit.

Salience comes only from the fixed Core mapping above.

It is not selected by BodyRig, the renderer or the replaceable ThoughtEngine.

## Live-session binding

`ProductionCognitiveSession.submit_embodiment_inference()` additionally
requires:

```text
EmbodimentState.person_id == live SelfState.person_id
EmbodimentState.person_revision == live SelfState.person_revision
```

Only then may the optional event enter the existing C18 queue.

The admission result records supervisor revision before/after and explicitly
fixes:

```text
body_mutation_authority = false
model_calls = 0
execution_authority = false
scheduling_authority = false
durable_memory_write_authority = false
self_state_store_write_applied = false
production_activation = false
```

## Replay

The event id is deterministic from exact state + inference provenance.

Submitting the same exact semantic inference twice therefore reaches C18 with
the same event id and same event content.

Existing C18 exact-event admission makes the second submission idempotent:

```text
pending event count unchanged
supervisor revision unchanged
```

Conflicting reuse of an event id remains a C18 contract failure.

## C19 live-state boundary

C26-D does not modify:

- SelfState;
- RuntimeWorldState;
- CognitiveWorkspace;
- PersonalitySnapshot;
- completed-cycle count;
- response-guidance mailbox;
- BodyRig Motor State.

Only the C18 pending-event queue may change.

## C25 relationship

C25-A's default policy requires:

```text
embodiment_change_min_salience = 0.85
```

Every C26-D event-producing semantic kind is intentionally above that
threshold.

With C25-A/B/C separately enabled, free budget and no cooldown:

```text
BodyRig-performed state
-> C8 normalized EmbodimentState
-> evidence-bound semantic inference
-> C26-D embodiment_change event
-> C18 pending queue
-> existing scheduler cadence
-> C25-C
-> C25-B
-> C25-A eligibility/budget/cooldown
-> exact-event cognitive step
```

C26-D does not bypass anti-hitchhike, pacing or single-flight.

## Non-goals

C26-D does not:

- poll BodyRig;
- create renderer observers;
- issue body cues;
- mutate Motor State;
- create semantic inferences itself;
- run ThoughtEngine;
- write Memory 4;
- persist SelfState;
- create a scheduler/thread/timer;
- execute Agent 3 or tools.

It is a narrow evidence-to-attention boundary.

C26-D is the fourth authoritative non-user attention source after:

1. C26-A wake-followup;
2. C26-B prediction mismatch;
3. C26-C privacy-safe Memory 4 recall.
