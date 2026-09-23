# C25-B — Default-off one-tick autonomous cognition adapter

Status: draft, caller-driven only, default-off.

C25-B turns C25-A eligibility into at most one existing exact-event cognitive
step per explicit call. It adds no scheduler or background lifecycle.

> **One explicit tick may request one cognitive cycle. Nothing repeats itself.**

## Activation

Exact opt-in:

```text
KALIV_CONSCIOUSNESS_AUTONOMOUS_ENABLED=1
```

Any other value is off.

Flag-off is first: no clock sample, pending-event inspection, profile read or
model call occurs.

## One-tick flow

```text
explicit tick_once()
-> trusted C25-B clock sample
-> snapshot every pending CognitionEvent
-> evaluate every event through C25-A
-> DENY present? stop
-> DEFER present? stop
-> freeze exact ELIGIBLE event-id set
-> choose canonical required event
-> load fresh C22-A CognitiveProfile
-> session.step(
     required_event_id=...,
     allowed_event_ids=frozen eligible set
   )
-> record automatic accounting only after verified RUN
```

No retry, thread, timer, polling loop or route is created.

## Anti-hitchhike at two layers

C18 may select multiple events in one canonical RUN.

C25-B therefore protects automatic cognition twice.

First, it refuses to proceed unless **every event in the evaluated pending
snapshot** is C25-A `ELIGIBLE`.

Second, it passes the exact eligible id snapshot to C18/C19 as
`allowed_event_ids`.

The lower layer rejects a RUN before ThoughtEngine invocation if its canonical
selected events contain any id outside that set.

This closes both:

- a denied event already pending during policy evaluation; and
- a denied event admitted after evaluation but before the exact-event step.

A user turn, operator signal or tool result cannot hitchhike into an autonomous
model call.

## Canonical selection

Required-event selection uses the exact C18 ordering:

```text
highest salience
-> lowest observed_sequence
-> lowest event_id
```

The selected required event is therefore compatible with C18's bounded
multi-event plan.

## Outcomes

The bounded receipt reports:

```text
DISABLED
IDLE
DEFER
WAIT
RUN
```

### DISABLED

The autonomous flag is not exact `1`.

```text
model_calls=0
pending_event_count=0
evaluated_event_count=0
clock_sample_id=null
```

### IDLE

No pending event exists, or a pending event is denied.

No profile/model work occurs when a denied event blocks the snapshot.

### DEFER

Every non-denied event is potentially autonomous, but C25-A cooldown/window
budget says not yet.

The receipt carries the latest required:

```text
not_before_monotonic_ms
```

No timer is created.

### WAIT

All policy checks passed and a required exact event was selected, but the
canonical C18 supervisor pacing policy returned WAIT.

No model call occurs, the event remains pending and automatic accounting is
unchanged.

### RUN

Exactly one existing C18/C19 cognitive step completed.

Only then is C25-A automatic accounting advanced by one.

The budget counts cognitive steps, not the number of events selected inside one
bounded supervisor cycle.

## Fresh profile boundary

The C22-A profile is loaded only after the event snapshot passes C25-A.

Missing/invalid profile state fails before ThoughtEngine and does not spend
automatic budget.

Model/provider/session failures also leave accounting unchanged because the
record operation occurs only after a verified RUN.

## Race binding

The eligible event set is frozen before profile IO.

That matters because profile loading creates an explicit race window where
another source could admit a new event.

The exact lower-layer call receives:

```text
required_event_id = selected eligible event
allowed_event_ids = exact policy-approved snapshot
```

If a new non-approved event would enter C18's canonical selected set, the
supervisor refuses before model invocation.

Regression tests cover this race directly.

## Receipt privacy and authority

The C25-B receipt contains only bounded operational metadata:

- event counts and ids by policy decision;
- selected event id;
- supervisor selected ids;
- not-before time;
- cognitive-profile ref;
- model-call count;
- automatic-accounting before/after.

It contains no ThoughtProposal, interpretation, hypotheses, response intent or
raw provider output.

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

## Non-goals

C25-B does not:

- start itself;
- attach to SchedulerService;
- sleep until DEFER expires;
- retry WAIT/failure;
- persist automatic accounting;
- execute tools or Agent 3;
- actuate BodyRig or VoiceRig.

A later C25-C may provide the separately reviewed production cadence bridge by
reusing an existing lifecycle owner rather than creating another autonomous
thread.
