# C29-I — One-successful-RUN post-wake reorientation horizon

Status: draft, process-local cycle horizon only,
`production_activation=false`.

C29-I bounds the direct C29-F model-context influence of post-wake continuity to
the first successfully accepted cognitive RUN of the live session.

The underlying C29-E continuity evidence remains available to deterministic
Core policy after that.

> **Wake context should orient the next cognitive moment, not tint every later
> thought forever.**

## Window

A live session with C29-E continuity opens:

```text
ContinuityReorientationWindow
state = ACTIVE
remaining_successful_runs = 1
consumed_cycle_id = null
```

A normal runtime start without WakeReceipt/continuity has no window.

## What consumes the window

Only a successfully completed C19/C18 RUN consumes it.

The order is:

```text
ACTIVE window
-> pass C29-E state to C18/C15
-> one ThoughtEngine RUN
-> validate/adopt C16 result into live session
-> consume exact cognitive cycle id
-> CONSUMED window
```

The consumed state is:

```text
state = CONSUMED
remaining_successful_runs = 0
consumed_cycle_id = <exact accepted cycle id>
```

## What does not consume it

The window is not consumed by:

- IDLE;
- WAIT;
- planning;
- a queued event by itself;
- lifecycle time passing;
- wall-clock time;
- a failed step before successful live-state adoption.

C29-I owns no timer and has no expiry clock.

## After consumption

C29-E `continuity_state` remains process-local and available to deterministic
Core policy.

However, C19 passes `continuity_state=None` into later C18/C15 model cycles
once the window is consumed.

C29-F therefore removes the optional continuity key from those later
ThoughtEngine context dictionaries.

This separates:

- **Core continuity knowledge**, which may remain useful;
- **direct model reorientation context**, which is intentionally one successful
  cognitive moment.

## Session close

C19 clears both:

- process-local C29-E continuity state;
- C29-I reorientation window.

No C29-I state is persisted across process restart.

## Authority boundary

The C29-I window fixes:

```text
model_calls = 0
self_state_store_write_applied = false
durable_memory_write_authority = false
execution_authority = false
scheduling_authority = false
timer_authority = false
production_activation = false
```

Opening or consuming the window does not itself call a model. It only determines
whether an already-authorized C19/C18 RUN receives C29-F context.

C29-I adds no:

- event;
- scheduler;
- timer;
- polling;
- retry;
- route;
- store;
- Memory 4 write;
- Agent 3 execution;
- BodyRig/VoiceRig mutation.

## Qualification target

Focused tests prove:

1. the window opens with exactly one successful RUN remaining;
2. consumption records the exact cycle id and cannot occur twice;
3. IDLE leaves the window active and makes zero model calls;
4. first RUN receives C29-F continuity context and consumes the window;
5. second RUN receives no continuity model context;
6. the underlying C29-E state survives the first RUN;
7. no-wake sessions have no window;
8. session close clears both state and window.

## Next slice

C29-J may add a pure continuity-recovery completion receipt tying the consumed
window to the first accepted cycle and wake evidence. That receipt must remain
process-local/diagnostic unless a separate persistence authority is explicitly
reviewed.
