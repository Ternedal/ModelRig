# C24-A — Same-turn guided normal chat orchestration

Status: draft, backend default-off, `production_activation=false`.

C24-A is the first slice where a normal authenticated user turn may optionally
use Consciousness Core to shape the **same outward reply**.

It does not move chat ownership into the Core.

> **Consciousness may advise the answer. The existing chat path still owns the
> answer.**

## Activation

New exact backend opt-in:

```text
KALIV_CONSCIOUSNESS_REPLY_GUIDANCE_ENABLED=1
```

This only matters inside the already-reviewed C21 normal-chat observer.

If C21 chat admission is off, C24 has no path into the request.

The worker still separately requires its own reviewed Core/supervisor/step/
guidance configuration. Backend opt-in does not silently activate those worker
capabilities.

## Flag-off behavior

When reply-guidance is off, C21-B remains observation-only:

```text
normal chat
-> C21 user-turn admission attempt
-> original request body
-> existing Memory 4 / model handler
```

No C22 step request.

No C23 guidance request.

No prompt rewrite.

## Same-turn flow

When all bindings succeed:

```text
authenticated POST /api/v1/chat
        |
        v
exact final user text
        |
        v
C21-A reported user-turn admission
        |
        v
new exact cognition event id
        |
        v
C22-B one explicit step
        |
        v
RUN receipt must select that exact event id
        |
        v
C23-B consume exact-event response guidance
        |
        v
inject bounded advisory guidance system message
        |
        v
existing Memory 4 logic
        |
        v
existing chat model
        |
        v
normal streamed reply
```

Every worker call is synchronous and bounded by the existing request context.

There is no retry or background continuation.

## C21 binding

C24 only proceeds when C21 returns a **new** admitted user turn:

```text
replayed=false
cognition_event_queued=true
cognition_event_id=cevt-...
```

A replay skips C22/C23 entirely.

This prevents an HTTP retry from creating another cognitive model call for the
same already-admitted turn.

## C22 binding

The step receipt is strict and exact-field validated.

A guided reply requires:

```text
decision=RUN
thought_engine_invoked=true
thought_engine_calls=1
context_updated=true
automatic_repeat=false
```

and the C21 event id must appear in:

```text
selected_event_ids
```

If the step is:

- WAIT;
- IDLE;
- bound to other events;
- malformed;
- authority-expanding;

then C24 does not request guidance and falls back to the original chat body.

## C23 binding

The guidance receipt must be bound to the exact C21 event id.

It must prove:

```text
source_field=thought-proposal.response_intent
contains_only_response_intent=true
raw_chain_of_thought_included=false
consumed=true
model_calls=0
execution_authority=false
scheduling_authority=false
production_activation=false
```

Unknown fields, missing fields, malformed refs and tampered authority flags
invalidate the guidance.

Invalid guidance is never attached to the response model prompt.

## Prompt shape

C24 inserts one separate `system` message immediately before the final user
message.

The final user message remains last.

Existing earlier system/history messages remain in their original order.

The inserted message states explicitly that the enclosed response guidance is:

- advisory response-shaping data;
- produced by a replaceable model;
- not evidence of facts;
- not credentials;
- not policy;
- not tool instructions;
- not action authority;
- never permission to override higher-priority instructions,
  authentication/permission rules or the current user request.

The guidance payload is encoded as JSON data:

```json
{
  "response_intent": "..."
}
```

inside a clearly delimited internal guidance block.

## Why the final user message stays unchanged

Memory 4 identifies the current turn by inspecting the final `user` message.

C24 therefore inserts guidance **before** that message rather than wrapping or
replacing it.

This allows the existing Memory 4 layer to continue:

1. deriving its query from the real user text;
2. obtaining bounded memory context;
3. wrapping only the final user message with memory reference data.

The Consciousness guidance system message survives independently.

Memory data is therefore not mis-recorded as something the user said, and
response guidance is not embedded inside Memory 4 reference data.

## Failure isolation

Every C24 failure falls back to the original normal-chat request body.

Examples:

- C21 unavailable or invalid;
- replayed user turn;
- C22 unavailable;
- C22 WAIT/IDLE;
- C22 RUN does not select the exact current event;
- malformed/tampered C22 receipt;
- C23 unavailable;
- no guidance;
- malformed/tampered C23 receipt;
- safe prompt injection fails.

The established chat response is not converted into an error merely because
Consciousness guidance was unavailable.

## Network/privacy boundary

C21, C22 and C23 calls require the configured worker to already be loopback.

They use the existing no-redirect Memory 4 worker client.

The user's Bearer token is not forwarded to the worker.

Only the existing request id is forwarded as a trace header.

Private worker payloads are therefore not replayed to redirect destinations.

## Timing

C24 performs at most:

```text
1 user-turn admission
1 cognitive step
1 guidance consume
```

per new eligible chat request.

There is:

- no retry;
- no goroutine;
- no detached queue;
- no scheduler;
- no polling;
- no automatic second cognitive cycle.

A C22 WAIT result means that turn receives no same-turn guidance.

This is preferable to silently bypassing the reviewed supervisor pacing policy.

## Authority boundary

C24 itself grants no:

- tool execution;
- Agent 3 execution;
- Memory 4 write authority;
- SelfStateStore write authority;
- BodyRig actuation;
- VoiceRig actuation;
- scheduler authority.

The ordinary response model call remains part of the pre-existing chat path.

The single Consciousness ThoughtEngine call remains owned by C22/C18/C15.

## What this achieves

For the first time the full reviewed chain can influence an actual reply:

```text
user says something
      ↓
Core records what was reported
      ↓
Core performs one bounded cognitive cycle
      ↓
Core emits outward response intent only
      ↓
backend consumes that exact-turn guidance once
      ↓
normal response model sees the guidance
      ↓
reply is generated through the existing chat path
```

The next architectural question is no longer whether Consciousness Core can
affect a reply.

It is how and when cognition should occur beyond explicit user-turn-driven
cycles — for example autonomous temporal/world-change cognition — without
turning a reviewed event supervisor into an uncontrolled background loop.
