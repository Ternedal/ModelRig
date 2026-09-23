# C27-A — Atomic SelfState transition-chain checkpoint

Status: draft, persistence primitive only, `production_activation=false`.

C27-A extends the existing C14 `SelfStateStore` with a bounded checkpoint
primitive for runtime state chains that legitimately advance by more than one
revision between durable commits.

It does **not** wire persistence into C19 yet.

> **A durable checkpoint may collapse storage, but it may not collapse revision
> continuity.**

## Why this is needed

C14 deliberately requires:

```text
write_next.revision == persisted.revision + 1
```

That prevents silent jumps in durable identity state.

The production cognitive path, however, contains several separate verified
in-memory transitions. A typical first cognitive RUN is:

```text
durable SelfState N
-> C19 fresh runtime bootstrap N+1
-> C18 event orientation N+2
-> C16 post-cycle reduction N+3
```

Writing N+3 directly with `write_next()` is correctly rejected.

Weakening `write_next()` to accept arbitrary jumps would destroy the C14
continuity invariant.

## Primitive

C27-A adds:

```python
SelfStateStore.write_chain([
    state_N_plus_1,
    state_N_plus_2,
    ...,
    state_N_plus_k,
])
```

The store first reads the currently persisted state.

It then validates the complete supplied chain before performing any write.

Every state must satisfy:

```text
revision == previous revision + 1
self_id == durable self_id
person_id == durable person_id
person_revision == durable person_revision
```

C27-A deliberately does not permit Person Revision rebinds.

Those remain separately authorized by C14's existing rebind authority.

## Bound

The chain must contain:

```text
1..128 states
```

An empty chain or over-bound chain fails before persistence.

## Atomic storage semantics

After the complete chain validates:

1. C27-A calls the existing C14 atomic writer exactly once;
2. only the final state is written;
3. the writer still uses bounded JSON, fsync and atomic replace.

If validation fails, C27-A performs zero writes.

If the atomic final write fails, no success receipt is returned.

## History semantics

The intermediate states are continuity evidence supplied to the checkpoint
operation.

They are **not** stored as durable history.

The receipt therefore states:

```text
atomic_replace_applied = true
intermediate_history_persisted = false
```

C27-A must not be described as an event log, journal or autobiographical-memory
store.

Memory 4 remains the durable autobiographical-memory authority.

## Receipt

Successful checkpointing returns one bounded
`SelfStateCheckpointReceipt` containing:

- previous durable SelfState ref;
- final SelfState ref;
- refs for all supplied transition states;
- exact Self / Person / Person Revision;
- revision before and after;
- transition count;
- explicit one-write / no-history semantics.

It also fixes:

```text
self_state_store_write_applied = true
model_calls = 0
durable_memory_write_authority = false
execution_authority = false
scheduling_authority = false
production_activation = false
```

## Compatibility

Existing C14 behavior remains unchanged.

`write_next()` still requires exactly one revision increment and retains its
existing Person Revision rebind rules.

C27-A is additive.

## What C27-A does not authorize

C27-A adds no:

- C19 lifecycle integration;
- automatic checkpoint cadence;
- model call;
- model-visible capability;
- HTTP route;
- scheduler;
- thread;
- timer;
- retry;
- Memory 4 write;
- Agent 3/tool execution;
- BodyRig/VoiceRig mutation.

The caller remains responsible for proving that each supplied in-memory state
was produced by an already-authorized Core transition.

## Next slice

C27-B can separately define a production checkpoint authority that collects the
already-verified C19/C20/C18/C16 transitions in exact order and invokes
`write_chain()` at a reviewed commit boundary.

That integration must address failure ordering between:

- C18 supervisor state;
- C19 live context;
- durable SelfState;

without pretending they are one transaction.
