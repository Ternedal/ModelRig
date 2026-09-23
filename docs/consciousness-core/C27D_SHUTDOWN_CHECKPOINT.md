# C27-D — Default-off graceful-shutdown SelfState checkpoint

Status: draft, graceful-shutdown persistence only,
`production_activation=false`.

C27-D is the first production lifecycle seam that invokes the explicit C27-C
SelfState checkpoint automatically.

It does so exactly once, and only during graceful worker shutdown.

> **Stop new cognition first. Persist the verified state chain second. Close the
> live session third.**

## Activation

Exact opt-in:

```text
KALIV_CONSCIOUSNESS_SELF_STATE_CHECKPOINT_ENABLED=1
```

Any other value is off.

With the flag off, C27-D returns before:

- reading `app.state.consciousness_session`;
- constructing a `SelfStateStore`;
- reading durable SelfState;
- constructing the C27-C coordinator;
- performing any persistence.

## No live session

Even with the flag enabled, no C19 session means no checkpoint coordinator and
no store construction.

C27-D does not create a cognitive session merely to persist state.

## Lifecycle ordering

The production entrypoint composes C27-D:

- **inside C25-C** autonomous scheduler lifecycle;
- **outside C19** cognitive session lifecycle.

The effective shutdown order is therefore:

```text
1. C25-C clears the SchedulerService post-tick cognition hook
2. C25-C cancels/drains any in-flight submitted autonomous tick
3. C27-D invokes checkpoint_once()
4. C19 closes the live cognitive session
5. C18/sleep/scheduler inner lifecycles continue teardown
```

This ordering prevents a new autonomous cognitive RUN from advancing SelfState
while the graceful-shutdown checkpoint is being committed.

The C19 session remains open until C27-C has acknowledged the durable receipt.

## Checkpoint behavior

C27-D does not implement persistence rules itself.

It constructs the existing:

```text
ExplicitSelfStateCheckpointCoordinator
```

with:

- the already-live C19 session;
- the normal C14 `SelfStateStore`.

On shutdown it calls:

```python
coordinator.checkpoint_once()
```

exactly once.

### IDLE

If the C27-B ledger has no pending transitions, C27-C returns `IDLE`.

C27-D accepts that as a valid graceful shutdown.

No store write occurs.

### COMMITTED

If pending transitions exist, C27-C:

1. verifies the exact C27-B plan and state refs;
2. verifies the current durable C14 anchor;
3. invokes C27-A `write_chain()`;
4. verifies the C27-A receipt;
5. asks C19/C27-B to acknowledge and reanchor.

Only the final SelfState is persisted.

Intermediate states remain continuity evidence, not durable history.

## Failure behavior

C27-D deliberately does not swallow checkpoint failures.

A failure is re-raised as:

```text
ShutdownSelfStateCheckpointError
```

The nested async-context teardown still proceeds, so C19 and deeper lifecycle
owners can close their resources.

### Pre-write failure

Examples:

- stale durable anchor;
- invalid pending chain;
- store construction failure.

No durable success is claimed.

### Store failure

The C27-B ledger remains pending in the still-open session until teardown
continues.

There is no retry loop.

### Post-write acknowledgement failure

C27-C already treats this as a split outcome:

- disk commit is authoritative;
- the stale write is never retried;
- process restart should bootstrap from the newly durable state.

C27-D propagates that failure instead of pretending the shutdown checkpoint was
fully acknowledged in-memory.

## No cadence

C27-D is **not** a periodic checkpoint service.

It adds no:

- scheduler hook;
- thread;
- timer;
- polling;
- background task;
- retry queue;
- threshold-based flush.

Long-running workers may therefore still accumulate a bounded C27-B pending
chain until graceful shutdown.

A later slice may introduce a separately reviewed periodic/threshold checkpoint
policy if needed.

## Relationship to sleep lifecycle

C27-D runs before deeper sleep/scheduler teardown.

That means the latest verified SelfState can become durable before normal
sleep-boundary processing finishes.

C27-D does not modify the C12/C13 sleep record and does not claim that SelfState
and SleepRecord are one filesystem transaction.

## Authority boundary

C27-D adds one narrowly scoped authority:

- invoke the already-authorized C27-C SelfState checkpoint once during graceful
  shutdown when its exact opt-in flag is enabled.

It adds no:

- model call;
- ThoughtEngine authority;
- Memory 4 write;
- Agent 3/tool execution;
- BodyRig/VoiceRig mutation;
- HTTP route;
- model-visible capability;
- scheduler ownership;
- automatic cognition authority.

The lifecycle seam itself remains:

```text
production_activation=false
```

and all deeper C27-A/B/C authority checks remain mandatory.
