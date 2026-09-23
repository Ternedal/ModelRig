# C27-I — Default-off exact-event SelfState checkpoint coupling

Status: draft, private-route integration only,
`production_activation=false`.

C27-I lets the private C22-C exact-event route reuse the single C27-G
policy-checkpoint service.

It preserves the exact-event cognition contract while making SelfState
persistence explicit and truthful for the whole route operation.

## Activation

Exact opt-in:

```text
KALIV_CONSCIOUSNESS_EVENT_CHECKPOINT_ENABLED=1
```

This gate is independent of:

- the C22-C exact-event route gate;
- the C27-G service gate.

With C27-I off, the route never reads
`app.state.consciousness_policy_checkpoint`.

## Preflight ordering

After loopback/body/session validation but before profile loading or model
invocation, C27-I performs:

```text
C27-G maybe_checkpoint_once()
```

when enabled.

If the service is missing or preflight checkpointing fails, the route returns
503 before:

- profile IO;
- ThoughtEngine invocation;
- required-event consumption.

This prevents unresolved durable continuity from being followed by a new
explicit cognitive RUN.

## Existing cognition path

After successful preflight the route keeps the existing C22-C behavior:

```text
fresh CognitiveProfile
-> session.step(required_event_id=...)
-> WAIT or RUN
```

There is no retry.

## WAIT

WAIT still means:

- required event not selected;
- zero model calls;
- zero cognitive state transition.

The route may nevertheless report a prior preflight checkpoint commit if C27-G
persisted an already-pending C27-B chain before the WAIT decision.

Cognition and persistence remain separately described.

## RUN

After a successful RUN, C27-I invokes C27-G once more.

With the default C27-E policy, the new `post_cycle_reduction` transition is
checkpoint-worthy, so the ordinary coupled path is:

```text
preflight HOLD/IDLE/COMMITTED
-> RUN
-> post-run CHECKPOINT
-> C27-C
-> C27-A atomic final replacement
-> C27-B reanchor
```

## Post-RUN persistence failure

If cognition succeeds but post-RUN persistence fails, the route returns:

```text
503 consciousness cognition completed but checkpoint failed
```

The route does not replay the cognitive operation.

The required event has already been consumed by the successful C18/C16 path.

A retry enters C27-I preflight first. If unresolved checkpoint pressure still
fails, the retry returns 503 before profile/model invocation.

This prevents an HTTP retry from becoming a second model call for the same
required event.

## Receipt

The existing exact-event receipt keeps all prior cognition fields.

C27-I adds bounded persistence observability:

- `checkpoint_enabled`;
- `checkpoint_evaluation_count`;
- `checkpoint_commit_count`;
- `checkpoint_last_outcome`;
- `checkpoint_last_pressure`;
- truthful `self_state_store_write_applied`.

The write flag is true exactly when at least one C27-F evaluation returned
COMMITTED during this request.

Gate-off defaults remain:

```text
checkpoint_enabled = false
checkpoint_evaluation_count = 0
checkpoint_commit_count = 0
checkpoint_last_outcome = null
checkpoint_last_pressure = null
self_state_store_write_applied = false
```

## Privacy / authority

C27-I does not expose:

- ThoughtProposal interpretation;
- hypotheses;
- raw chain-of-thought;
- Memory 4 contents;
- store payloads.

It adds no:

- background task;
- scheduler;
- timer;
- thread;
- retry;
- new model call beyond the existing C22-C RUN;
- Agent 3/tool execution;
- BodyRig/VoiceRig mutation.

The only new authority is the separately gated use of the already-mounted C27-G
checkpoint service around one private exact-event operation.
