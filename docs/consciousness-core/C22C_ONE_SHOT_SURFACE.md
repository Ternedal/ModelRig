# C22-C — Private required-event one-shot cognition surface

Status: draft, independently default-off.

C22-C is the first production-facing Consciousness Core surface that may invoke
the replaceable ThoughtEngine.

It remains deliberately narrow:

> **The caller may name one already-pending event. The caller may not supply a
> model, prompt, profile, state, memory, tool or action.**

## Independent activation

Exact opt-in:

```text
KALIV_CONSCIOUSNESS_TURN_COGNITION_ENABLED=1
```

This is stronger than C21 chat admission and therefore has its own switch.

It does not replace the existing requirements for:

- Consciousness Core runtime;
- supervisor bridge;
- live cognitive session;
- strict production CognitiveProfile configuration.

The route can be mounted while those are unavailable, but execution then fails
closed without fabricating missing context.

## Surface

```text
POST /experimental/consciousness/step
```

Request:

```json
{
  "required_event_id": "cevt-..."
}
```

That is the complete caller-controlled cognitive input.

No caller-provided:

- model;
- provider;
- capacity score;
- prompt;
- SelfState;
- WorldState;
- Workspace;
- personality;
- Memory 4 content;
- tool definition;
- action.

Extra request fields are rejected.

## Network boundary

C22-C is loopback-only even when generic worker LAN access has been enabled.

Loopback admission happens before body parsing.

A remote caller cannot make this route parse a cognition-step body.

The request body is bounded to 4 KiB.

## Profile authority

The route resolves its CognitiveProfile locally through C22-B.

If the operator profile file is:

- absent;
- malformed;
- contradictory;
- unavailable;

the route returns a generic profile-unavailable response and performs zero model
calls.

The caller cannot override the profile through HTTP.

## Required-event binding

The route passes the exact event id to C22-A:

```text
session.step(
    profile=<strict local C22-B profile>,
    required_event_id=<caller named pending event>
)
```

C22-A verifies before model invocation that the event:

- has a valid id;
- is pending;
- is actually selected by the canonical supervisor RUN plan.

A missing or unselected required event returns a generic conflict.

No model call occurs.

## WAIT

A pending required event may be pacing-blocked.

C22-C then returns:

```text
decision=WAIT
thought_engine_invoked=false
model_calls=0
context_updated=false
transition_receipt_ref=null
```

The event remains pending.

There is no timer or automatic retry.

## RUN

A valid selected required event may produce one existing C18/C15/C16 cycle.

The receipt must then satisfy:

```text
decision=RUN
required event is among selected_event_ids
thought_engine_invoked=true
model_calls=1
context_updated=true
transition_receipt_ref != null
```

The route cannot authorize a second model call.

## Receipt privacy

C22-C deliberately does not return ThoughtProposal content.

It returns only bounded control-plane evidence:

- required event id;
- WAIT/RUN decision;
- selected event ids;
- whether the ThoughtEngine was invoked;
- model-call count;
- canonical profile/config refs;
- canonical SelfState/WorldState/Workspace refs;
- transition receipt ref after RUN;
- completed-cycle count;
- fixed authority-denial fields.

It does **not** return:

- interpretation;
- hypotheses;
- candidate intentions;
- predicted outcomes;
- questions;
- memory queries;
- response intent;
- body intent;
- raw provider output;
- provider error text.

Provider/ThoughtEngine failures become one generic 502 error.

## Receipt consistency

The strict receipt model prevents contradictory states.

For WAIT:

- no model call;
- no context update;
- no transition receipt.

For RUN:

- exactly one model call;
- one context update;
- one transition receipt;
- required event selected.

## Authority boundary

C22-C creates no:

```text
automatic trigger
background task
thread
timer
scheduler
retry
action execution
tool execution
SelfStateStore write
Memory 4 write
Agent 3 authority
BodyRig actuation
VoiceRig actuation
raw inner-monologue API
```

Every receipt retains:

```text
automatic_repeat=false
self_state_store_write_applied=false
durable_memory_write_authority=false
execution_authority=false
scheduling_authority=false
production_activation=false
```

## What this unlocks

The architecture can now perform a fully event-bound, profile-bound, one-shot
inner cognition:

```text
reported user turn
    |
    v
C21 exact cognition event id
    |
    v
C22-C private one-shot request
    |
    v
C22-B strict local profile
    |
    v
C22-A required-event binding
    |
    v
one C18 -> C15 -> C16 cycle
```

Normal chat still does **not** automatically call this surface.

Any C21-to-C22 automatic coupling remains a separate review because it changes
user-turn latency and causes a model invocation on every eligible turn.
