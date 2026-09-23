# C27-F — Explicit policy-driven SelfState checkpoint adapter

Status: draft, caller-driven composition only, `production_activation=false`.

C27-F composes C27-E checkpoint pressure with the explicit C27-C durable
checkpoint coordinator without changing any existing C19 mutation API.

> **State mutation and persistence remain separate operations with separate
> receipts.**

## Input

The adapter is constructed with:

- one live `ProductionCognitiveSession`;
- one C14 `SelfStateStore`;
- one immutable C27-E `CheckpointPressurePolicy`.

It constructs the existing C27-C coordinator over that same session/store.

## One explicit evaluation

```python
adapter.maybe_checkpoint_once()
```

performs at most one pressure evaluation and at most one C27-C checkpoint.

There is no loop or retry.

## IDLE

No pending C27-B transition plan exists.

C27-F returns:

```text
outcome = IDLE
coordinator_invoked = false
self_state_store_write_applied = false
```

## HOLD

A pending plan exists, but C27-E says HOLD.

The exact plan is hashed and retained in the result, but:

- C27-C is not called;
- the store is not written;
- the ledger is not reanchored.

## CHECKPOINT / REQUIRED

For either pressure level C27-F:

1. hashes the exact evaluated C27-B checkpoint plan;
2. re-reads the live plan immediately before persistence;
3. fails before C27-C if the visible plan already changed;
4. calls C27-C exactly once;
5. requires C27-C to return COMMITTED;
6. requires the committed `plan_ref` to equal the exact plan evaluated by
   C27-E.

A successful result reports:

```text
outcome = COMMITTED
coordinator_invoked = true
self_state_store_write_applied = true
```

## Why existing mutation APIs are untouched

C27-F deliberately does not wrap or replace:

- `session.step()`;
- C20 world-evidence admission;
- user-turn admission;
- wake/prediction/memory/embodiment event admission.

Those APIs keep their existing success/failure semantics.

A caller may first complete one already-authorized state-changing operation and
then explicitly invoke C27-F.

If persistence then fails, the original cognitive/world operation is **not
replayed** by C27-F.

The C27-B ledger remains the in-memory continuity proof for recovery/checkpoint
retry decisions.

## Plan binding

The adapter uses the same canonical runtime checkpoint-plan ref as C27-C.

A coordinator result that claims COMMITTED for another plan is rejected.

This prevents a pressure decision over state chain A from being presented as
proof that state chain B was the chain persisted.

## Default behavior

With C27-E's default policy:

- bootstrap-only state -> HOLD;
- small world-only batch -> HOLD;
- completed cognitive cycle -> CHECKPOINT;
- eight pending transitions -> CHECKPOINT;
- near-capacity ledger -> REQUIRED.

C27-F still remains caller-driven. The policy decision alone does not schedule
or invoke it.

## Failure behavior

A C27-C failure is surfaced as `PolicyDrivenCheckpointError`.

C27-F adds no retry.

If C27-C reports the already-documented post-write acknowledgement split
failure, C27-F also propagates it rather than repeating the store write.

## Authority boundary

C27-F adds no:

- automatic invocation;
- lifecycle hook;
- scheduler;
- thread;
- timer;
- polling;
- HTTP route;
- model call;
- Memory 4 write;
- Agent 3/tool execution;
- BodyRig/VoiceRig mutation.

For IDLE/HOLD:

```text
self_state_store_write_applied = false
```

For COMMITTED, the write authority is exactly the existing C27-C -> C27-A path.

## Next slice

A later production integration may invoke C27-F after selected already-successful
state-changing operations behind a separate default-off gate.

That integration must define whether persistence failure is fatal, degraded, or
restart-required for each caller surface; C27-F itself makes no such product
policy decision.
