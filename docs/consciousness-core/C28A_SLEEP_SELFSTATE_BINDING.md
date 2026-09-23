# C28-A — Exact durable SelfState sleep/wake binding

Status: draft, continuity hardening only, `production_activation=false`.

C28-A strengthens the existing C13 sleep/wake boundary by binding a planned
sleep record to the exact durable C14 SelfState that existed at shutdown.

> **Wake continuity may claim an exact prior SelfState only when that exact
> durable state was recorded and later verified.**

## Shutdown sequence

The existing lifecycle ordering remains:

```text
C25-C autonomous submissions stop
-> C27-D optional graceful SelfState checkpoint
-> C19/C27-G teardown begins
-> C13 sleep lifecycle closes
```

The authoritative C13 binding provider reads the C14 SelfState store when it is
asked for the shutdown binding.

When C27-D checkpointing is enabled and succeeds, that read therefore observes
the final durable state after the graceful checkpoint.

## SleepBinding

C28-A adds an optional all-or-none pair:

```text
durable_self_state_ref
durable_self_state_revision
```

Production `authoritative_sleep_binding()` fills both values from the exact
verified C14 state:

- revision = `PersistentSelfState.revision`;
- ref = canonical `self_state_ref(state)`.

The binding still requires the exact active Person id/revision match.

## SleepRecord

New planned sleep records copy the same exact pair into the existing
`sleep-record/v1` contract.

The pair is included in the deterministic sleep-id seed when present, so a
record bound to another durable state cannot produce the same sleep id merely by
sharing self/person/temporal inputs.

The pair is validated as all-or-none.

## Legacy compatibility

Existing v1 sleep records that predate C28-A contain neither field.

They remain valid.

When a legacy record is read:

```text
durable_self_state_ref = null
durable_self_state_revision = null
```

C28-A does not invent an exact state binding for old records.

## WakeReceipt

A planned wake copies the exact pair from the SleepRecord.

Unplanned dormancy has no planned-sleep durable-state claim and therefore
carries null values.

The WakeReceipt pair is also all-or-none.

## C19 bootstrap verification

When a WakeReceipt contains the exact durable binding, C19 validates it before
fresh runtime WorldState/Workspace construction.

Both must match the currently loaded durable state:

```text
wake.durable_self_state_revision == state.revision
wake.durable_self_state_ref == self_state_ref(state)
```

A mismatch fails closed before the runtime bootstrap advances SelfState.

This detects cases such as:

- sleep record from an older durable checkpoint;
- replaced/corrupt durable SelfState;
- mismatched shutdown artifacts;
- operator-restored state that no longer matches the planned sleep boundary.

## Legacy wake behavior

When both wake binding fields are null, C19 preserves the previous C13/C19
identity + Person Revision continuity behavior.

It may still verify:

- same self id;
- same Person Revision;
- cognition did not continue offline;
- temporal wake relation.

It simply does **not** claim exact prior SelfState continuity.

## Store authority

C28-A adds no store.

The existing stores remain separate:

- C14 SelfStateStore owns durable SelfState;
- C13 SleepStateStore owns the bounded sleep boundary.

They are not one filesystem transaction.

C28-A adds a cryptographic/reference relationship between them, not transaction
atomicity.

## Failure semantics

A new exact-binding mismatch aborts C19 wake bootstrap.

It does not:

- rewrite the sleep record;
- rewrite SelfState;
- automatically select one artifact as authoritative;
- retry;
- call a model.

Recovery remains an explicit operator/restart concern.

## Authority boundary

C28-A adds no:

- model call;
- scheduler;
- thread;
- timer;
- polling;
- Memory 4 write;
- Agent 3/tool execution;
- BodyRig/VoiceRig mutation;
- new route;
- new activation flag.

It only strengthens existing continuity evidence across shutdown and wake.
