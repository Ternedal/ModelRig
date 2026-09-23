# C22-D — Opt-in normal-chat exact-event cognition coupling

Status: draft, default off, `production_activation=false`.

C22-D connects the authenticated normal-chat boundary to the exact-event C22-C
one-shot surface. It does **not** replace the normal chat response owner and does
not inject inner-monologue output into the chat prompt.

## Activation

Backend coupling requires both exact flags:

```text
KALIV_CONSCIOUSNESS_CHAT_ENABLED=1
KALIV_CONSCIOUSNESS_TURN_COGNITION_ENABLED=1
```

The worker surface is independently gated by:

```text
KALIV_CONSCIOUSNESS_EVENT_STEP_ENABLED=1
```

Core/supervisor/live-session/profile prerequisites retain their existing gates.

If turn cognition is off, C21 user-turn admission continues exactly as before
and no cognition step is requested.

## Flow

```text
authenticated POST /api/v1/chat
    |
    +-> read bounded final user turn
    +-> restore exact original request body
    |
    +-> C21 user-turn admission (best effort)
          |
          +-> replay/failure -> no cognition request
          |
          +-> new exact CognitionEvent id
                    |
                    +-> C22-C step-event (best effort, synchronous, once)
                              |
                              +-> WAIT: 0 model calls
                              +-> RUN: exactly 1 ThoughtEngine call
    |
    +-> existing Memory 4 / normal-chat handler
    +-> existing normal response model
```

The C22-C event id comes only from the already validated C21 admission receipt.
The client cannot supply a cognition event id through `/api/v1/chat`.

## Causal binding

Normal chat cognition is attempted only when the C21 receipt proves:

- this is not a replay;
- the world changed;
- one cognition event was newly queued;
- the event id has the canonical `cevt-` form.

The exact event id is then sent to C22-C. C22-C independently verifies that it is
still pending and, for RUN, canonically selected before ThoughtEngine invocation.

This prevents an older pending event from being mistaken for the current chat
turn.

## Failure isolation

All Consciousness work remains secondary to normal chat.

These conditions do **not** fail the user chat request:

- C21 admission unavailable/refused;
- C22-C route unavailable;
- profile unavailable/invalid;
- supervisor pacing conflict;
- provider/ThoughtEngine failure;
- malformed or authority-escalating C22-C receipt.

There is no retry. After one best-effort attempt, the existing chat handler owns
the response.

## Privacy / authority boundary

The backend C22-D client accepts only the strict C22-C receipt contract. It never
accepts or forwards:

- ThoughtProposal interpretation/hypotheses;
- raw inner monologue;
- provider error text;
- prompt material;
- model-selected actions.

The client Bearer token is not forwarded to the loopback worker.

Every accepted C22-C receipt must prove:

```text
automatic_repeat=false
internal_thread_created=false
internal_timer_created=false
self_state_store_write_applied=false
durable_memory_write_authority=false
execution_authority=false
scheduling_authority=false
production_activation=false
```

## Request preservation

C21/C22 processing occurs before normal chat, but the exact original
`/api/v1/chat` request bytes and content length are restored before the
existing Memory 4/chat handler receives the request.

C22-D therefore observes the turn without becoming prompt or response authority.

## Latency

When a required event receives RUN, C22-D adds one ThoughtEngine invocation
before the normal chat model response. The worker request timeout is bounded to
two minutes.

This is an explicit opt-in latency tradeoff. C22-D does not hide the model call
behind a goroutine, queue or later background completion.

## Non-goals

C22-D does not yet use inner cognition to alter the assistant response. A later
slice may define a safe, bounded semantic influence contract, but must not expose
or inject raw chain-of-thought.
