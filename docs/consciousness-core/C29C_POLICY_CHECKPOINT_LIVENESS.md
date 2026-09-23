# C29-C — Policy-checkpoint liveness coupling

Status: draft, default-off production composition, `production_activation=false`.

C29-C connects the existing C27-F/C27-G policy-checkpoint service to the C29-B
committed-checkpoint liveness recorder.

> **Checkpoint authority stays in C27-F. C29-C only observes a successful commit
> and records bounded liveness evidence afterwards.**

## Activation

C29-C has its own exact opt-in:

```text
KALIV_CONSCIOUSNESS_CHECKPOINT_LIVENESS_ENABLED=1
```

The existing C27-G service must also already be enabled:

```text
KALIV_CONSCIOUSNESS_POLICY_CHECKPOINT_ENABLED=1
```

Any other value leaves C29-C off.

The liveness store path resolves from:

```text
KALIV_CONSCIOUSNESS_LIVENESS_STATE
```

with the default:

```text
./kaliv-consciousness-liveness.json
```

Constructing the service does not read or write the liveness store.

## Composition

When C29-C is off, C27-G exposes the unchanged
`PolicyDrivenSelfStateCheckpointAdapter`.

When C29-C is on, C27-G exposes a
`LivenessCoupledPolicyCheckpointAdapter`, which is a strict subclass of the
existing C27-F adapter.

The public `maybe_checkpoint_once()` result remains the existing
`PolicyDrivenCheckpointResult`, so C27-H, C27-I and C27-J keep their current
checkpoint contract.

## Flow

```text
existing C27-F maybe_checkpoint_once()
-> IDLE/HOLD
   -> return unchanged
   -> zero C29-B work
-> COMMITTED
   -> durable SelfState is already authoritative
   -> C29-B record_once(exact checkpoint result)
   -> write one bounded C29-A witness
   -> return unchanged C27-F result
```

No liveness work happens for IDLE or HOLD.

## Evidence binding

C29-B continues to enforce the exact binding:

```text
C27-C store receipt
+ exact committed SelfState ref/revision
+ authoritative Self / Person / Person Revision
+ existing trusted C11 clock
-> C29-A RuntimeLivenessWitness
```

C29-C does not create a second clock or timing source.

## Post-commit failure semantics

A liveness-store failure can only happen after C27-F has returned an actual
COMMITTED checkpoint internally.

C29-C raises `PolicyCheckpointLivenessError` with:

```text
checkpoint_committed = true
checkpoint_retry_authority = false
```

The error retains the exact committed `PolicyDrivenCheckpointResult` for
bounded operator/runtime diagnosis.

The committed SelfState remains authoritative. C29-C never calls C27-C itself
and never retries the checkpoint.

A later call to `maybe_checkpoint_once()` sees the already-reanchored C19
ledger and therefore returns IDLE rather than replaying persistence.

## Store semantics

C29-C uses the existing C29-A `RuntimeLivenessStore` and C29-B recorder. It
adds no history log and no second persistence format.

## Authority boundary

C29-C adds no:

- scheduler;
- heartbeat thread;
- timer;
- polling loop;
- retry loop;
- HTTP route;
- model call;
- Memory 4 write;
- Agent 3/tool execution;
- BodyRig/VoiceRig mutation.

It only adds post-commit liveness evidence to the already-authorized
policy-checkpoint path.

## Compatibility

With the C29-C flag off:

- C27-G constructs the original C27-F adapter;
- no liveness store is constructed;
- no liveness flag-dependent persistence happens;
- C27-H/I/J behavior remains unchanged.

With the flag on:

- only COMMITTED checkpoints touch liveness;
- the caller-visible checkpoint result shape remains unchanged.

## Qualification target

Focused qualification must prove:

1. exact flag behavior;
2. C27-G disabled means the C29-C gate is never consulted;
3. C29-C disabled preserves the plain C27-F service;
4. HOLD performs zero liveness IO;
5. COMMITTED records one exact witness;
6. liveness failure preserves the committed SelfState;
7. the next checkpoint evaluation is IDLE and performs no replay.

## Next slice

C29-D may use the durable liveness witness during startup to strengthen
unplanned-dormancy evidence without claiming an exact crash timestamp.

Any such slice must preserve the C29-A rule that a last-known-alive anchor is
not itself a crash time.
