# C24-A — Exact-turn guided normal chat orchestration

Status: draft, backend default-off, `production_activation=false`.

C24-A is the first slice on the current exact-event stack where a normal
authenticated user turn may optionally use Consciousness Core to shape the
**same outward reply**.

It does not move response ownership into Consciousness Core.

> **Consciousness may advise the answer. The existing chat path still owns the answer.**

## Activation

The backend requires all three exact opt-ins for the guided path:

```text
KALIV_CONSCIOUSNESS_CHAT_ENABLED=1
KALIV_CONSCIOUSNESS_TURN_COGNITION_ENABLED=1
KALIV_CONSCIOUSNESS_REPLY_GUIDANCE_ENABLED=1
```

The worker still independently requires its reviewed exact-event cognition,
profile/session and guidance-consume gates.

If reply guidance is off, the current C22-D behavior remains unchanged:
admission + optional exact-event cognition, then the original unmodified normal
chat request.

## Same-turn flow

```text
authenticated POST /api/v1/chat
        |
        v
C21 exact user-turn admission
        |
        v
new exact CognitionEvent id
        |
        v
C22-C exact-event step
        |
        +-- WAIT / failure --> original chat body
        |
        v
RUN must prove exact required event selected
        |
        v
C23-B consume response guidance for same event
        |
        v
strict receipt: response_intent only
        |
        v
insert advisory system guidance before final user
        |
        v
existing Memory 4
        |
        v
existing normal response model
```

There is no second cognitive cycle, retry, goroutine, detached queue or
background completion.

## Exact causal binding

Guidance is considered only when:

1. C21 returned a newly admitted non-replay event;
2. C22-C returned `RUN`;
3. `required_event_selected=true`;
4. the exact C21 event id appears in `selected_event_ids`;
5. C23-B returns guidance bound to that exact same event id.

Any mismatch falls back to the original chat body.

## Guidance boundary

The only model-derived content injected into normal chat is C23's bounded
`response_intent`.

The inserted system message states that guidance is:

- advisory response-shaping data;
- produced by a replaceable model;
- not evidence of facts;
- not credentials;
- not policy;
- not tool instructions;
- not action authority;
- never permission to override higher-priority instructions,
  authentication/permission rules or the current user request.

The guidance payload is JSON data in a clearly delimited internal block.

Raw interpretation, hypotheses, candidate intentions, predictions, memory
queries, body intent, provider output and hidden chain-of-thought never enter the
normal-chat prompt.

## Final user remains last

The guidance system message is inserted immediately before the final user
message. Existing earlier messages remain in order and the final user text is
unchanged.

This preserves Memory 4's current-turn semantics: Memory 4 may still identify
and wrap only the final user message while the Consciousness guidance remains a
separate system message.

## Failure isolation

Every guidance-path failure falls back to baseline normal chat:

- C21 unavailable / invalid / replay;
- C22-C unavailable;
- C22-C WAIT;
- C22-C wrong-event or malformed/tampered receipt;
- C23-B unavailable / no guidance;
- C23-B wrong-event or malformed/tampered receipt;
- guidance injection failure.

Consciousness availability therefore does not determine whether the user gets a
normal reply.

## Privacy / network

Worker calls use the loopback-only worker endpoint and existing no-redirect
client.

The user's Bearer credential is not forwarded. Only the request id is forwarded
as trace metadata.

## Authority

C24-A grants no:

- Agent 3 / tool execution;
- BodyRig / VoiceRig execution;
- SelfStateStore write;
- Memory 4 durable write;
- scheduler authority;
- automatic repeat.

The final response remains owned by the pre-existing normal chat model path.

`production_activation=false`.

## What this achieves

The reviewed chain can now influence a real same-turn response without exposing
the inner monologue:

```text
user turn
 -> reported world evidence
 -> exact-event bounded cognition
 -> response_intent projection only
 -> exact-event one-shot consume
 -> advisory response guidance
 -> existing response model
```

The next architectural work can focus on when cognition should happen outside
explicit user-turn-driven cycles, without turning the bounded supervisor into an
uncontrolled autonomous loop.
