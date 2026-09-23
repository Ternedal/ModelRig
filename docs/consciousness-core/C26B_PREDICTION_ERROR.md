# C26-B — Prediction-mismatch attention admission

Status: draft, event-admission only, `production_activation=false`.

C26-B connects the existing C5 prediction-resolution contract to the C18 pending
event queue.

It does not let the ThoughtEngine decide whether its own prediction was wrong.

> **Structured evidence resolves the prediction. Only an exact mismatch becomes autonomous attention.**

## Input authority

C26-B starts from two existing C5 contracts:

- `PredictionRecord`: one Core-owned OPEN prediction created from a bounded
  ThoughtProposal outcome;
- `OutcomeObservation`: structured evidence bound to that exact prediction,
  with explicit provenance, observation kind, relation and observed sequence.

C5 `resolve_prediction()` remains the only resolution rule used by C26-B.

The replaceable model does not supply:

- result;
- error score;
- confidence delta;
- event salience;
- event id;
- autonomous authority.

## Resolution

C5 deterministically maps structured relation evidence to:

```text
supports            -> match
partially_supports  -> partial
contradicts         -> mismatch
unknown             -> indeterminate
```

C26-B only creates a CognitionEvent when:

```text
result == mismatch
error_score == 1.0
```

Everything else returns a valid non-event plan.

## Event

An exact mismatch creates one:

```text
kind = prediction_error
salience = 1.0
observed_sequence = OutcomeObservation.observed_sequence
```

The source ref is a canonical SHA-256 digest over both the exact
`PredictionResolution` and exact `OutcomeObservation`.

The event id is deterministically derived from that combined provenance ref.

This means the event is bound to the concrete structured evidence, not merely a
prediction id or free-form model statement.

## Plan before side effect

C26-B separates pure resolution from queue admission.

```text
PredictionRecord + OutcomeObservation
-> PredictionOutcomePlan
-> optional CognitionEvent
```

The plan cannot claim queue admission.

Only `ProductionCognitiveSession.submit_prediction_outcome()` may then submit
the event to the existing C18 bridge.

The returned `PredictionOutcomeAdmissionResult` records supervisor revision
before and after admission.

For a new mismatch:

```text
revision_after = revision_before + 1
```

For exact duplicate mismatch replay:

```text
revision_after = revision_before
```

because C18 exact-event admission is idempotent.

For match/partial/indeterminate:

```text
revision_after = revision_before
cognition_event_admitted = false
```

## Live cognitive state

Prediction-outcome admission does not modify C19 live:

- SelfState;
- WorldState;
- CognitiveWorkspace;
- PersonalitySnapshot;
- completed cycle count;
- response-guidance mailbox.

Only the C18 pending-event queue may change.

## C25 relationship

The default C25-A policy already recognizes:

```text
prediction_error_min_salience = 0.75
```

C26-B exact mismatches use salience `1.0`.

Therefore, with C25-A/B/C separately enabled and free budget/cooldown:

```text
structured contradictory evidence
-> C5 mismatch
-> C26-B prediction_error event
-> C18 pending queue
-> existing scheduler cadence
-> C25-C
-> C25-B
-> C25-A eligible
-> exact-event cognitive step
```

C26-B does not bypass the C25 budget, cooldown, anti-hitchhike, supervisor
pacing or single-flight boundaries.

## Failure behavior

Admission fails closed when:

- prediction or outcome contract is invalid;
- prediction is not open;
- outcome belongs to another prediction;
- structured bindings disagree;
- C18 rejects queue admission.

A failure before C18 admission leaves the pending queue unchanged.

## Authority boundary

C26-B adds no:

- model call;
- scheduler;
- timer;
- thread;
- polling loop;
- retry;
- durable SelfState write;
- Memory 4 mutation;
- Agent 3/tool execution;
- BodyRig actuation;
- VoiceRig actuation.

All receipts and events remain:

```text
production_activation=false
```

C26-B is the second authoritative non-user event source after C26-A
wake-followup.
