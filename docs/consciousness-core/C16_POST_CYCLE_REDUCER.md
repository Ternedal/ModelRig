# C16 — Deterministic post-cycle reducer and next-state continuity

Status: draft, isolated, `production_activation=false`.

C16 connects a verified C15 cognitive cycle to the next in-memory cognitive
moment without granting the replaceable ThoughtEngine persistent-state authority.

> **The model may propose. Core owns the transition.**

## Flow

```text
C15 CognitiveCycleResult
+ exact PersistentSelfState
+ exact CognitiveWorkspace
        |
        v
exact request / proposal / receipt binding checks
        |
        v
bounded Core-owned reducer policy
        |
        +-- carry at most 31 prior candidates
        +-- accept attention suggestions only for known candidate/source refs
        +-- apply fixed +0.05 attention boost
        +-- add one bounded thought_result candidate
        +-- deterministic eviction + stable salience ordering
        |
        v
next CognitiveWorkspace
        |
        v
advance_self_state(workspace_ref=...)
        |
        v
CognitiveTransitionReceipt
```

## SelfState authority

C16 changes exactly two SelfState values:

- `revision` increments by one;
- `workspace_ref` points to the new bounded workspace.

The reducer explicitly verifies that these remain unchanged:

- `self_id`;
- `person_id`;
- `person_revision`;
- `personality_state_ref`;
- `world_state_ref`;
- active goal refs;
- active intention refs;
- affect;
- known durable uncertainties;
- `last_experience_ref`.

C16 does **not** call `SelfStateStore.write_next`. Durable persistence remains a
separate authority decision.

## Attention suggestions

A ThoughtProposal may suggest attention. The suggestion is not accepted as a new
fact or new workspace object.

C16 only recognizes a suggestion when it exactly matches an already-known:

- workspace `candidate_id`; or
- candidate `source_ref`.

Unknown refs are ignored. Known targets receive a fixed Core-owned +0.05 salience
boost capped at 1.0.

The model therefore influences attention within a bounded policy surface but
cannot invent authoritative context.

## Thought continuity

One `thought_result` candidate is added to the next workspace.

Its source is the canonical C15 ThoughtProposal ref. Its summary is the bounded
structured `interpretation` field, not a raw/private reasoning trace.

Its salience is mapped by Core policy into the narrow range 0.60–0.90 from the
proposal's declared uncertainty. This makes uncertainty cognitively visible
without granting durable-state authority.

## Deterministic bounds

- at most 31 previous candidates are carried;
- exactly one new thought-result candidate may be added;
- max active attention remains inherited from the previous workspace;
- carry ordering is descending salience then stable candidate id;
- next cycle id and thought candidate id are deterministic hashes of the
  previous cycle + canonical proposal ref.

This prevents unbounded workspace growth across repeated cycles.

## Authority boundaries

The transition receipt fixes:

```text
model_state_mutation_applied=false
self_state_store_write_applied=false
durable_memory_write_authority=false
execution_authority=false
scheduling_authority=false
raw_chain_of_thought_persisted=false
production_activation=false
```

C16 does not:

- write Memory 4;
- admit or complete goals;
- dispatch Agent 3;
- actuate BodyRig or VoiceRig;
- create a scheduler or continuous cognition loop;
- mount a public route;
- activate production behavior.

## What this unlocks

C15 + C16 now form a safe two-step primitive:

```text
bounded cognition -> deterministic next cognitive state
```

The next slice can build a wake-to-first-cycle bridge or a separately reviewed
event-driven cognition supervisor on top of this primitive without giving the
LLM ownership of identity or durable state.
