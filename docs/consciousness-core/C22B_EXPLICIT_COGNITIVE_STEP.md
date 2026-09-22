# C22-B — Explicit loopback single cognitive step

Status: draft, independently default-off, `production_activation=false`.

C22-B is the first production boundary that can explicitly ask the already-live
Consciousness Core session to advance cognition.

It is deliberately not automatic.

> **One request may evaluate one supervisor step. Nothing repeats by itself.**

## Independent activation

The route is absent unless:

```text
KALIV_CONSCIOUSNESS_STEP_ENABLED=1
```

This is separate from:

```text
KALIV_CONSCIOUSNESS_CORE_ENABLED=1
KALIV_CONSCIOUSNESS_SUPERVISOR_ENABLED=1
KALIV_CONSCIOUSNESS_CHAT_ENABLED=1
```

A live Core/supervisor or admitted chat turn does not itself authorize a model
call through C22-B.

If the step flag is on while the live C19-B session does not exist, the route
returns a generic 503.

## Private route

```text
POST /experimental/consciousness/step
```

The request body must be completely empty.

That is an authority boundary.

The caller cannot supply:

- SelfState;
- WorldState;
- Workspace;
- PersonalitySnapshot;
- CognitiveProfile;
- model name;
- pending events;
- memory refs;
- embodiment refs;
- cycle policy.

All of those remain owned by existing Core/runtime state or separate reviewed
authorities.

## Loopback boundary

The route remains loopback-only regardless of generic worker LAN settings.

Loopback admission occurs before:

- request-body inspection;
- profile loading;
- session lookup;
- any possible model call.

A remote request therefore cannot make this surface inspect private payload
bytes or touch cognitive state.

## Profile source

For every explicit request C22-B calls C22-A fresh:

```text
load_cognitive_profile()
```

A missing or invalid profile produces a generic 503.

C22-B never invents model capabilities.

Because the profile is loaded per request, replacing the operator calibration
changes the next explicit step without changing Self/Person identity.

## One-step semantics

The route invokes exactly:

```python
await session.step(profile=current_profile)
```

once.

C18-B remains the canonical supervisor authority.

### IDLE

No pending work is ready.

Result:

```text
decision=IDLE
ThoughtEngine calls=0
context update=false
```

### WAIT

Pending work exists but the reviewed supervisor pacing interval has not elapsed.

Result:

```text
decision=WAIT
ThoughtEngine calls=0
context update=false
wait_remaining_ms=<bounded value>
```

### RUN

Pending work is selected.

Existing C18/C15/C16 semantics apply:

```text
one supervisor plan
-> one ThoughtEngine call
-> one strict ThoughtProposal validation
-> one deterministic post-cycle reduction
-> one in-memory session adoption
```

There is no second call.

## Concurrency

C22-B adds no new queue.

Existing C18-B single-flight protection remains authoritative.

If a step is already in progress, another attempt fails closed with a generic
conflict response.

It is not enqueued for later.

## No automatic continuation

C22-B adds no:

- loop;
- retry;
- follow-up call;
- scheduler;
- timer;
- thread;
- background task;
- event-triggered auto-step.

Even after a successful RUN, pending events may remain.

A later explicit request is required to evaluate another supervisor step.

## Response privacy

The response is a bounded `CognitiveStepReceipt`.

It may expose:

- RUN / WAIT / IDLE decision;
- selected event ids;
- wait duration;
- whether the ThoughtEngine was invoked;
- profile ref/id/config hash;
- SelfState revision before/after;
- completed-cycle count before/after;
- current-step transition receipt ref.

It does **not** expose:

- ThoughtProposal interpretation;
- hypotheses;
- candidate intentions;
- predicted outcomes;
- questions;
- response intent;
- body intent;
- raw model output;
- hidden/internal reasoning text.

The receipt explicitly fixes:

```text
model_output_exposed=false
raw_chain_of_thought_exposed=false
```

## Failure behavior

Missing session:

```text
503 consciousness session unavailable
```

Missing profile:

```text
503 consciousness cognitive profile unavailable
```

Invalid profile:

```text
503 consciousness cognitive profile invalid
```

Single-flight/lifecycle conflict:

```text
409 consciousness cognitive step already in progress or unavailable
```

Strict ThoughtEngine contract failure:

```text
502 consciousness thought engine returned an invalid proposal
```

Other provider/model failures:

```text
502 consciousness thought engine step failed
```

Internal exception/model text is not reflected to the caller.

## Authority boundary

The receipt fixes:

```text
self_state_store_write_applied=false
durable_memory_write_authority=false
execution_authority=false
scheduling_authority=false
automatic_repeat=false
production_activation=false
```

C22-B itself adds no:

- SelfStateStore write;
- Memory 4 write;
- Agent 3 execution;
- tool execution;
- BodyRig actuation;
- VoiceRig actuation.

A ThoughtProposal may still contain candidate intentions that name external
authority requirements, but C22-B does not execute them.

## Production chain now available

With the separately reviewed flags/configuration present:

```text
normal authenticated user chat
        |
        v
C21-B backend observation
        |
        v
C21-A reported user-turn evidence
        |
        v
C20 live WorldState + pending attention
        |
        v
explicit C22-B step request
        |
        v
C22-A current calibrated profile
        |
        v
C18 supervisor
        |
        v
C15 external replaceable ThoughtEngine
        |
        v
C16 deterministic cognitive state transition
        |
        v
C19-B live session adopts next state
```

The missing piece after C22-B is no longer "can cognition run?".

It becomes a policy question:

> which reviewed event sources, if any, are allowed to request that explicit
> step automatically?

That should remain a separate slice rather than being smuggled into this route.
