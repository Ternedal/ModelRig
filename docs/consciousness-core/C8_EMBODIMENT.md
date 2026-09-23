# Consciousness Core C8-A — embodiment observation contracts and mock loop

Status: first C8 slice. Contracts + deterministic mock only. No BodyRig network integration. No production activation.

Issue: #1618.

## Core rule

Consciousness Core may observe embodiment state.

BodyRig remains authoritative for body identity, BodyPrint, Movement Identity and
performed Motor State.

C8-A keeps four states explicitly separate:

```text
SemanticBodyIntent
  -> PerformedBodyStateRef
  -> EmbodimentObservation
  -> EmbodimentState
  -> optional InferredEmbodimentState
```

## Semantic intent

`SemanticBodyIntent` contains only high-level semantics such as affect labels,
intent and expressive intensity.

It has no joint angles, gait phase, blendshape weights, eyebrow percentages,
head-angle commands or other renderer-level controls.

## Performed state

`PerformedBodyStateRef` is only a reference to BodyRig-owned performed state.

It binds:

- cognitive cycle;
- person id;
- Person Revision;
- body revision;
- body id;
- BodyCue ref;
- Motor State ref;
- Motor State sequence;
- BodyRig source receipt.

Consciousness Core does not create or mutate the performed Motor State.

## Raw observation

`EmbodimentObservation` is renderer/runtime evidence.

It carries:

- exact cycle/person/body/Motor State binding;
- renderer ref;
- observation kind;
- coordinate-space marker;
- bounded raw scalar values;
- confidence;
- source refs;
- observation sequence.

It cannot contain BodyPrint, Movement Identity or personality mutation authority.

## Normalization

`normalize_embodiment_state()` fails closed on:

- wrong cognitive cycle;
- wrong person;
- wrong Person Revision;
- wrong body revision;
- wrong Motor State;
- stale observation sequence;
- duplicate observation id;
- duplicate sequence.

Tracking health is derived from observations as:

- unavailable — no observations;
- lost — explicit tracking observation says lost;
- degraded — bounded confidence below 0.5;
- ok — otherwise.

No fake current body state is invented when observations are missing.

## Inference

`InferredEmbodimentState` is a separate contract.

An inference must cite at least one raw observation and can never masquerade as
renderer evidence.

This preserves distinctions such as:

- I intended an action;
- BodyRig performed Motor State X;
- renderer observed Y;
- Consciousness Core inferred Z.

## C8-A mock

`MockEmbodimentObserver` gives deterministic contract coverage without importing
or mutating BodyRig or a renderer.

It validates exact cycle/person binding and emits a bounded tracking observation
bound to the supplied performed Motor State.

The mock carries only the semantic intent id into observation evidence, not raw
semantic text.

## Non-goals

C8-A does not:

- call BodyRig;
- mount a route;
- issue BodyCue;
- mutate Motor State;
- connect Kaliv-VR;
- ingest real tracking;
- close the C5 prediction loop;
- change personality;
- persist embodiment;
- create actions/tools;
- activate production.

Those belong to later C8 sub-slices.

`production_activation=false`.
