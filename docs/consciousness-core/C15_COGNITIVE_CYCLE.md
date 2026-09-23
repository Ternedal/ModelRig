# C15 — Authoritative cognitive cycle / inner-monologue boundary

Status: draft, isolated, `production_activation=false`.

C15 turns the earlier state and ThoughtEngine contracts into one bounded cognitive
cycle. It deliberately keeps the architectural split:

> **Kaliv owns continuity. The model supplies cognition.**

The ThoughtEngine is therefore an external, replaceable inner-monologue engine,
not SelfState, identity, durable memory, a scheduler, or an executor.

## Cycle

```text
PersistentSelfState
  + exact WorldState
  + bounded CognitiveWorkspace
  + PersonalitySnapshot
  + selected Memory 4 refs
  + optional EmbodimentState ref
  + ephemeral CognitiveProfile
        |
        v
authoritative binding + canonical refs
        |
        v
ThoughtRequest
        |
        +---- bounded materialized CognitiveContextPacket ----+
        |                                                     |
        v                                                     v
             replaceable external ThoughtEngine / LLM
                              |
                              v
                       ThoughtProposal
                              |
                              v
                 immutable CognitiveCycleReceipt
```

The reference-only ThoughtRequest remains the auditable contract. The ephemeral
ContextPacket solves a separate runtime problem: the external model needs the
bounded materialized state it is supposed to reason about, not only opaque hashes.

## Authority

The context packet may expose information for cognition. Exposure is not authority.

The ThoughtEngine still cannot:

- activate or rebind a Person Revision;
- mutate or persist SelfState;
- mutate WorldState or the active workspace;
- write Memory 4;
- call tools or Agent 3;
- schedule work;
- actuate BodyRig or VoiceRig;
- claim that a candidate intention was executed.

`ThoughtProposal.actions` and `state_mutations` remain schema-bound empty arrays,
and all proposal authority bits remain false.

## Workspace / attention

C15 implements the C2 workspace contract at runtime.

Candidate attention is deterministic:

1. descending salience;
2. stable `candidate_id` tie-break;
3. at most `max_active`, where 1 <= max_active <= 16.

The complete candidate set is bounded to 256 entries. Selection changes what is
shown as active cognitive material; it does not execute anything.

## Exact state binding

Before the model is called, C15 verifies:

- `SelfState.world_state_ref` is the canonical hash of the exact WorldState;
- `SelfState.workspace_ref` is the canonical hash of the exact workspace;
- `SelfState.personality_state_ref` matches the PersonalitySnapshot;
- the PersonalitySnapshot belongs to the exact active Person Revision;
- the CognitiveProfile is canonical-hash bound into the ThoughtRequest;
- memory refs are bounded and deduplicated;
- the workspace belongs to the request's exact cycle.

A mismatched object fails closed before cognition.

## Model swap

Provider/model identity exists only in `CognitiveProfile`.

Changing the model may therefore change:

- interpretation;
- hypotheses;
- candidate intentions;
- predictions;
- questions;
- response/body intent;
- uncertainty.

It does not change:

- `self_id`;
- `person_id`;
- `person_revision`;
- durable personality authority;
- durable memory authority.

The CycleReceipt records the exact self/person binding before and after cognition
and requires `self_state_unchanged=true`.

## Chain-of-thought boundary

C15 does not persist a raw/private model reasoning trace. The engine is instructed
to return only the bounded structured ThoughtProposal fields. The receipt records:

```text
raw_chain_of_thought_persisted=false
model_state_mutation_applied=false
execution_authority=false
scheduling_authority=false
durable_memory_write_authority=false
production_activation=false
```

The `interpretation`, hypotheses and predictions are bounded product-level
outputs, not a stored hidden reasoning transcript.

## Still missing after C15

C15 deliberately runs one cycle only. Later slices may add separately reviewed:

- Core-owned state transitions after a proposal;
- Memory 4 materialized recall content rather than refs only;
- prediction-resolution feedback into the next cycle;
- body/voice observation refresh;
- a wake-to-first-cycle transition;
- an event-driven continuous cognition supervisor.

None of those are authorized by C15.
