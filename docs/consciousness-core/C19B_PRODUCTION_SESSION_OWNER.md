# C19-B — Production in-memory cognitive session owner

Status: draft, default-off through the existing C18-B double opt-in,
`production_activation=false`.

C19-B gives the production worker one authoritative live cognitive session for
the current process.

It does **not** make the model authoritative. The external model remains a
replaceable `CognitiveProfile` supplied per explicit step.

> **The session owns continuity context. The model supplies cognition.**

## Production lifecycle

The documented production composition becomes:

```text
C19-B cognitive session lifecycle
    C18-B supervisor lifecycle
        C13 sleep lifecycle
            Memory 4 write lifecycle
                Memory 4 context lifecycle
                    scheduler_lifespan
```

Every wrapper preserves the underlying scheduler as the lifecycle authority
owner.

C19-B adds no HTTP route.

## Startup

C19-B only attempts to build a session when
`app.state.consciousness_supervisor` already exists.

That means C18-B has already required the exact double opt-in:

```text
KALIV_CONSCIOUSNESS_CORE_ENABLED=1
KALIV_CONSCIOUSNESS_SUPERVISOR_ENABLED=1
```

If the supervisor bridge does not exist, C19-B returns before touching
SelfState or Person persistence.

When the bridge exists, C19-B reads:

1. the persisted SelfState;
2. the selected active approved Person Revision;
3. the optional C13 WakeReceipt already present on app.state.

If SelfState or active Person is missing, no live session is mounted.

No identity is fabricated.

## Runtime bootstrap

The exact sources are passed to C19-A.

C19-A produces:

- fresh RuntimeWorldState;
- fresh CognitiveWorkspace;
- exact PersonalitySnapshot;
- next in-memory SelfState;
- SessionBootstrapReceipt proving old transient world/workspace were not
  restored.

C19-B then converts that bootstrap result into
`LiveCognitiveSessionState`.

## Live session state

The session owns:

- current PersistentSelfState;
- current RuntimeWorldState;
- current CognitiveWorkspace;
- current exact PersonalitySnapshot;
- canonical bootstrap receipt ref;
- count of completed cognitive cycles;
- last C16 transition receipt ref.

The live-state validator requires:

```text
SelfState.world_state_ref == canonical live WorldState ref
SelfState.workspace_ref   == canonical live Workspace ref
SelfState.person_revision == PersonalitySnapshot.person_revision
SelfState.personality_state_ref == PersonalitySnapshot.personality_state_ref
```

A mismatched context cannot become the live session.

## Caller surface

Trusted in-process callers use:

```python
session.submit(event)
session.plan()
await session.step(profile=...)
```

Callers no longer provide:

- SelfState;
- WorldState;
- Workspace;
- PersonalitySnapshot.

Those belong to the session owner.

The caller still supplies a transient CognitiveProfile.

That is deliberate: replacing the ThoughtEngine/model changes cognitive
capacity, not identity.

## One step

`step(profile=...)` delegates to C18-B using the session-owned live context.

### IDLE / WAIT

No cognitive cycle occurs.

The live context remains exactly unchanged.

### RUN

C18-B/C18-A run exactly one C15 cycle followed by C16 reduction.

C19-B adopts only the already-verified C16 outputs:

- next SelfState;
- next Workspace.

It keeps:

- current WorldState unchanged;
- current PersonalitySnapshot unchanged.

Before adoption it verifies that the C16 transition did not change:

- world binding;
- Person Revision;
- personality-state binding.

A violation fails closed.

## Model swap semantics

A later step may use another CognitiveProfile/model.

The session identity remains:

- same self_id;
- same person_id;
- same Person Revision.

No model/provider identity enters durable SelfState.

This preserves the architectural rule:

> a stronger or weaker LLM feels like a cognitive upgrade/downgrade, not a
> different person.

## Durability

C19-B is still intentionally in-memory.

After RUN:

- SelfStateStore is **not** written;
- Memory 4 is **not** written;
- WorldState is **not** persisted;
- Workspace is **not** persisted.

The durable SelfState therefore remains the last separately authorized durable
revision.

Future persistence must be a separately reviewed authority boundary.

## Shutdown

C19-B closes and removes:

```text
app.state.consciousness_session
```

It performs:

- no final model call;
- no implicit state flush;
- no Memory 4 write;
- no SelfState write.

The inner C18-B and C13 lifecycles then perform their own separately reviewed
shutdown behavior.

## Authority boundary

C19-B adds no:

```text
HTTP route
model-visible capability
thread
timer
polling loop
scheduler
automatic cognition
automatic action
SelfStateStore write
Memory 4 write
Agent 3 execution
tool execution
BodyRig actuation
VoiceRig actuation
```

Every session step reports:

```text
self_state_store_write_applied=false
durable_memory_write_authority=false
execution_authority=false
scheduling_authority=false
production_activation=false
```

## What this unlocks

The production-side cognitive path is now:

```text
durable Self + active Person
        |
        v
C19-A fresh runtime bootstrap
        |
        v
C19-B live cognitive session
        |
        +---- submit(event)
        |
        v
C18-B explicit step
        |
        v
C18-A event supervisor
        |
        v
C15 ThoughtEngine
        |
        v
C16 next cognitive state
        |
        v
C19-B adopts next live state
```

The next useful slice can update RuntimeWorldState from verified runtime events,
so world-change events become durable-within-session epistemic state instead of
workspace-only context.
