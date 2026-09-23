# C18-A — Event-driven cognition supervisor kernel

Status: draft, isolated, `production_activation=false`.

C18-A introduces the first reusable orchestration primitive for ongoing cognition
without creating a hidden autonomous process.

> **Events may request cognition. They do not gain execution authority.**

## Flow

```text
CognitionEvent(s)
+ trusted C11 ClockSample
+ SupervisorPolicy
        |
        v
bounded SupervisorState
        |
        v
deterministic plan: IDLE / WAIT / RUN
        |
        v
explicit caller invokes RUN plan
        |
        v
event-oriented workspace
        |
        v
one C15 cognitive cycle
        |
        v
C16 reducer
        |
        v
next in-memory SelfState + SupervisorState
```

## No hidden background loop

C18-A deliberately creates no:

- thread;
- timer;
- polling loop;
- scheduler;
- recurring task;
- process-level daemon.

The kernel only performs work when an external caller explicitly invokes it.

One invocation may execute at most one ThoughtEngine call.

A future production supervisor may decide when to call this kernel, but that
wiring is not part of C18-A.

## Event queue

`CognitionEvent` is bounded and provenance-bearing.

Supported event classes are:

- user turn;
- world change;
- embodiment change;
- tool result;
- memory recall;
- wake follow-up;
- operator signal.

The pending queue is bounded to 64 events.

Event admission is idempotent for an identical event id and exact payload.
Reusing an event id with different content fails closed.

No event can directly mutate SelfState, write durable memory or execute an
action.

## Deterministic planning

The supervisor emits exactly one of:

### IDLE

No pending events.

```text
thought_engine_calls_authorized=0
```

### WAIT

Events exist, but the trusted monotonic clock says the configured minimum cycle
interval has not elapsed.

```text
thought_engine_calls_authorized=0
wait_remaining_ms=<deterministic>
```

### RUN

At least one event is due.

Events are selected by:

1. descending salience;
2. ascending observed sequence;
3. stable event id.

At most `max_events_per_cycle` events are selected, bounded to 16.

```text
thought_engine_calls_authorized=1
```

## Temporal pacing

C18-A uses a trusted C11 `ClockSample`.

The supervisor is bound to one runtime epoch. A changed epoch fails closed and
must go through the existing sleep/wake/bootstrap path instead.

After a completed cycle, a clock sample must:

- belong to the same runtime epoch;
- have a strictly newer sampled sequence;
- not move monotonic time backwards.

This makes cycle pacing deterministic without giving C18-A scheduling authority.

## Event orientation

A RUN plan creates a fresh bounded workspace.

Selected events become workspace candidates with Core-owned kind mapping:

- user/world/operator/wake -> perception;
- embodiment -> body;
- tool result -> tool_result;
- memory recall -> memory.

The prior workspace contributes at most 31 highest-salience candidates.

SelfState then advances by one revision and changes only `workspace_ref`.

Identity, Person Revision, personality, world binding, goals, intentions,
affect, uncertainties and memory binding are explicitly verified unchanged.

## Cognitive cycle

After event orientation:

1. C15 runs exactly once;
2. C16 reduces the verified ThoughtProposal;
3. selected events are removed from the SupervisorState;
4. unselected events remain pending;
5. the trusted clock sample becomes the last-cycle pacing anchor.

No automatic second cycle occurs.

## Authority boundaries

The cycle receipt fixes:

```text
thought_engine_calls=1
internal_thread_created=false
internal_timer_created=false
automatic_repeat=false
self_state_store_write_applied=false
durable_memory_write_authority=false
execution_authority=false
scheduling_authority=false
raw_chain_of_thought_persisted=false
production_activation=false
```

C18-A adds no:

- Memory 4 write;
- Agent 3 execution;
- tool execution;
- BodyRig/VoiceRig actuation;
- scheduler;
- public route;
- production wiring.

## What this unlocks

The Consciousness Core now has two explicit entry paths into cognition:

```text
wake -> C17 -> first post-wake cycle

runtime event -> C18-A -> one paced cognitive cycle
```

A later C18-B may wire trusted runtime events into this kernel behind a
default-off production lifecycle seam, while keeping actual external actions
behind their existing authorities.
