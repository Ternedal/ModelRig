# C25-A — Bounded autonomous cognition trigger policy

Status: draft, pure policy, `production_activation=false`.

C25-A defines when an already-admitted non-user CognitionEvent is eligible to
request one automatic cognitive step later.

It does not schedule or run that step.

> **Eligibility is not execution.**

## Why this exists

C24 proves that an authenticated user turn can be bound to one exact cognitive
step and one same-turn outward reply.

That still leaves a different problem:

How may Kaliv think when nobody just sent a user message?

Potential sources include:

- meaningful world changes;
- embodiment changes;
- memory recall;
- wake follow-up;
- prediction error;
- later temporal threshold events.

That policy must be owned by Consciousness Core rather than by the replaceable
ThoughtEngine or a hidden polling loop.

## Inputs

The evaluator receives exactly:

- one canonical `CognitionEvent`;
- one trusted C11 `ClockSample`;
- one bounded automatic-cognition accounting snapshot;
- one strict `AutonomousTriggerPolicy`.

No model output participates in the decision.

## Decisions

The output is one of:

```text
DENY
DEFER
ELIGIBLE
```

### DENY

The event is not permitted to request automatic cognition.

Default hard denials:

```text
user_turn
operator_signal
tool_result
```

User-turn cognition remains owned by the exact-turn C21→C24 path.

Operator signals do not become autonomous model authority.

Tool results do not silently trigger more cognition until a later policy slice
explicitly reviews that behavior.

Threshold-based events are also denied when salience is too low.

### DEFER

The event type is otherwise eligible, but the automatic-cognition budget or
cooldown currently blocks it.

The decision returns:

```text
not_before_monotonic_ms
```

This is a time fact, not scheduling authority.

No timer is created.

### ELIGIBLE

The event passed:

- event-kind policy;
- salience threshold;
- runtime-epoch binding;
- rolling-window budget;
- cooldown.

The result still authorizes zero model calls.

A later adapter must separately request the existing exact-event step.

## Default policy

Default rolling window:

```text
5 minutes
```

Default maximum automatic steps:

```text
4 per window
```

Default cooldown:

```text
30 seconds
```

Default event behavior:

| Event kind | Default |
|---|---|
| `user_turn` | DENY |
| `operator_signal` | DENY |
| `tool_result` | DENY |
| `wake_followup` | eligible, subject to budget/cooldown |
| `world_change` | salience >= 0.80 |
| `embodiment_change` | salience >= 0.85 |
| `memory_recall` | salience >= 0.85 |
| `prediction_error` | salience >= 0.75 |

These values are Core policy, not model suggestions.

## Monotonic time only

Cooldown and rolling-window enforcement use trusted runtime-monotonic time.

Wall-clock jumps cannot grant extra automatic cycles.

If the trusted monotonic clock moves backward inside one runtime epoch, C25-A
fails closed with a contract error.

## Runtime epoch changes

Automatic accounting belongs to one runtime epoch.

If the clock sample belongs to another epoch:

```text
decision=DENY
reason=runtime_epoch_changed
```

The evaluator does not silently transfer prior automatic-cognition budget across
a restart.

A higher lifecycle owner may later create a fresh accounting snapshot for the
new epoch after wake/reorientation policy has run.

## Rolling budget

`AutomaticCognitionAccounting` records:

- runtime epoch;
- rolling-window start;
- automatic steps already recorded in the window;
- last automatic-step monotonic time.

Evaluation is pure.

If the old window has expired, the evaluator computes an effective fresh window
for the decision but does not mutate the supplied snapshot.

## Separate record operation

After a later caller has separately completed an allowed exact-event step it may
call:

```python
record_automatic_cognition(...)
```

Recording succeeds only when the supplied decision is:

```text
ELIGIBLE / eligible
```

and still matches:

- the exact ClockSample;
- the exact runtime epoch;
- the exact policy ref;
- an unexhausted effective budget.

The record operation increments accounting by exactly one.

It does not run or authorize the cognitive step itself.

Its receipt explicitly states:

```text
model_calls_authorized_here=0
```

## Determinism and provenance

The policy has a canonical SHA-256 reference.

Each decision receives a deterministic `autodec-...` identity derived from:

- event id;
- trusted clock sample id;
- decision;
- reason;
- defer time;
- effective window accounting;
- policy ref.

Same validated inputs produce the same decision id.

## Authority boundary

Every decision fixes:

```text
event_consumed=false
model_calls=0
scheduling_authority=false
execution_authority=false
durable_memory_write_authority=false
production_activation=false
```

C25-A creates no:

- HTTP route;
- background loop;
- scheduler;
- timer;
- thread;
- polling;
- model call;
- event dequeue/consume;
- SelfStateStore write;
- Memory 4 write;
- Agent 3 execution;
- tool execution;
- BodyRig actuation;
- VoiceRig actuation.

## Downstream anti-hitchhike requirement

The existing supervisor may select more than one pending event in one RUN.

Therefore a later automatic adapter must not merely require that one eligible
event is present. Before requesting a RUN it must also prove that every event
the canonical supervisor could select in that same step is permitted by the
same C25-A policy snapshot.

A denied user turn, operator signal or tool result must never acquire an
automatic model call by being selected alongside an otherwise eligible world
change.

## Next slice

C25-B may add a tiny lifecycle/scheduler-owned adapter:

```text
pending canonical event
+ C25-A ELIGIBLE
-> request existing C22 exact-event step once
-> record automatic cognition only after successful RUN
```

That adapter must still be separately gated and must not invent its own retry or
continuous polling loop.
