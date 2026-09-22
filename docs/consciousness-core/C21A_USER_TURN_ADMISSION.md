# C21-A — Loopback reported user-turn admission

Status: draft, independently default-off, `production_activation=false`.

C21-A is the first reviewed production event-source adapter for Consciousness
Core.

It does not change normal chat yet. It gives the worker one private loopback
surface that can admit a canonical authenticated user turn into an already-live
C19/C20 cognitive session.

> **The Core learns that the user said something. It does not silently learn
> that what the user said is true.**

## Independent activation

The route is absent unless:

```text
KALIV_CONSCIOUSNESS_CHAT_ENABLED=1
```

This is deliberately separate from:

```text
KALIV_CONSCIOUSNESS_CORE_ENABLED=1
KALIV_CONSCIOUSNESS_SUPERVISOR_ENABLED=1
```

A live supervisor is not permission for normal chat to feed it.

When the chat flag is on but no live C19-B session exists, the route returns
`503 consciousness session unavailable`.

No identity or session is fabricated.

## Private HTTP boundary

The worker surface is:

```text
POST /experimental/consciousness/user-turn
```

Request:

```json
{
  "turn_id": "<stable backend turn id>",
  "user_text": "<bounded exact user text>",
  "source_ref": "<backend provenance ref>"
}
```

Bounds:

- turn id: 1..128 characters;
- user text: 1..2048 characters;
- source ref: 1..256 characters;
- complete request body: max 16 KiB.

The surface is independently loopback-only even when generic worker LAN access
has been enabled.

Loopback admission is checked before request-body parsing. A remote caller
cannot make this route parse private user text.

## Epistemic semantics

A new canonical user turn becomes one C20 WorldEvidenceEvent:

```text
subject_ref      = actor:user
proposition      = exact user text
confidence       = 1.0
epistemic_status = reported
source_refs      = [backend source ref]
```

`confidence=1.0` means:

> the authenticated turn boundary is fully confident that this exact text was
> reported by the user.

It does **not** mean the proposition is objectively true.

C20's canonical complete evidence ref is appended to WorldObservation
provenance as usual.

## Attention semantics

The same newly admitted evidence queues exactly one CognitionEvent:

```text
kind     = user_turn
salience = 1.0
source   = canonical WorldEvidenceEvent ref
summary  = exact bounded user text
```

The route performs no ThoughtEngine call.

A later explicit C19-B `step(profile=...)` may consume the event.

## Stable turn identity and sequencing

The evidence event id is derived from the stable `turn_id`, not from the text.

Therefore:

- same turn id + same exact payload = idempotent replay;
- same turn id + changed text = conflict;
- same turn id + changed source provenance = conflict.

Each new successfully admitted user turn receives a process-local monotonically
increasing `observed_sequence`.

The session retains a bounded mapping of recent turn ids to their assigned
sequence, so replay uses the exact original sequence.

A failed admission—for example while another cognitive step is in flight—does
not consume a sequence number.

The sequence map is bounded to 1024 user turns. This is intentionally larger
than C20's 512-observation live WorldState window; C21-A does not claim durable
cross-restart replay memory.

## Receipt privacy

The response does not echo `user_text`.

It returns only:

- hashed turn ref;
- canonical evidence ref;
- cognition event id when newly queued;
- world-changed/replayed/queued flags;
- fixed epistemic status and confidence;
- observed sequence;
- fixed authority-denial fields.

Validation and conflict errors are generic and do not reflect rejected private
text.

## Atomicity

C21-A reuses C20-B's atomic admission ordering:

```text
pure world reduction
-> prospective live state
-> supervisor event admission
-> adopt live state only if queue succeeds
```

If cognition is already in flight, the user-turn admission fails closed and the
live WorldState remains unchanged.

## Authority boundary

C21-A creates no:

```text
model call
automatic cognition
scheduler
thread
timer
polling loop
SelfStateStore write
Memory 4 write
Agent 3 execution
tool execution
BodyRig actuation
VoiceRig actuation
external/public route
```

Receipts retain:

```text
model_calls=0
self_state_store_write_applied=false
durable_memory_write_authority=false
execution_authority=false
scheduling_authority=false
production_activation=false
```

## Next slice

C21-B may connect the authenticated Go `POST /api/v1/chat` handler to this
worker surface using the already-reviewed Memory 4 loopback-client pattern.

That integration must remain separately default-off and preserve baseline chat
response semantics if Consciousness admission is unavailable.
