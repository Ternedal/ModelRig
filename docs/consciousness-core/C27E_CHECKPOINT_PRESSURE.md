# C27-E — Deterministic SelfState checkpoint pressure policy

Status: draft, pure policy only, `production_activation=false`.

C27-E decides when the bounded C27-B runtime transition ledger has accumulated
enough continuity evidence that a durable C27-C checkpoint should be considered.

It performs no persistence itself.

> **Checkpoint pressure is a decision. Persistence remains a separate authority.**

## Input

C27-E accepts:

- an optional `RuntimeSelfStateCheckpointPlan`;
- one immutable `CheckpointPressurePolicy`.

No store, clock, scheduler, model or lifecycle object is consulted.

## Decisions

The policy returns exactly one of:

```text
IDLE
HOLD
CHECKPOINT
REQUIRED
```

### IDLE

No pending C27-B plan exists.

```text
pending_transition_count = 0
self_state_store_write_applied = false
```

### HOLD

A valid pending chain exists, but none of the configured pressure conditions are
met.

The default policy permits small bootstrap/world-only batches to remain in RAM
until later activity or the C27-D graceful-shutdown checkpoint.

### CHECKPOINT

A durable checkpoint is recommended, but C27-E does not invoke it.

The default policy returns CHECKPOINT when either:

1. a `post_cycle_reduction` transition is present; or
2. the pending chain reaches eight transitions.

The completed-cycle rule means one successful cognitive RUN becomes
checkpoint-worthy immediately, even when the chain is shorter than eight.

### REQUIRED

The bounded C27-B ledger is too close to capacity for ordinary batching.

The default reserve is two transitions, matching the possible:

```text
C18 supervisor_orientation
+ C16 post_cycle_reduction
```

pair produced by one RUN.

When fewer than two slots remain, the decision is REQUIRED.

REQUIRED is still policy pressure only. It is not execution or scheduling
authority.

## Default policy

```text
checkpoint_transition_count = 8
reserve_transition_slots = 2
checkpoint_after_post_cycle = true
```

The policy is immutable and versioned.

Operators or tests may construct another policy explicitly, but no environment
variable or runtime route is added in C27-E.

## Priority

Decision precedence is deterministic:

```text
capacity reserve exhausted
-> completed cognitive cycle
-> transition threshold reached
-> below threshold
```

This guarantees that a nearly full ledger cannot be downgraded to an ordinary
CHECKPOINT merely because it also contains a completed cognitive cycle.

## Determinism

The same exact:

- checkpoint plan;
- policy;

produces the same:

- decision;
- reason;
- counts;
- transition-kind list;
- deterministic decision id.

No wall-clock time is used.

C27-E therefore does not introduce a second temporal authority alongside C11.

## What C27-E does not do

C27-E does not:

- call `SelfStateStore`;
- call C27-C;
- clear/reanchor the C27-B ledger;
- create a scheduler hook;
- create a timer/thread/task;
- retry failed writes;
- inspect Memory 4;
- call ThoughtEngine;
- execute Agent 3 or tools;
- mutate BodyRig or VoiceRig.

Every decision fixes:

```text
self_state_store_write_applied = false
model_calls = 0
durable_memory_write_authority = false
execution_authority = false
scheduling_authority = false
production_activation = false
```

## Relationship to C27-D

C27-D remains an independent graceful-shutdown safety net.

Even if C27-E returns HOLD throughout a short worker lifetime, graceful shutdown
may still persist the pending chain when the separate C27-D flag is enabled.

## Next slice

A later integration may evaluate C27-E after already-successful SelfState-changing
operations and, behind a separate default-off production gate, call C27-C for
CHECKPOINT/REQUIRED decisions.

That integration must preserve C27-C's failure semantics and must not turn a
successful cognitive cycle into an implicit retry loop.
