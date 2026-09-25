# C31-D — lived dormancy bridge

Status: implemented on a default-off integration branch.

C31-D closes the reference gap between the existing sleep/wake and continuity
recovery primitives. It does **not** introduce another lifecycle state machine.

## Composition

```text
planned shutdown                           unplanned restart
      |                                          |
   SleepRecord                                    |
      |                                          |
      +---------------> WakeReceipt <-------------+
                           |
                           v
                 PostWakeContinuityState
                           |
                           v
              ContinuityReorientationDecision
                           |
                           v
              ContinuityReorientationWindow
                           |
                           v
                ContinuityOrientationState
                           |
              first accepted post-wake RUN
                           |
                           v
              RecoveryCompletion (optional
              while still REORIENTING)
```

`build_lived_dormancy_bridge()` verifies that every supplied object belongs to
the same Self, Person Revision, wake event and continuity state.

## Planned sleep

A planned wake must carry the exact `SleepRecord`. The bridge verifies:

- the same `sleep_id`;
- the same temporal entry anchor;
- the same durable SelfState binding;
- the same bounded goal, loop and pending-review references; and
- `cognition_continues=false`.

The resulting receipt may describe an exact or unknown planned offline duration
only when that knowledge has already been adjudicated by the existing temporal
and wake contracts.

## Unplanned dormancy

An unplanned wake must **not** carry a `SleepRecord`, planned entry boundary or
exact offline duration. A last-known-alive witness may bound the outage through
the existing C28/C29 contracts, but C31-D never invents a crash timestamp.

## Explicit reorientation

Before the first accepted post-wake RUN:

```text
reorientation_phase = REORIENTING
reorientation window = ACTIVE
recovery completion = absent
```

After that exact RUN has consumed the one-run window:

```text
reorientation_phase = ORIENTED
reorientation window = CONSUMED
recovery completion = exact matching receipt
```

The completion, consumed cycle and orientation must agree. C31-D therefore
cannot claim that wake reorientation completed merely because a process
restarted.

## Authority invariants

Every C31-D receipt fixes:

```text
explicit_reorientation_required=true
continuity_preserved=true
cognition_during_gap=false
hidden_cognition_claimed=false
crash_timestamp_claimed=false
model_calls=0
persistent_state_authority=false
self_state_store_write_applied=false
durable_memory_write_authority=false
automatic_cognition_authority=false
execution_authority=false
scheduling_authority=false
timer_authority=false
production_activation=false
```

C31-D is therefore evidence binding only. C12/C29 remain the lifecycle and
continuity authorities, Memory 4 remains durable autobiographical-memory
authority, Agent 3 remains execution authority, and Person/Profile remains
identity authority.
