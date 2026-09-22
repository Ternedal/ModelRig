# C23-B — Private one-shot response-guidance consume

Status: draft, independently default-off, `production_activation=false`.

C23-B exposes only C23-A's already-isolated outward `response_intent`
projection to trusted backend code.

It does not expose the ThoughtProposal.

> **The backend can consume how to answer once. It cannot fetch the inner
> monologue.**

## Independent activation

The route is absent unless:

```text
KALIV_CONSCIOUSNESS_GUIDANCE_ENABLED=1
```

This is separate from Core, supervisor, chat and explicit-step activation.

## Private route

```text
POST /experimental/consciousness/response-guidance/consume
```

Strict request:

```json
{
  "user_turn_event_id": "cevt-..."
}
```

No other field is accepted.

The request cannot supply:

- guidance text;
- proposal refs;
- profile refs;
- SelfState;
- WorldState;
- model/profile selection;
- execution intent.

## Loopback boundary

The route remains loopback-only regardless of generic worker LAN settings.

Loopback admission occurs before body parsing or session inspection.

A remote caller therefore cannot make the route deserialize private input or
touch the live guidance mailbox.

## Consume semantics

### No pending guidance

Returns:

```text
404 response guidance not available
```

### Wrong event id

Returns:

```text
409 response guidance belongs to another user turn or session
```

The mailbox remains unchanged.

### Exact event id

The route consumes C23-A guidance exactly once and returns a bounded receipt.

The mailbox is cleared before the response leaves the route.

A second request for the same event therefore returns 404.

## Response surface

The successful receipt may contain only:

- canonical guidance ref;
- guidance id;
- bound user-turn event id;
- cycle id;
- proposal ref;
- cognitive-profile ref;
- Person Revision;
- SelfState revision;
- outward guidance text;
- fixed source-field marker;
- authority-denial metadata.

The text is exactly the bounded C23-A outward guidance derived from
`ThoughtProposal.response_intent`.

It is not a general ThoughtProposal projection.

## Fields that remain inaccessible

C23-B cannot return:

- interpretation;
- hypotheses;
- candidate intentions;
- predictions;
- questions;
- memory queries;
- body intent;
- raw provider response;
- hidden reasoning / chain of thought.

The receipt fixes:

```text
contains_only_response_intent=true
raw_chain_of_thought_included=false
```

## Error privacy

Invalid JSON, unknown fields, malformed event ids and oversized bodies produce a
generic validation error.

Rejected private body values are not reflected in the response.

Lifecycle/session failures are also generic.

## Authority boundary

Guidance consumption performs no model call.

Every successful receipt fixes:

```text
model_calls=0
self_state_store_write_applied=false
durable_memory_write_authority=false
execution_authority=false
scheduling_authority=false
automatic_repeat=false
production_activation=false
```

C23-B adds no:

- scheduler;
- thread;
- timer;
- retry loop;
- background task;
- SelfStateStore write;
- Memory 4 write;
- Agent 3 execution;
- tool execution;
- BodyRig actuation;
- VoiceRig actuation.

## Production chain now possible

The separately reviewed pieces can now form:

```text
authenticated user turn
        |
        v
C21 reported evidence + user_turn event
        |
        v
C22 explicit cognitive step
        |
        v
C23-A one-shot outward guidance
        |
        v
C23-B exact-event consume
```

The next backend slice can bind the C21 event id from the original chat
admission receipt to C23-B.

That future integration must still decide when to run C22 and how to inject the
consumed guidance into the existing response-model prompt without changing
Memory 4 or authentication ownership.
