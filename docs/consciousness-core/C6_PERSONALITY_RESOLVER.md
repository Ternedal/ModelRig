# Consciousness Core C6 — multi-source Personality Resolver

Status: stacked implementation over C5. No activation authority. No production activation.

Issue: #1616.

## Core rule

Personality is multi-source, but source domains remain explicit.

```text
Person/Profile reviewed semantic traits
BodyRig observable mannerisms
VoiceRig observable delivery traits
approved transcript style
interaction history
behavioural evidence
operator-authored evidence
        |
        v
Personality Resolver
        |
        +-> PersonalityModel
        +-> transient PersonalityState
```

The resolver cannot create or activate a ModelRig PersonalityRevision or Person
Revision.

## Source/domain boundary

C6 enforces the following fail-closed mapping:

- `BODYRIG_MANNERISM` -> `embodied` traits only;
- `VOICERIG_DELIVERY` -> `vocal` traits only;
- `PERSON_REVISION`, approved transcript style, interaction history,
  behavioural evidence and operator-authored evidence -> `semantic` traits only.

This directly preserves BodyRig's existing rule: observable body/video mannerisms
may ground movement/gesture/head/gaze/speech-motion traits, but body/video is not
authority for communication personality or psychological/value traits.

BodyRig mannerism evidence additionally requires an immutable source digest.

Approved transcript style requires both immutable digest and approval reference.

## Identity, model and state

### PersonalityIdentitySnapshot

Read-only snapshot of the reviewed active semantic personality binding.

The resolver never mutates this object.

### PersonalityModel

Deterministic aggregate of the identity baseline and evidence.

Every resolved trait retains:
- evidence ids;
- source kinds;
- lineage refs;
- confidence;
- identity baseline where present;
- whether it has an authoritative semantic source that could make it eligible for
  a future reviewed revision candidate.

`promotion_eligible=true` is **not activation authority**.

### PersonalityState

Transient manifestation produced by bounded modifiers.

A modifier can shift a current trait value, but it does not change the
PersonalityModel or PersonalityIdentitySnapshot.

## Anti-drift

Evidence with the same `trait_domain + trait_id + lineage_ref` counts once.

An exact duplicate lineage is deduplicated.

A conflicting copy with the same lineage fails closed rather than being counted
as independent support.

Behavioural evidence alone cannot make a semantic trait eligible for stable
identity promotion.

The current ThoughtEngine/provider/model is not an input to personality
resolution.

## Authority boundaries

C6 has no:

- PersonRegistry mutation;
- personality/person activation;
- Memory 4 write;
- Agent 3 call;
- tool execution;
- BodyRig mutation;
- VoiceRig mutation;
- scheduler/background loop;
- durable store.

A later consolidation slice may turn sufficient evidence into a **candidate**
revision. Existing review/Person Revision authority remains the only activation
path.

`production_activation=false`.
