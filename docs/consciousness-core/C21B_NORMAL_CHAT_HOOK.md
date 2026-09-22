# C21-B — Normal `/api/v1/chat` user-turn hook

Status: draft, end-to-end default-off through the existing C21 chat flag.

C21-B connects the authenticated Go normal-chat boundary to C21-A's private
worker admission surface without transferring chat ownership into the
Consciousness Core.

> **Normal chat still owns the response. Consciousness observes the incoming
> turn as a secondary bounded side effect.**

## Activation

C21-B reuses the same exact opt-in as C21-A:

```text
KALIV_CONSCIOUSNESS_CHAT_ENABLED=1
```

No fourth flag is introduced.

With the flag off, the backend immediately delegates to the existing
`handleMemory4Chat` path:

- it does not read the request body;
- it does not rewrite the request body;
- it does not contact the worker;
- existing Memory 4 and Ollama semantics remain the owner.

## Production boundary

The authenticated backend route remains:

```text
POST /api/v1/chat
```

The route now enters `handleConsciousnessChat`, which is only an outer
observer.

When enabled and the request contains a bounded final string user message:

1. read a bounded copy of the original request;
2. extract the exact final user string without trimming it;
3. restore the exact original request body;
4. validate the already-established backend `X-Request-ID`;
5. require the configured worker upstream to be loopback;
6. submit the user turn once to C21-A;
7. regardless of C21 admission success, continue through the pre-existing
   `handleMemory4Chat` owner.

The Consciousness Core does not generate the chat response in C21-B.

## Stable turn identity

The backend logging middleware already assigns or accepts one request id and
places it in `X-Request-ID`.

C21-B uses that value as the stable turn id when it is:

- non-empty;
- at most 128 runes;
- free of control characters.

The provenance ref sent to the worker is:

```text
backend-chat:<request-id>
```

The worker response must bind back to the exact turn id through:

```text
chat-turn:<sha256(turn-id)>
```

A malformed or oversized request id simply makes Consciousness admission
ineligible; normal chat continues unchanged.

## Bounded turn shape

Only the final message is eligible, and only when:

- role is exactly `user`;
- content is a JSON string;
- content is not blank after whitespace inspection;
- content is at most 2048 runes.

C21-B does not currently adapt multimodal content, tool chat, RAG chat or voice.

Those remain separate reviewed event sources.

The backend probe itself is bounded to 2 MiB. Requests outside the C21 adapter
shape are restored/delegated rather than rejected by C21.

## Privacy and worker transport

The C21-A worker call:

- is allowed only when the configured worker is loopback;
- uses the reviewed Memory 4 no-redirect HTTP client;
- never forwards the client's bearer token;
- forwards the bounded request id only as `X-Request-ID`;
- carries no assistant response;
- uses a two-second timeout;
- has no retry;
- has no detached goroutine;
- has no background queue.

A loopback worker cannot redirect the private user turn to another host.

## Strict worker receipt

C21-B accepts only the exact C21-A receipt shape.

It verifies:

- exact schema;
- exact hashed turn binding;
- canonical 64-hex WorldEvidenceEvent ref;
- `epistemic_status=reported`;
- `confidence=1.0`;
- positive observed sequence;
- `model_calls=0`;
- all write/action/scheduling/production authorities false;
- new admission shape:
  `world_changed=true`, event queued, valid `cevt-...`;
- replay shape:
  no world change, no new event.

Unknown/missing receipt fields fail validation.

## Failure isolation

Consciousness is secondary to the authenticated normal-chat contract in this
slice.

These failures therefore do **not** rewrite an otherwise-valid chat response:

- C21-A route absent;
- no live cognitive session;
- worker timeout/refusal;
- invalid/tampered C21 receipt;
- user-turn conflict;
- redirect response;
- unsupported request shape.

The backend makes at most one C21 admission attempt per incoming chat request,
then invokes the existing chat owner.

There is no retry loop.

## Memory 4 composition

C21-B sits outside the existing Memory 4 wrapper.

The sequence is:

```text
authenticated /api/v1/chat
        |
        v
C21-B observe original user turn
        |
        v
restore exact original request
        |
        v
Memory 4 R05/W04-B existing composition
        |
        v
Ollama/model response
```

Regression coverage proves that when both C21 and Memory 4 read context are
enabled:

- C21 receives the exact original user text;
- Memory 4 receives the restored original request;
- Memory 4 may perform its existing context injection;
- the model sees the normal Memory 4-wrapped user context.

## Authority boundary

C21-B adds no:

```text
response-generation authority
ThoughtEngine call
automatic cognitive step
scheduler
thread
timer
retry daemon
durable SelfState write
Memory 4 write authority
Agent 3 execution
tool execution
BodyRig actuation
VoiceRig actuation
```

C21-A still records the user input as `reported` evidence and only queues
attention.

## Next source adapters

C21-B deliberately covers only normal `/api/v1/chat`.

Future slices can separately review:

- RAG chat turns;
- tools chat turns;
- voice transcripts.

Keeping them separate avoids double-admission and makes each provenance boundary
explicit.
