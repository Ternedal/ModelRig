# C25-B — Default-off one-tick autonomous cognition adapter

Status: draft, caller-driven only, default-off.

C25-B is the first adapter that can turn a C25-A eligibility decision into one
existing exact-event cognitive step.

It still does not own a scheduler.

> **One explicit tick may request at most one cognitive cycle. No tick repeats
> itself.**

## Activation

Exact opt-in:

```text
KALIV_CONSCIOUSNESS_AUTONOMOUS_ENABLED=1
```

Anything else is off.

With the flag off, `tick_once()` returns `DISABLED` before touching:

- trusted clock;
- CognitiveProfile configuration;
- ThoughtEngine;
- supervisor/session state.

## Caller-driven boundary

C25-B exposes an in-process async method:

```python
await AutonomousCognitionTickAdapter.tick_once()
```

It adds no HTTP route and starts no task or thread.

A later lifecycle owner must explicitly call it.

## Tick flow

One call performs at most:

```text
flag check
-> trusted ClockSample
-> pending-event snapshot
-> C25-A evaluation
-> deterministic selection
-> fresh CognitiveProfile load
-> one session.step(required_event_id=...)
-> accounting record only after RUN
```

There is no retry.

## Anti-hitchhike rule

C18 may select up to several pending events in one RUN.

Therefore C25-B refuses to request an automatic step unless **every currently
pending event** evaluates to `ELIGIBLE` under the same:

- ClockSample;
- automatic-cognition accounting snapshot;
- C25-A policy.

If any pending event is `DENY`:

```text
outcome=IDLE
reason=pending_event_denied
ThoughtEngine calls=0
```

If any pending event is `DEFER`:

```text
outcome=DEFER
reason=pending_event_deferred
ThoughtEngine calls=0
```

This prevents a denied:

- user turn;
- operator signal;
- tool result;

from receiving an automatic model call merely because it sat beside an eligible
world-change event in the supervisor queue.

## Deterministic event selection

When every pending event is eligible, the required event is selected using the
same canonical ordering as C18:

```text
highest salience
-> oldest observed_sequence
-> lowest event_id
```

This matters when more events are pending than C18's per-cycle event budget.

The event C25-B chooses is therefore guaranteed to be in the canonical RUN
selection whenever C18 is permitted to RUN.

## Fresh cognitive profile

The C22-A profile is loaded only after an event has passed policy and been
selected.

A missing profile returns:

```text
IDLE / profile_unavailable
```

with no ThoughtEngine call and no accounting increment.

Invalid profile-loader behavior fails closed.

## Supervisor WAIT

C25-A eligibility does not bypass C18 pacing.

If:

```text
session.step(required_event_id=...)
```

returns WAIT:

- ThoughtEngine calls = 0;
- required event remains pending;
- accounting is unchanged;
- the receipt is `WAIT / supervisor_wait`.

C25-B does not sleep until the wait expires and does not retry.

## Successful RUN

A RUN must prove:

- ThoughtEngine was invoked exactly once by the existing session/supervisor path;
- the required event appears in the canonical selected-event ids;
- every selected event belonged to the same C25-A ELIGIBLE snapshot.

Only after that succeeds does C25-B call:

```text
record_automatic_cognition(...)
```

Accounting increments by exactly one **automatic cognitive step**, not by the
number of events consumed in that cycle.

## Failures do not spend budget

These cases do not increment automatic-cognition accounting:

- policy deny/defer;
- no pending events;
- missing profile;
- supervisor WAIT;
- exact-event binding failure;
- provider/model failure;
- invalid returned session state.

The accounting object is replaced only after a verified RUN.

## Tick outcomes

```text
DISABLED
IDLE
DEFER
WAIT
RUN
```

The receipt contains only bounded operational metadata:

- trusted clock sample id;
- evaluated event ids;
- selected event id;
- C25-A decision id;
- not-before time when deferred;
- cognitive-profile ref;
- supervisor decision and selected ids;
- model-call count;
- accounting before/after.

It contains no ThoughtProposal or raw provider output.

## Authority boundary

Every receipt fixes:

```text
automatic_repeat=false
internal_thread_created=false
internal_timer_created=false
self_state_store_write_applied=false
durable_memory_write_authority=false
execution_authority=false
scheduling_authority=false
production_activation=false
```

C25-B creates no:

- thread;
- timer;
- polling loop;
- scheduler;
- retry queue;
- HTTP route;
- durable state;
- tool execution;
- Agent 3 execution;
- BodyRig actuation;
- VoiceRig actuation.

## Next slice

C25-C may explicitly compose this adapter into the **existing**
`SchedulerService` lifecycle.

That work must answer the thread/event-loop ownership question directly rather
than creating a second background service inside Consciousness Core.
