# C19-A — Authoritative runtime session bootstrap

Status: draft, Core-only, `production_activation=false`.

C19-A closes a subtle continuity gap in the Consciousness Core architecture.

PersistentSelfState is durable. RuntimeWorldState and CognitiveWorkspace are
not. After a process restart, the durable SelfState may still contain the
canonical refs of the last transient world/workspace, but those refs are not
proof that the old runtime objects still exist.

> **Continuity of self is durable. Continuity of transient context must be
> re-established honestly.**

## Input authority

C19-A accepts:

- one PersistentSelfState;
- one strict ActivePersonBindingSnapshot projected from the active approved
  Person Revision;
- one trusted bootstrap source ref;
- optionally one verified WakeReceipt.

The active Person binding must match the durable SelfState exactly on:

- person_id;
- Person Revision.

A WakeReceipt, when present, must match:

- self_id;
- Person Revision;
- `cognition_during_gap=false`.

Any mismatch fails closed.

## Active Person projection

`active_person_binding_from_registry(...)` projects the existing
`PersonRegistry.active_bindings()` result into a strict Core snapshot:

- person_id;
- Person Revision;
- body revision + BodyRig source ref;
- voice revision + VoiceRig source ref;
- personality revision;
- registry provenance.

C19-A does not activate or mutate any Person/Profile component.

It derives the C15 `PersonalitySnapshot` using:

- the exact active Person Revision;
- the exact active personality revision;
- the durable SelfState `personality_state_ref`;
- Person Registry / body / voice provenance refs.

## Fresh runtime world

C19-A creates a new RuntimeWorldState revision 1.

Its first observed fact states that a fresh runtime session has started and
that the previous transient WorldState and CognitiveWorkspace were **not**
restored.

A second observed fact records that the active Person Revision was verified
against the durable SelfState.

When a WakeReceipt exists, a third observed fact records only bounded,
receipt-backed sleep/dormancy information:

- planned sleep or unplanned dormancy;
- known or unknown offline duration;
- explicit absence of cognition during the gap.

No offline thoughts, actions or memories are invented.

## Fresh workspace

The new bounded workspace may contain:

- runtime-start perception;
- wake continuity perception;
- durable active goal refs;
- durable active intention refs as context only;
- last accepted experience ref.

These are references and bounded summaries.

C19-A never materializes the prior transient world/workspace from their old
refs.

The old refs appear only in SessionBootstrapReceipt provenance.

## SelfState transition

C19-A advances SelfState by exactly one revision.

It changes only:

- `world_state_ref`;
- `workspace_ref`;
- mandatory `revision`.

It explicitly verifies that these remain unchanged:

- self_id;
- person_id;
- Person Revision;
- personality_state_ref;
- active goal refs;
- active intention refs;
- affect;
- durable uncertainties;
- last experience ref.

No SelfStateStore write occurs.

## Receipt semantics

The SessionBootstrapReceipt fixes:

```text
prior_world_restored=false
prior_workspace_restored=false
identity_unchanged=true
active_goal_bindings_unchanged=true
active_intention_bindings_unchanged=true
affect_unchanged=true
durable_uncertainties_unchanged=true
last_experience_binding_unchanged=true
model_calls=0
self_state_store_write_applied=false
durable_memory_write_authority=false
execution_authority=false
scheduling_authority=false
production_activation=false
```

For wake bootstrap it additionally fixes:

```text
cognition_during_gap=false
```

## Determinism

Given the same exact:

- PersistentSelfState;
- ActivePersonBindingSnapshot;
- bootstrap source ref;
- optional WakeReceipt;
- max_active value;

C19-A produces the same:

- world id;
- observation ids;
- cycle id;
- workspace candidate ids;
- canonical refs;
- next SelfState;
- receipt.

## What this unlocks

A production runtime can now truthfully establish a live cognitive session after
startup:

```text
durable identity state
        +
active approved Person
        +
optional wake evidence
        |
        v
fresh live WorldState + Workspace
        |
        v
same self, new runtime context
```

The next slice can make this context an in-process session owner for C18-B, so
trusted event sources no longer need to construct Self/World/Workspace/
Personality snapshots themselves.
