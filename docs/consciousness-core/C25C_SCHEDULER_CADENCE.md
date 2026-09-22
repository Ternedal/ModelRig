# C25-C — Scheduler-owned autonomous cognition cadence

Status: draft, separately default-off.

C25-C composes C25-B into the cadence of the existing production
`SchedulerService`.

It does **not** create another background service.

> **The scheduler supplies cadence. Consciousness Core still owns cognition
> policy and exact-event authority.**

## Activation

All relevant authorities remain separate.

Production scheduled autonomous cognition requires:

```text
KALIV_SCHEDULER=1
KALIV_CONSCIOUSNESS_AUTONOMOUS_ENABLED=1
KALIV_CONSCIOUSNESS_AUTONOMOUS_SCHEDULER_ENABLED=1
```

The new scheduler flag is intentionally separate from C25-B's caller-driven
flag.

Calling `tick_once()` manually and granting periodic production invocation are
different authorities.

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

No second scheduler thread is created.

No second timer is created.

No second polling loop is created.

## Hook failure isolation

The scheduler tick is already complete before the optional hook runs.

Therefore an exception from the optional hook:

- is logged;
- does not retroactively mark the schedule runner tick failed;
- does not alter the TickResult;
- does not retry the cognitive hook.

This prevents optional Consciousness behavior from corrupting scheduler
durability/accounting semantics.

## Why cognition is submitted back to the FastAPI loop

The cognitive session is owned by the worker's async application lifecycle.

The scheduler cadence runs on the pre-existing `kaliv-scheduler` thread.

C25-C does **not** run the async cognitive session directly on that thread.

Instead:

```text
scheduler thread
-> asyncio.run_coroutine_threadsafe(...)
-> FastAPI owner event loop
-> C25-B tick_once()
```

The scheduler thread waits for the bounded result.

The actual C25-B/session/ThoughtEngine coroutine executes on the event-loop
thread that owns the cognitive runtime.

## Timeout

The scheduler-to-event-loop bridge has a bounded timeout.

Default:

```text
30 seconds
```

On timeout:

1. the submitted future is cancelled;
2. no retry is scheduled;
3. the scheduler callback returns;
4. C25-B accounting is unchanged unless a RUN had already reached its verified
   accounting-record boundary.

The timeout is a bridge bound, not a new timer thread.

## Trusted clock binding

C25-C does not construct an independent runtime epoch for autonomous cognition.

C25-B receives its C25-A `ClockSample` through:

```python
session.plan()[0]
```

That samples C18's canonical production supervisor clock without consuming an
event or invoking ThoughtEngine.

Therefore:

- trigger accounting uses the same runtime epoch as the live supervisor;
- a worker restart cannot silently continue the old epoch's automatic budget;
- C25-B's later exact-event step still samples the supervisor again at the real
  execution boundary.

## Startup ordering

The existing scheduler lifespan is deep inside the worker lifespan and starts
before C18/C19 are constructed.

Installing the hook at scheduler startup would therefore race a missing
cognitive session.

C25-C is composed **outside** C19:

```text
enter existing lifespans
-> scheduler becomes live
-> supervisor becomes live
-> cognitive session becomes live
-> C25-C factory evaluates gates
-> install post-tick hook
-> serve application
```

If there is no running scheduler or no live C19 session, no bridge is installed.

## Shutdown ordering

C25-C also owns the inverse boundary:

```text
stop accepting new autonomous tick callbacks
-> clear scheduler post-tick hook
-> cancel/drain submitted cognitive coroutine
-> remove C25-C app state
-> allow C19 session teardown
-> allow supervisor/scheduler teardown
```

This prevents the scheduler thread from submitting new cognition into a session
that is already being closed.

## Single-flight behavior

The scheduler itself is single-threaded.

The bridge additionally rejects an overlapping submitted future if one is
already active.

C18/C19 single-flight remains the final cognitive authority.

C25-C does not create a queue of missed cognitive ticks.

A scheduler cadence that arrives while an earlier cognitive tick is still active
does not become future autonomous work.

## C25-A and C25-B remain authoritative

C25-C supplies cadence only.

Every callback still passes through:

1. C25-B exact autonomous flag;
2. C25-A event-kind policy;
3. C25-A salience thresholds;
4. C25-A rolling budget;
5. C25-A cooldown;
6. C25-B anti-hitchhike check across all pending events;
7. C22 exact-event required-event binding;
8. C18 supervisor pacing and single-flight.

The scheduler callback cannot bypass any of those layers.

## Status

The bridge retains bounded operational status only:

- installed / closed;
- callback count;
- completed count;
- timeout count;
- failure count;
- overlap rejections;
- active yes/no;
- last high-level C25-B outcome;
- generic last error class/reason.

It does not retain:

- user text;
- ThoughtProposal;
- interpretation;
- hypotheses;
- response guidance;
- raw model/provider output.

## Authority boundary

C25-C itself creates no:

- new thread;
- new timer;
- new polling loop;
- retry queue;
- HTTP route;
- durable cognitive state;
- Memory 4 write;
- SelfStateStore write;
- Agent 3 execution;
- tool execution;
- BodyRig actuation;
- VoiceRig actuation.

The bridge status fixes:

```text
internal_thread_created=false
internal_timer_created=false
retry_authority=false
execution_authority=false
durable_memory_write_authority=false
production_activation=false
```

## Resulting autonomous path

When all separately reviewed gates are deliberately enabled:

```text
real world / memory / wake event
        |
        v
canonical CognitionEvent pending in C18
        |
        v
existing scheduler cadence
        |
        v
C25-C post-tick callback
        |
        v
owner-loop C25-B tick_once()
        |
        v
C25-A policy + cooldown + budget
        |
        v
C22 exact-event step
        |
        v
at most one cognitive RUN
```

This is the first production-capable autonomous cognition cadence, but it is
still bounded, event-driven and separately default-off.
