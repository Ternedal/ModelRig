# C29-E — Process-local post-wake continuity state

Status: draft, descriptive process-local state only,
`production_activation=false`.

C29-E projects one authenticated C12/C28/C29 WakeReceipt into a strict
process-local continuity state retained by C19 for the lifetime of the live
cognitive session.

> **Continuity knowledge is not autobiographical memory, and a liveness bound
> is not a crash timestamp.**

## Why this slice exists

C29-D made the evidence honest, but later Core policy should not need to
re-interpret raw WakeReceipt fields every time it needs to reason about the
kind of temporal gap that just occurred.

C29-E therefore creates one explicit classification:

```text
PLANNED_EXACT
PLANNED_UNKNOWN
UNPLANNED_BOUNDED
UNPLANNED_UNBOUNDED
```

No fifth ambiguous state is permitted.

## Knowledge classes

### PLANNED_EXACT

A planned SleepRecord crossed the shutdown boundary and C12 established an
exact offline duration.

The continuity state carries:

```text
exact_offline_duration_ms = N
offline_duration_upper_bound_ms = null
last_known_alive_* = null
```

### PLANNED_UNKNOWN

A planned SleepRecord exists, but trusted clocks cannot establish the elapsed
duration, for example after cross-epoch wall-clock rollback.

Both exact duration and upper bound remain absent.

### UNPLANNED_BOUNDED

C28-C classified an unplanned dormancy and C29-D supplied valid last-known-alive
evidence with a numeric maximum possible offline window.

The state carries:

```text
exact_offline_duration_ms = null
offline_duration_upper_bound_ms = N
last_known_alive_witness_ref = ...
last_known_alive_anchor_ref = ...
crash_timestamp_claimed = false
```

The upper bound never becomes an exact duration.

### UNPLANNED_UNBOUNDED

The restart is unplanned but there is no trustworthy numeric upper bound.

This includes both:

- no liveness witness;
- a valid last-known-alive witness whose wall-clock relation to wake cannot be
  trusted numerically.

The latter may retain the witness/anchor refs while the numeric bound remains
absent.

## Identity

The projection requires exact:

- Self id;
- Person Revision.

Mismatch fails closed before the state is created.

The state preserves:

```text
continuity_preserved = true
cognition_during_gap = false
crash_timestamp_claimed = false
```

## C19 integration

`bootstrap_runtime_session()` derives C29-E only when a WakeReceipt exists.

The resulting `RuntimeSessionContext` carries:

```text
continuity_state: PostWakeContinuityState | null
```

A normal process start with no WakeReceipt carries `null`; C29-E does not
invent a previous gap.

The wake WorldObservation is additionally provenance-bound to the canonical
C29-E state ref.

`ProductionCognitiveSession` retains the state process-locally and exposes it
through:

```text
session.continuity_state
```

The state is cleared when the live session closes.

This makes the continuity classification directly available to deterministic
Core policy without creating a second durable store.

## ThoughtEngine boundary

C29-E does not grant the replaceable model continuity authority.

The existing C19 world/workspace material still provides bounded wake context
to cognition, while the strict C29-E object remains Core-owned process-local
state.

A later slice may deliberately add a bounded reference/projection to the C15
context contract if that is useful, but the model must never become the
authority that decides whether a gap was planned, exact or bounded.

## Persistence

C29-E creates no persistence format.

It does not write:

- C14 SelfState;
- Memory 4;
- C29 liveness state;
- sleep lifecycle state;
- any new database or event log.

If the process exits, this derived state disappears. On the next startup it is
derived again only from newly authenticated lifecycle evidence.

## Authority boundary

C29-E fixes:

```text
self_state_store_write_applied = false
model_calls = 0
durable_memory_write_authority = false
execution_authority = false
scheduling_authority = false
production_activation = false
```

It adds no:

- scheduler;
- timer;
- heartbeat;
- polling;
- retry;
- route;
- model call;
- Memory 4 write;
- Agent 3 execution;
- BodyRig/VoiceRig mutation.

## Qualification target

Focused tests prove:

1. planned exact duration maps only to `PLANNED_EXACT`;
2. planned clock uncertainty maps to `PLANNED_UNKNOWN`;
3. unplanned liveness bound maps to `UNPLANNED_BOUNDED` without exact duration;
4. unplanned no-bound maps to `UNPLANNED_UNBOUNDED`;
5. rollback can retain liveness provenance without inventing a numeric bound;
6. foreign identity fails closed;
7. C19 retains the exact state and binds its canonical ref into wake evidence;
8. the live session exposes the state with zero model calls and clears it on
   close.

## Next slice

C29-F may add a deliberately bounded C15 context projection/reference so the
replaceable ThoughtEngine can receive the already-adjudicated continuity
classification without receiving raw lifecycle internals or gaining authority
over it.
