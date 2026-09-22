# C16 — Cognitive executive / proposal adjudication

Status: draft, isolated, `production_activation=false`.

C16 places a deterministic Core-owned executive between the external
ThoughtEngine and every downstream cognitive/action boundary.

The architectural rule is:

> **The model proposes. The Core adjudicates. Existing authorities execute.**

## Flow

```text
C15 CognitiveCycleResult
  + exact CognitiveWorkspace
  + C5 MetacognitiveState
  + optional exact C9 active GoalRecord
  + model-independent ExecutivePolicy
        |
        v
      C16 Executive
        |
        +--> ACCEPT_COGNITION
        +--> VERIFY
        +--> REQUERY
        +--> DECOMPOSE
        +--> HOLD
        |
        v
bounded candidates + immutable AdjudicationReceipt
```

No branch of this flow directly calls Agent 3, Memory 4, BodyRig, VoiceRig,
a scheduler, a tool, or a persistence writer.

## Deterministic policy

The default v1 policy is explicit data, not model behavior:

- proposal uncertainty >= 0.85 -> `HOLD`;
- proposal uncertainty >= 0.45 -> `VERIFY`;
- Core task uncertainty >= 0.60 -> `VERIFY`;
- `MetacognitiveState.decomposition_required=true` -> `DECOMPOSE`;
- `MetacognitiveState.verification_required=true` -> `VERIFY`;
- empty bounded cognitive output -> `REQUERY`;
- attention suggestions outside the exact bound workspace -> `HOLD`;
- otherwise -> `ACCEPT_COGNITION`.

Explicit Core metacognitive decomposition/verification takes precedence over
ordinary model uncertainty thresholds.

The policy itself is canonical-hash referenced in the receipt. Changing the
model/provider does not change executive policy.

## Confidence ceiling

Model confidence is input evidence, not authority.

For hypotheses, intentions and predictions that survive adjudication:

```text
effective_confidence = min(model_confidence, Core confidence_ceiling)
```

The receipt records how many candidate confidences were clipped.

This means replacing a weak model with a stronger one can improve the quality of
proposals, but the model cannot simply declare confidence above the Core's current
metacognitive ceiling.

## Decision semantics

### ACCEPT_COGNITION

May emit bounded:

- hypothesis candidates;
- intention candidates;
- PredictionRecord candidates;
- Memory 4 read-query candidates;
- semantic response intent;
- semantic body intent;
- valid attention references already present in the C15 workspace.

Even here, an intention candidate is explicitly:

```text
selected=false
dispatched=false
execution_authority=false
```

Semantic response/body intent has `dispatch_authority=false`.

Memory queries have `read_requested=false` and
`durable_write_authority=false`.

### VERIFY

May preserve:

- hypotheses;
- predictions;
- optionally Memory 4 read-query candidates.

It emits **no intention candidates** and **no response/body semantic intents**.
Unverified cognition therefore cannot accidentally flow toward execution or
embodied output.

### DECOMPOSE / REQUERY / HOLD

Emit no downstream cognitive/action candidates.

They are control decisions for a later cognitive supervisor, not scheduler or
execution instructions.

## Workspace integrity

A ThoughtProposal may suggest attention only to candidate IDs that already exist
in the exact C15 workspace bound into the cycle receipt.

An out-of-workspace attention reference is not silently accepted, invented, or
looked up. The executive returns `HOLD` and records the rejected reference.

## Goal binding

C16 may optionally bind downstream intention candidates to one existing C9 active
GoalRecord.

That goal must:

- have status `active`;
- belong to the exact same `self_id`;
- belong to the exact same Person Revision.

C16 does not activate, transition, complete, select, dispatch, or execute the
goal/intention. Existing C9 admission and execution boundaries remain intact.

## Prediction boundary

Accepted/verification-worthy predicted outcomes may be transformed using the
existing C5 `prediction_from_proposal` function.

They become Core-owned OPEN PredictionRecord candidates with exact proposal,
workspace and cycle provenance. Their confidence is still capped by the Core
metacognitive ceiling.

No prediction is treated as an observed outcome.

## Receipt authority

Every adjudication emits an immutable receipt that binds:

- cycle/request;
- proposal hash;
- workspace hash;
- MetacognitiveState hash;
- ExecutivePolicy hash;
- optional active goal ref;
- decision and reason;
- accepted/rejected attention refs;
- confidence ceiling/clipping;
- downstream candidate counts.

It also pins:

```text
self_state_mutation_applied=false
execution_authority=false
scheduling_authority=false
durable_memory_write_authority=false
body_actuation_authority=false
voice_actuation_authority=false
production_activation=false
```

## What C16 still does not do

C16 does not yet run another thought cycle after `VERIFY`, `REQUERY` or
`DECOMPOSE`. It only determines the next cognitive control state.

A later supervisor slice may consume those decisions and run another bounded
cycle, but that must remain event-driven, interruptible and separately reviewed.
