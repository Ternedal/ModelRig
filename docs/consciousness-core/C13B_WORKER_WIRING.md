# C13-B — Authoritative worker sleep/wake wiring

Status: draft, default off, `production_activation=false`.

C13-B closes the production wiring gap between C13-A persisted sleep continuity
and C14 persistent SelfState.

## Authority chain

```text
C14 PersistentSelfState
  + exact active PersonRegistry binding
  + C11 TrustedRuntimeClock
  -> C13 SleepBinding
  -> C12 SleepRecord / WakeReceipt
  -> existing worker lifespan
```

No model/provider identity participates in this chain.

## Runtime clock

`TrustedRuntimeClock` owns one random `runtime_epoch_id` per worker runtime
instance and emits C11 `ClockSample` values from:

- system wall clock for civil/offline time;
- `time.monotonic_ns()` for same-process elapsed time;
- the host local timezone/UTC offset;
- a strictly increasing in-process sequence.

A new worker runtime gets a new epoch. Monotonic values are never treated as
comparable across epochs.

## Binding

`authoritative_sleep_binding()` returns a binding only when all of these are
true:

1. C14 SelfState exists and validates;
2. the Person registry exists;
3. one selected Person has an active approved Person Revision;
4. the active `person_id` equals SelfState `person_id`;
5. the active `person_revision` equals SelfState `person_revision`.

A mismatch raises instead of guessing/rebinding identity.

Goals and intentions are carried only as opaque references. C13-B does not
execute them. `pending_review_refs` remains empty until a separately-authorized
review queue exists.

## Production lifespan

The worker now composes:

```text
sleep_lifecycle(
  memory4_write(
    memory4_context(
      scheduler_lifespan
    )
  )
)
```

The C13 wrapper deliberately preserves `scheduler_lifespan` as the
`__wrapped__` authority owner.

Startup order means existing worker resources enter first, then C13 reads a
prior sleep boundary while the process is alive. Shutdown order writes the
sleep boundary before the inner Memory 4/scheduler cleanup exits.

## Dormancy invariant

When the worker is off there is no background cognition, scheduler created by
Consciousness Core, model call, Memory 4 write, BodyRig/VoiceRig action or Agent
3 execution.

Every C12 wake receipt therefore retains:

```text
continuity_preserved=true
cognition_during_gap=false
execution_authority=false
scheduling_authority=false
durable_memory_write_authority=false
production_activation=false
```

## Activation

The production seam remains opt-in:

```text
KALIV_CONSCIOUSNESS_SLEEP_LIFECYCLE_ENABLED=1
```

With the flag absent/off, no Consciousness Core persistence is read or written by
this lifecycle.
