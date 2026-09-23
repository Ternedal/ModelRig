# C21-B — Normal /api/v1/chat user-turn hook

Status: draft, end-to-end default-off through
`KALIV_CONSCIOUSNESS_CHAT_ENABLED=1`.

C21-B connects the existing authenticated Go normal-chat route to C21-A's
private worker user-turn admission surface.

It does not move chat ownership into Consciousness Core.

> **Normal chat still owns the response. Consciousness observes the turn.**

## Existing route

The public client route remains:

```text
POST /api/v1/chat
```

It remains:

- Bearer-authenticated;
- owned by the existing Go backend;
- routed through the existing Memory 4 read/write composition;
- streamed to the existing Ollama/model upstream exactly as before.

C21-B adds one pre-turn observer around that handler.

## Exact activation

The same flag governs both ends:

```text
KALIV_CONSCIOUSNESS_CHAT_ENABLED=1
```

With the flag off:

```text
handleConsciousnessChat
    -> handleMemory4Chat
```

immediately.

No request-body read, worker call, rewrite or extra model behavior is added on
that path.

## Enabled flow

For a bounded normal text turn:

```text
authenticated /api/v1/chat
        |
        v
bounded body probe
        |
        +-- unsupported/oversized? --> existing chat unchanged
        |
        v
exact final string user message
        |
        v
stable X-Request-ID + authenticated device id
        |
        v
server-bound SHA-256 turn id
        |
        v
loopback POST /experimental/consciousness/user-turn
        |
        v
strict C21-A receipt validation
        |
        v
restore exact original body
        |
        v
existing handleMemory4Chat
        |
        v
existing model response
```

The request body delivered to the existing chat owner remains the original
bytes.

## Stable turn identity

The backend logging middleware already assigns or accepts one
`X-Request-ID` per authenticated request, while auth middleware has already
bound the request to one concrete paired device.

C21-B derives the stable Core turn id as:

```text
chat-<sha256(authenticated_device_id + NUL + X-Request-ID)>
```

The raw `X-Request-ID` remains the downstream trace header. The derived
device-bound turn id is used as:

- C21-A `turn_id`;
- source-ref suffix;
- the basis of the worker's hashed turn ref and evidence identity.

This preserves retry identity for the same paired device while preventing two
different devices that happen to reuse the same client-supplied request id from
colliding in Consciousness Core.

## What is admitted

Only the final message is eligible, and only when:

- role is exactly `user`;
- content is a JSON string;
- content is non-blank;
- content is at most 2048 Unicode code points;
- request id is non-blank, control-character free and at most 128 code points;
- authenticated device id is present from the existing Bearer boundary.

Unsupported shapes are not rejected by C21-B. They simply bypass
Consciousness admission and continue through the existing chat implementation.

That preserves compatibility with richer Ollama request shapes.

## Exact text

C21-B checks `TrimSpace` only to decide whether the message is blank.

The admitted `user_text` itself is the exact original string, including
leading/trailing whitespace.

The model request also receives the exact original request body.

## Worker trust boundary

C21-B only calls the configured worker when its base URL is already classified
as loopback.

It sends:

```json
{
  "turn_id": "chat-<device/request hash>",
  "user_text": "<exact final user string>",
  "source_ref": "backend-chat:chat-<device/request hash>"
}
```

It does **not** forward the client's Bearer token.

The HTTP client reuses the reviewed Memory 4 no-redirect policy:

- configured destination must be loopback;
- a 30x response is returned as a refusal;
- the private user-turn body is never replayed to the redirect target.

## Receipt validation

A successful C21-A response is accepted only if it has the exact expected field
set and proves:

- expected schema;
- turn ref bound to the original request id;
- canonical SHA-256 evidence ref shape;
- `epistemic_status=reported`;
- `confidence=1.0`;
- positive observed sequence;
- `model_calls=0`;
- no SelfStateStore write;
- no durable-memory-write authority;
- no execution authority;
- no scheduling authority;
- no production activation.

For a new turn it must also prove:

- world changed;
- one cognition event was queued;
- cognition event id has canonical shape.

For a replay it must prove:

- world did not change;
- no new cognition event was queued;
- no cognition event id is returned.

Unknown or missing receipt fields fail validation.

## Failure isolation

Consciousness admission is secondary to the established normal-chat response.

These cases do **not** fail or rewrite chat:

- no worker;
- non-loopback worker;
- worker timeout;
- worker 4xx/5xx;
- redirect refusal;
- malformed response;
- oversized response;
- invalid/tampered receipt.

After one admission attempt, the existing normal chat handler runs.

There is no retry.

There is no queue.

There is no detached goroutine.

There is no background authority.

## Memory 4 coexistence

C21-B wraps `handleMemory4Chat`; it does not replace it.

Therefore the later existing logic still decides independently whether to:

- inject Memory 4 context;
- observe a completed turn for Memory 4;
- proxy directly to Ollama.

The Consciousness observer sees the original current user text before Memory 4
may inject reference context into the model request.

This prevents memory reference data from being mis-recorded as something the
user said.

## Authority boundary

C21-B grants no:

```text
automatic cognition
model call from the Consciousness hook
scheduler
background worker
retry loop
tool execution
Agent 3 execution
Memory 4 write authority
SelfStateStore write authority
BodyRig actuation
VoiceRig actuation
```

The established chat model call remains owned by the established chat path.

## Coverage boundary

C21-B covers only:

```text
POST /api/v1/chat
```

It does not claim canonical coverage for:

- RAG chat;
- tools chat;
- voice conversation;
- Agent 3 fallback turns;
- future Kaliv VR conversational surfaces.

Those can be connected through separately reviewed adapters rather than
silently assuming all user-facing routes have identical semantics.
