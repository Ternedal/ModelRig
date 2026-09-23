# Consciousness Core C5 — prediction and metacognition

Status: stacked implementation over C4. Default off. No route. No persistence.

Issue: #1615.

## Core rule

A ThoughtEngine may propose a predicted outcome. Consciousness Core owns the
prediction lifecycle, outcome binding, deterministic resolution and
metacognitive strategy state.

The model cannot mark a prediction resolved, write calibration history, or grant
itself execution authority.

## Flow

```text
ThoughtProposal.predicted_outcomes
  -> Core creates PredictionRecord(status=open)
  -> provenance-bearing OutcomeObservation
  -> deterministic PredictionResolution
  -> MetacognitiveState update
```

Resolution uses structured relation evidence, not a free-form model-authored
score.

## Provenance classes

Outcome observations remain explicitly typed:

- user_report
- tool_result
- embodiment
- core_observation
- inferred

A user report is therefore never silently rewritten as direct Core observation.

## Cognitive profile

The current transient CognitiveProfile may influence strategy such as:

- confidence ceiling
- verification requirement
- decomposition requirement
- capability limitation notes

Provider/model/engine identity is not persisted in MetacognitiveState.

A model swap may change current cognitive capacity without changing SelfState.

## Authority

C5 has no:

- Agent 3 executor
- tool calls
- Memory 4 writer
- Person/Profile mutation
- BodyRig mutation
- scheduler
- background loop
- durable store

A prediction mismatch can set `verification_required=true`; it cannot perform
the verification itself.

## Failure semantics

- invalid/non-finite confidence fails closed;
- only open predictions can resolve;
- outcome must bind the exact prediction;
- missing source provenance fails validation;
- unexpected observation class becomes indeterminate;
- contradictory evidence increases uncertainty and verification/decomposition.

## Non-goals

C5 does not implement affect, personality consolidation, durable memory,
persistent autonomous goals, or embodiment sensing.

`production_activation=false`.
