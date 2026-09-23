# C27-J — Default-off user-turn/world SelfState checkpoint coupling

Status: draft, private user-turn integration only,
`production_activation=false`.

C27-J lets the private C21-A reported user-turn admission route reuse the single
C27-G policy-checkpoint service.

This makes C27-E's world-only transition threshold reachable through the normal
reported user-turn path, without waiting for a cognitive RUN or graceful
shutdown.

## Activation

Exact opt-in:

```text
KALIV_CONSCIOUSNESS_TURN_CHECKPOINT_ENABLED=1
```

This gate is independent of the C21-A route gate and the C27-G service gate.

With C27-J off, the route never reads
`app.state.consciousness_policy_checkpoint`.

## Preflight

After loopback/body/session validation but before world mutation, C27-J invokes:

```text
C27-G maybe_checkpoint_once()
```

If the service is unavailable or checkpoint preflight fails, the route returns
503 before:

- C20 world mutation;
- C18 event admission;
- C21 reported-turn sequence consumption.

The user-turn operation itself has not happened.

## New user turn

After successful preflight, the existing C21 path remains authoritative:

```text
submit_reported_user_turn()
-> reported C20 world evidence
-> SelfState world binding +1
-> pending user_turn CognitionEvent
```

C27-J does not alter C21 sequence or replay semantics.

## Post-admission checkpoint

When the C21 result reports:

```text
world_changed = true
```

C27-J evaluates the C27-G policy-checkpoint service again.

With the default C27-E policy, small world-only batches may return HOLD.

When the pending transition count reaches the policy threshold, the path becomes:

```text
new reported world transition
-> C27-E CHECKPOINT
-> C27-C
-> C27-A atomic final SelfState replacement
-> C27-B reanchor
```

## Replay

An exact C21 replay has:

```text
world_changed = false
cognition_event_queued = false
```

C27-J performs the preflight evaluation but deliberately skips the second
post-admission evaluation because no new SelfState transition was created.

The existing C21 turn ledger remains the replay authority.

## Post-admission persistence failure

If the world transition/event admission succeeds but persistence then fails, the
route returns:

```text
503 consciousness user-turn admitted but checkpoint failed
```

It does not repeat the user-turn operation internally.

A retry with the same turn id first encounters C27-J preflight.

If unresolved pressure still cannot be checkpointed, the retry returns 503
before C21 admission.

If persistence later succeeds, the existing C21 replay guard prevents a second
world revision or duplicate user-turn event.

## Receipt

The existing C21 receipt retains:

- turn/evidence refs;
- world-changed/replay state;
- event id/queued state;
- reported epistemic status;
- sequence;
- zero model calls.

C27-J adds:

- `checkpoint_enabled`;
- evaluation count;
- commit count;
- last checkpoint outcome;
- last checkpoint pressure;
- truthful `self_state_store_write_applied`.

Gate-off values remain zero/null/false.

## No cognition authority

C27-J never calls ThoughtEngine.

A user-turn route request may queue a cognition event exactly as C21 already
does, but C27-J itself only surrounds the world-admission operation with
persistence policy.

## Authority boundary

C27-J adds no:

- model call;
- scheduler;
- thread;
- timer;
- polling;
- background retry;
- Memory 4 write;
- Agent 3/tool execution;
- BodyRig/VoiceRig mutation.

Its only new authority is the separately gated use of the existing C27-G
checkpoint service around C21-A world mutation.
