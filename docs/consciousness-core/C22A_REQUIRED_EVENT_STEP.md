# C22-A — Required-event one-shot cognition

Status: draft, Core-only extension of the existing explicit-call supervisor.

C22-A adds one missing correctness property for turn-coupled cognition:

> **If a caller says "run cognition for event X", the model call may not silently
> run for another event instead.**

No route, profile resolver or automatic chat trigger is introduced in this slice.

## Existing generic behavior

The existing C19-B call remains valid:

```python
await session.step(profile=profile)
```

That asks the supervisor to execute its canonical current RUN plan, if any.

C22-A does not change that behavior.

## Required-event behavior

The caller may now supply:

```python
await session.step(
    profile=profile,
    required_event_id="cevt-...",
)
```

The required event id is passed through C19-B into the C18-B bridge.

Before any ThoughtEngine invocation, C22-A verifies:

1. the id has exact `cevt-<32 lowercase hex>` shape;
2. that event is currently pending;
3. if the canonical supervisor plan is RUN, that exact event is among the
   canonically selected events.

Failure of any of these checks fails closed before the model call.

## Canonical plan still owns selection

C22-A does not let the caller rewrite the supervisor plan.

The caller cannot say:

> run event X even though the canonical plan selected Y.

If X is pending but falls outside the bounded selected set—for example because
four higher-salience events occupy a policy with
`max_events_per_cycle=4`—the required-event step is refused.

The caller must not bypass:

- salience ordering;
- event bounds;
- pacing;
- canonical plan construction.

## WAIT semantics

If the required event is pending but the supervisor is inside its minimum
inter-cycle interval, canonical planning returns WAIT.

C22-A preserves that:

```text
required event: pending
plan: WAIT
ThoughtEngine calls: 0
live cognitive context: unchanged
event: remains pending
```

There is no automatic retry.

## RUN semantics

If the plan is RUN and includes the required event:

- exactly one existing C18-A supervisor cycle runs;
- exactly one C15 ThoughtEngine call is authorized;
- C16 performs the existing deterministic post-cycle reduction;
- C19-B adopts the resulting verified live state.

The same cycle may include other events that were independently selected by the
canonical supervisor plan.

C22-A only requires that the named event is among them.

## Missing or already-consumed events

If the required event is not pending, the call fails closed before model
invocation.

That includes an event already consumed by an earlier cycle.

A caller therefore cannot replay a model turn merely by resending an old event
id.

## CognitiveProfile remains explicit

C22-A still requires a complete explicit `CognitiveProfile`.

This is deliberate.

The current contract contains normalized fields such as:

- reasoning depth;
- planning capacity;
- uncertainty calibration.

The repository does not currently have measured production evidence for those
values.

C22-A therefore does **not** invent a profile or assign benchmark-looking
numbers to a model.

Production profile resolution remains a separate reviewed slice.

## Authority boundary

C22-A adds no:

```text
route
feature flag
automatic model invocation
thread
timer
scheduler
retry
background loop
SelfStateStore write
Memory 4 write
Agent 3 execution
tool execution
BodyRig actuation
VoiceRig actuation
```

It only narrows an already-explicit one-shot cognition call by binding it to one
pending event.

## What this unlocks

C21-A already returns the exact cognition event id created for a newly admitted
user turn.

With C22-A, a future turn-cognition adapter can safely say:

```text
admitted turn -> event cevt-X
                  |
                  v
step(required_event_id=cevt-X)
```

and know that a model call cannot silently process some unrelated pending event
instead.

The next slice must solve production CognitiveProfile resolution honestly before
normal chat is allowed to trigger this call automatically.
