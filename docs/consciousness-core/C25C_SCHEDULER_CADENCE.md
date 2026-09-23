# C25-C — Scheduler-owned autonomous cognition cadence

Status: draft, separately default-off.

C25-C composes C25-B into the cadence of the existing production
`SchedulerService`.

It does not create another background service.

> **The scheduler supplies cadence. Consciousness Core still owns cognition
> policy and exact-event authority.**

## Activation

Scheduled autonomous cognition requires all relevant authorities:

```text
KALIV_SCHEDULER=1
KALIV_CONSCIOUSNESS_AUTONOMOUS_ENABLED=1
KALIV_CONSCIOUSNESS_AUTONOMOUS_SCHEDULER_ENABLED=1
```

The scheduler-integration flag is deliberately separate from C25-B's
caller-driven flag. Manual one-tick authority and periodic production invocation
are different powers.

## Existing scheduler thread only

C25-C adds one optional post-successful-tick callback seam to
`SchedulerService`.

Default:

```text
post_tick_hook = None
```

With no hook installed, scheduler behavior is unchanged.

When installed:

```text
existing kaliv-scheduler thread
-> existing SchedulerRunner.run_once()
-> successful TickResult
-> optional post_tick_hook(TickResult)
```

No second scheduler thread, timer or polling loop is created.

## Hook failure isolation

The schedule runner tick is already complete before the optional observer runs.

A hook exception is logged but does not:

- change the TickResult;
- increment scheduler tick failures;
- retry the cognitive callback;
- alter schedule durability/accounting.

## Owner-loop handoff

The cognitive session is owned by the FastAPI async lifecycle, while the
scheduler cadence runs on `kaliv-scheduler`.

C25-C therefore never runs C25-B directly on the scheduler thread.

Instead:

```text
kaliv-scheduler
-> asyncio.run_coroutine_threadsafe(...)
-> FastAPI owner event loop
-> C25-B tick_once()
```

The existing scheduler thread waits for a bounded result. The cognitive
coroutine itself executes on the owner loop.

## Canonical trusted clock

C25-B requires a `TrustedRuntimeClock`.

C25-C does not create another clock or runtime epoch. C18 now exposes its owned
trusted clock through read-only properties:

```text
ProductionSupervisorBridge.trusted_clock
ProductionCognitiveSession.trusted_clock
```

These properties do not sample the clock and grant no scheduling authority.

C25-C constructs C25-B with:

```python
clock=session.trusted_clock
```

so C25-A accounting and the later C18 exact-event step remain in the same
runtime epoch.

## Timeout and cancellation

The bridge timeout is bounded; default:

```text
30 seconds
```

On timeout:

1. the submitted future is cancelled;
2. no retry is created;
3. the scheduler callback returns;
4. C25-B's existing accounting rules remain authoritative.

Provider/session exception text is not retained in bridge status.

## Startup ordering

The production scheduler starts inside the existing worker lifespan before
C18/C19 exist.

C25-C therefore composes outside C19:

```text
enter existing lifespans
-> scheduler live
-> supervisor live
-> C19 cognitive session live
-> evaluate C25-C gates
-> construct bridge from live session
-> install post-tick hook
-> serve application
```

No hook is installed if:

- C25-C flag is off;
- C25-B flag is off;
- scheduler is absent/not running;
- C19 session is absent/closed.

## Shutdown ordering

The outer composition also owns teardown order:

```text
clear scheduler post-tick hook
-> reject new callbacks
-> cancel/drain submitted C25-B coroutine
-> remove C25-C app state
-> allow C19 teardown
-> allow supervisor/scheduler teardown
```

This prevents the scheduler thread from submitting cognition into a closing
session.

## Single-flight and overlap

C25-C does not build a queue of missed cognition ticks.

If a submitted C25-B future is still active, an overlapping callback is
rejected and counted.

C18/C19 single-flight remains the final cognitive authority.

## C25-A/B remain authoritative

C25-C supplies cadence only.

Every callback still passes through:

1. C25-B exact autonomous flag;
2. C25-A event-kind and salience policy;
3. C25-A cooldown and rolling budget;
4. C25-B full pending-snapshot anti-hitchhike check;
5. C25-B frozen `allowed_event_ids`;
6. C18 canonical exact-event selection and pacing;
7. ThoughtEngine only after all previous gates pass.

The scheduler callback cannot bypass those layers.

## Bridge status

C25-C retains only bounded operational metadata:

- installed / closed;
- callback count;
- completed count;
- timeout count;
- generic failure count;
- overlap rejections;
- active yes/no;
- last high-level C25-B outcome;
- generic error class/reason.

It retains no user text, ThoughtProposal, response guidance or provider output.

## Authority boundary

Bridge status fixes:

```text
internal_thread_created=false
internal_timer_created=false
retry_authority=false
execution_authority=false
durable_memory_write_authority=false
production_activation=false
```

C25-C adds no:

- new thread;
- new timer;
- new polling loop;
- retry queue;
- HTTP route;
- SelfStateStore write;
- Memory 4 write;
- tool/Agent 3 execution;
- BodyRig actuation;
- VoiceRig actuation.

## Resulting autonomous production path

When every independently reviewed switch is deliberately enabled:

```text
non-user world/memory/wake/prediction event
        |
        v
canonical CognitionEvent pending in C18
        |
        v
existing scheduler cadence
        |
        v
C25-C post-tick observer
        |
        v
owner-loop C25-B tick_once()
        |
        v
C25-A policy + budget + cooldown
        |
        v
C18 exact allowed-event step
        |
        v
at most one cognitive RUN
```

This creates a production-capable cadence while keeping cognition bounded,
event-driven and independently default-off.
