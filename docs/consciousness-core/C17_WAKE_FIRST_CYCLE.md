# C17 — Wake reorientation and first cognitive cycle

Status: draft, isolated, `production_activation=false`.

C17 connects the persisted sleep/wake boundary to the cognitive-cycle machinery
without pretending that cognition continued while the process was off.

> **Wake restores orientation. It does not resume execution.**

## Flow

```text
WakeReceipt
+ exact PersistentSelfState
+ exact current CognitiveWorkspace
        |
        v
identity + Person Revision verification
        |
        v
deterministic wake-orientation workspace
        |
        v
advance_self_state(workspace_ref=...)
        |
        v
exactly one C15 cognitive cycle
        |
        v
C16 post-cycle reducer
        |
        v
next in-memory cognitive state
```

## Temporal continuity

C12 already guarantees:

```text
continuity_preserved=true
cognition_during_gap=false
wake_state=WAKING
```

C17 preserves that distinction.

The powered-off interval may be temporally measured, but no thoughts, memories,
actions, body movement or tool execution are invented inside the gap.

The wake-orientation workspace receives one high-salience wake candidate whose
summary contains only bounded product-level facts:

- planned sleep vs unplanned dormancy;
- known or unknown offline duration;
- explicit statement that cognition during the gap was false.

The candidate source is the canonical SHA-256-bound WakeReceipt reference.

## Open work carried across sleep

WakeReceipt may contain:

- `resume_goal_refs`;
- `resume_open_loop_refs`;
- `pending_review_refs`.

C17 exposes at most 16 refs from each class as bounded workspace candidates.

This is **reference continuity only**.

It does not:

- activate a goal;
- select an intention;
- mark a goal complete;
- execute an open loop;
- approve a pending review;
- call Agent 3 or a tool.

The pre-wake SelfState goal and intention bindings remain byte-for-byte unchanged
through orientation.

## In-memory state transition

Wake orientation increments SelfState revision by one and changes only
`workspace_ref`.

It explicitly verifies that all of the following stay unchanged:

- `self_id`;
- `person_id`;
- `person_revision`;
- personality binding;
- world binding;
- active goal refs;
- active intention refs;
- affect;
- known durable uncertainties;
- last experience ref.

No `SelfStateStore.write_next` occurs.

## First cognitive cycle

After orientation, C17 invokes C15 exactly once with reasoning mode `verify`.

That model call receives the bounded wake context through the normal C15
workspace/context packet. The model remains replaceable cognition, not identity
or state authority.

The result is immediately passed through C16, which produces the next bounded
workspace and the second in-memory SelfState revision.

For an initial revision N:

```text
pre-wake                  N
wake orientation          N + 1
first post-wake cognition N + 2
```

## Fail-closed bindings

Before any model call, C17 requires:

- WakeReceipt `self_id` == current SelfState `self_id`;
- WakeReceipt Person Revision == current SelfState Person Revision;
- current SelfState `workspace_ref` == canonical current workspace ref;
- `cognition_during_gap=false`.

A mismatch fails before ThoughtEngine invocation.

C15 and C16 then independently re-verify their own request, proposal, receipt,
state and workspace bindings.

## Authority boundaries

The C17 receipts fix:

```text
thought_engine_calls=1
cognition_during_gap=false
automatic_goal_resume=false
automatic_loop_resume=false
self_state_store_write_applied=false
durable_memory_write_authority=false
execution_authority=false
scheduling_authority=false
raw_chain_of_thought_persisted=false
production_activation=false
```

C17 adds no:

- scheduler;
- background cognition loop;
- public route;
- Memory 4 write;
- Agent 3 execution;
- BodyRig or VoiceRig actuation;
- production activation.

## What this unlocks

C12/C13 + C17 + C15/C16 now provide a complete bounded lifecycle primitive:

```text
awake
-> sleep boundary
-> powered-off continuity gap
-> wake reorientation
-> one verified cognitive cycle
-> next cognitive state
```

A later slice may introduce an event-driven cognition supervisor, but only as a
separately reviewed authority with explicit pacing, stop conditions and no hidden
background autonomy.
