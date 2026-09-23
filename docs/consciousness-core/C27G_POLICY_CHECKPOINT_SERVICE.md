# C27-G — Default-off production policy-checkpoint service

Status: draft, process-owned service only, `production_activation=false`.

C27-G mounts one process-owned C27-F
`PolicyDrivenSelfStateCheckpointAdapter` on production `app.state`.

It does not invoke checkpointing by itself.

> **One persistence service owner. Zero implicit persistence calls.**

## Activation

Exact opt-in:

```text
KALIV_CONSCIOUSNESS_POLICY_CHECKPOINT_ENABLED=1
```

Any other value is off.

With the flag off, the factory returns before:

- reading `app.state.consciousness_session`;
- constructing a C14 `SelfStateStore`;
- constructing C27-F;
- reading or writing durable SelfState.

## Construction

When enabled, C27-G requires an already-live C19
`ProductionCognitiveSession`.

It constructs:

```text
C19 live session
+ one C14 SelfStateStore object
-> one C27-F PolicyDrivenSelfStateCheckpointAdapter
```

Constructing the service performs no store read and no store write.

The adapter is exposed only as:

```text
app.state.consciousness_policy_checkpoint
```

for trusted in-process callers.

No route is mounted.

## Lifecycle ordering

C27-G is composed:

- inside C27-D graceful-shutdown checkpoint;
- outside C19 cognitive-session lifecycle.

The effective startup sequence is:

```text
C19 session opens
-> C27-G service is constructed/exposed
-> C27-D outer shutdown boundary becomes active
-> C25-C outer autonomous scheduler boundary becomes active
```

The shutdown sequence is:

```text
C25-C stops autonomous submissions
-> C27-D performs optional graceful-shutdown checkpoint
-> C27-G removes app.state checkpoint service
-> C19 closes the live session
```

That ordering guarantees the service never outlives the session it owns.

## No automatic checkpoint

C27-G never calls:

```python
maybe_checkpoint_once()
```

on startup, during serving, or during teardown.

It only owns the reusable adapter instance.

Automatic or post-operation invocation remains a separate reviewed authority.

## Relationship to C27-D

C27-D remains independent.

C27-D constructs and invokes its own explicit C27-C shutdown coordinator behind:

```text
KALIV_CONSCIOUSNESS_SELF_STATE_CHECKPOINT_ENABLED=1
```

C27-G does not replace or silently enable that safety net.

The two switches remain separate:

- C27-D grants graceful-shutdown persistence;
- C27-G grants availability of a trusted in-process policy-checkpoint service.

## Authority boundary

C27-G adds no:

- model call;
- ThoughtEngine authority;
- automatic checkpoint call;
- HTTP route;
- scheduler hook;
- thread;
- timer;
- polling;
- retry;
- Memory 4 write;
- Agent 3/tool execution;
- BodyRig/VoiceRig mutation.

It only owns one dormant in-process C27-F adapter.

## Next slice

A later production caller may use the single C27-G service after an already
successful state-changing operation.

That caller must define:

- which operation may trigger a checkpoint evaluation;
- whether persistence failure is fatal or degraded for that caller;
- whether the caller returns checkpoint metadata;
- how it avoids replaying the already-completed cognitive/world operation.
