# C22-D — Opt-in normal-chat one-shot cognition coupling

Status: draft, additive and default-off.

C22-D is the first slice that couples an authenticated normal user turn to one
actual Consciousness Core ThoughtEngine invocation.

It does so only under the stronger, explicit end-to-end opt-in:

```text
KALIV_CONSCIOUSNESS_CHAT_ENABLED=1
KALIV_CONSCIOUSNESS_TURN_COGNITION_ENABLED=1
```

> **Chat admission and cognition are separate powers. Both must be enabled.**

## End-to-end flow

For one eligible authenticated `POST /api/v1/chat` request:

```text
normal user turn
    |
    v
C21-B -> C21-A admission
    |
    +-- replay ---------------------------> no cognition step
    |
    +-- new exact cognition_event_id
             |
             v
       C22-C /step
             |
             +-- WAIT -> zero model calls
             |
             +-- RUN  -> exactly one C15 ThoughtEngine call
             |
             v
restore/continue normal chat ownership
             |
             v
existing Memory 4 / model response path
```

The normal chat handler still owns the assistant response.

C22-D does not inject ThoughtProposal content into that response.

## Gate combinations

### Chat flag OFF

The C21/C22 observer does nothing.

The request immediately follows the existing normal-chat path.

### Chat ON, turn cognition OFF

C21 user-turn admission occurs exactly as in C21-B.

No C22-C step request is made.

### Both ON

A successful **new** C21 admission may trigger one C22-C step for the exact
returned cognition event id.

A C21 replay does not trigger another step.

This prevents a retried/replayed backend request from causing a duplicate inner
cognitive cycle.

## Exact event binding

C21-A returns the exact newly queued:

```text
cevt-<32 lowercase hex>
```

C22-D does not derive or replace that event id.

It forwards exactly that id to:

```text
POST /experimental/consciousness/step
{"required_event_id":"cevt-..."}
```

C22-A inside the worker remains the authority that verifies the event is:

- valid;
- still pending;
- selected by the canonical supervisor plan.

The backend cannot force a different plan.

## Synchronous one-shot ordering

C22-D is intentionally synchronous.

For a newly admitted event:

1. C21 admission completes;
2. C22-C step completes or fails;
3. only then does normal chat response generation continue.

Regression coverage verifies that the ordinary chat model is not entered before
the cognition-step request has completed.

This ordering is important because the design goal is a turn-coupled inner
cognitive step, not an eventually-consistent background side effect.

## Latency tradeoff

A C22-C RUN performs one ThoughtEngine call **before** the normal chat response
model call.

That may materially increase turn latency, especially when a local model is
cold.

C22-D does not hide this cost.

The cognition worker HTTP client allows up to ten minutes, but the original
client request context still bounds the total operation and may cancel earlier.

This latency only exists when both stronger opt-ins are explicitly enabled.

## No replay cognition

A valid C21 replay receipt has:

```text
replayed=true
cognition_event_id=null
cognition_event_queued=false
```

C22-D makes no step call in this case.

A replay therefore remains:

- no WorldState update;
- no new attention event;
- no inner model call caused by C22-D.

## Strict step receipt

The backend accepts only the exact C22-C receipt field set.

It verifies:

- exact schema;
- exact required event binding;
- all selected event ids have valid shape;
- canonical profile/config refs;
- canonical SelfState/WorldState/Workspace refs;
- non-negative completed cycle count;
- automatic repeat false;
- all durable/action/scheduling/production authority false.

For WAIT:

```text
thought_engine_invoked=false
model_calls=0
context_updated=false
transition_receipt_ref=null
```

For RUN:

```text
thought_engine_invoked=true
model_calls=1
context_updated=true
transition_receipt_ref=cognitive-transition-receipt:<sha256>
required event appears in selected_event_ids
```

Unknown or additional receipt fields are rejected.

No ThoughtProposal field exists in the backend receipt type.

## Failure isolation

C22 cognition remains secondary to the already-established authenticated normal
chat contract in this slice.

These failures do not turn an otherwise-valid normal chat request into a chat
error:

- C22-C route unavailable;
- profile unavailable;
- required event no longer runnable;
- ThoughtEngine/provider failure;
- timeout;
- malformed or tampered step receipt.

The backend attempts the cognition step at most once and then continues through
the existing chat owner.

There is:

- no retry;
- no goroutine;
- no queue;
- no timer;
- no detached worker.

## Privacy

The C22 step request carries only:

```text
required_event_id
```

It does not resend the user text.

The client's bearer token is never forwarded to the worker.

The same no-redirect loopback client used by the Memory 4 boundary is reused.

The backend never receives:

- ThoughtProposal interpretation;
- hypotheses;
- candidate intentions;
- response intent;
- body intent;
- memory-query proposals;
- raw provider output;
- raw inner monologue.

## Response ownership

Even after a successful C22 RUN, C22-D simply continues to the pre-existing
normal chat path.

The current assistant answer is therefore **not yet informed by the generated
ThoughtProposal**.

This is deliberate.

Using internal cognition to alter the visible answer is a separate semantic
change and requires its own reviewed contract rather than smuggling private
ThoughtProposal text into the prompt.

## Authority boundary

C22-D grants no new:

```text
tool execution
Agent 3 execution
BodyRig actuation
VoiceRig actuation
SelfStateStore write
Memory 4 write
automatic retry
background scheduling
raw thought exposure
response-generation ownership
```

It only connects:

```text
new authenticated user-turn event
        ->
one exact private one-shot cognition step
```

under both explicit opt-ins.
