# Consciousness Core C10 — consolidation and anti-drift

Status: stacked on C9. Deterministic candidate generation only. No production activation.

Issue: #1620.

## Purpose

C10 converts accumulated, provenance-bearing evidence into review candidates for
long-term self/world/personality/relationship changes.

It does not directly change those authorities.

The invariant is:

Experience may influence the self over time. No single model turn may redefine the self.

## Evidence rules

C10 distinguishes evidence by self + Person Revision binding, subject scope,
field/value, source kind, source reference, root lineage digest, confidence,
temporal scope and a stable-candidate marker.

Duplicate observations from the same lineage count once.

raw_chain_of_thought is rejected as consolidation authority.

thought_engine, transient and session state cannot independently produce a
long-term candidate.

Self-generated behaviour may support a candidate only when independent external
stable evidence agrees.

## Conflict policy

C10 does not hide contradictory evidence inside an opaque weighted average.

When independent long-term evidence proposes incompatible values and there is no
explicit correction authority, the resolver emits no candidate and preserves the
conflicting source refs.

An explicit user/operator correction may produce a review candidate from one
lineage, but it still has review_required=true, activation_authority=false,
durable_memory_write_authority=false and execution_authority=false.

## Candidate types

Initial C10 maps evidence into review-only candidates for SELF_MODEL_DELTA,
PERSONALITY_REVISION, RELATIONSHIP_MODEL and WORLD_MODEL_DELTA.

A PersonalityRevision candidate must still cross the existing Person/Profile
review and activation authority. C10 does not create another activation path.

## Model independence

Provider/model/CognitiveProfile identity is not an input to consolidation.

A model swap therefore cannot directly create a long-term identity/personality
revision. Only source evidence with stable provenance participates.

## Non-goals

C10 does not persist autobiographical memory, activate Person/Profile revisions,
change BodyRig/VoiceRig identity, execute Agent 3 actions, create tools or
confirmations, schedule background consolidation, persist raw private
chain-of-thought, or claim phenomenal consciousness.

production_activation=false.
