# C18-B — Default-off production supervisor lifecycle seam

Status: draft, production-wired but inert by default, `production_activation=false`.

C18-B makes the C18-A event-driven supervisor available inside the documented
worker lifecycle without turning it into an autonomous process.

> **Lifecycle ownership is not cognition authority.**

## Activation contract

The production bridge exists only when **both** exact flags are set:

```text
KALIV_CONSCIOUSNESS_CORE_ENABLED=1
KALIV_CONSCIOUSNESS_SUPERVISOR_ENABLED=1
```

Any other value remains disabled.

The supervisor flag is intentionally read through a literal environment-key
reference so `scripts/current_state.py` discovers it and exposes the new
runtime power in generated `CURRENT_STATE.md`.

## Production placement

The documented worker entrypoint now composes:

```text
C18-B supervisor lifecycle
    C13 sleep lifecycle
        Memory 4 write lifecycle
            Memory 4 context lifecycle
                scheduler_lifespan
```

The wrapper preserves:

```text
production_lifespan.__wrapped__ is scheduler_lifespan
```

so the scheduler remains the process lifecycle authority owner.

C18-B adds no route and mounts no model-visible capability.

## In-process runtime surface

When enabled, startup attaches one bridge:

```python
app.state.consciousness_supervisor
```

The bridge is available only for existing trusted in-process code.

It exposes:

- `submit(CognitionEvent)`
- `plan()`
- `await step(...)`

No HTTP route, tool registration, websocket, SSE stream or remote control plane
is added.

## Explicit cognition only

Bridge construction performs zero ThoughtEngine calls.

`submit(...)` only changes bounded in-memory SupervisorState.

`plan()` samples the trusted process-local C11 clock and returns deterministic
`IDLE`, `WAIT` or `RUN`.

`step(...)` evaluates exactly one plan:

- `IDLE`: zero ThoughtEngine calls;
- `WAIT`: zero ThoughtEngine calls;
- `RUN`: exactly one C18-A supervisor cycle, therefore at most one C15
  ThoughtEngine invocation followed by one C16 reduction.

There is no retry and no automatic second step.

## Caller-owned cognitive snapshots

A RUN step requires the caller to provide exact current:

- PersistentSelfState;
- RuntimeWorldState;
- CognitiveWorkspace;
- PersonalitySnapshot;
- CognitiveProfile;
- optional relevant Memory 4 refs;
- optional embodiment-state ref.

C18-B does not fabricate or discover missing cognitive state.

The lower C18-A/C15/C16 contracts verify their canonical bindings before and
after cognition.

## Double opt-in provider boundary

The production factory evaluates activation in this order:

1. supervisor exact opt-in;
2. Core exact opt-in;
3. model runtime composition;
4. trusted runtime clock construction;
5. in-memory bridge bootstrap.

Therefore:

- supervisor OFF never composes the model runtime;
- supervisor ON + Core OFF still never composes the model runtime;
- only the exact double opt-in can resolve the production ThoughtEngine adapter.

This keeps normal worker startup behavior unchanged.

## Single-flight cognition

A production bridge allows only one in-flight `step()`.

While a ThoughtEngine call is awaited:

- another `step()` fails closed;
- synchronous `submit()` fails closed;
- `plan()` fails closed.

This avoids two dangerous races:

1. double-consuming the same pending event;
2. overwriting an event submitted while a previous cognitive transition was
   committing its next SupervisorState.

C18-B deliberately rejects the race instead of silently merging authority
surfaces.

## Shutdown

Lifecycle shutdown:

- marks the bridge closed;
- removes `app.state.consciousness_supervisor`;
- writes no SupervisorState;
- writes no SelfState;
- writes no Memory 4 data;
- runs no final cognition cycle.

The existing inner sleep lifecycle remains responsible for its separately
reviewed C13 shutdown boundary.

## Authority boundary

C18-B creates no:

```text
HTTP route
model-visible tool
thread
timer
polling loop
scheduler
automatic repeat
SelfStateStore write
Memory 4 write
Agent 3 execution
tool execution
BodyRig actuation
VoiceRig actuation
raw/private chain-of-thought persistence
```

All bridge and C18-A receipts retain:

```text
execution_authority=false
scheduling_authority=false
durable_memory_write_authority=false
production_activation=false
```

## What this unlocks

The production worker can now host the Consciousness Core supervisor safely:

```text
trusted in-process event source
        |
        v
ProductionSupervisorBridge.submit()
        |
        v
explicit caller chooses to step
        |
        v
C18-A pacing + event orientation
        |
        v
one C15 cognition
        |
        v
C16 next cognitive state
```

The next slice should not add a free-running loop. It can instead connect one
specific existing runtime event source—such as a completed user turn—to
`submit()` behind its own reviewed boundary, while preserving explicit
one-step cognition and zero external execution authority.
