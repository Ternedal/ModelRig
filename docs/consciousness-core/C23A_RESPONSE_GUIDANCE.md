# C23-A — One-shot outward response-guidance mailbox

Status: draft, in-memory only, `production_activation=false`.

C23-A preserves one very specific piece of a successful ThoughtProposal for
later outward response composition:

```text
response_intent
```

Nothing else from the inner monologue is eligible.

> **The Core may hand off how to answer. It does not hand off why it thought
> that way.**

## Why this exists

Before C23-A, C15/C16 retained only a bounded `interpretation` as a transient
`thought_result` workspace candidate.

The explicitly outward-facing `response_intent` field was validated in the
ThoughtProposal but then disappeared after the cycle.

That meant the cognitive cycle could think about a user turn without leaving a
safe, bounded handoff for the ordinary response model.

C23-A adds that handoff as a one-shot mailbox owned by the live C19-B session.

## Eligibility

Guidance is created only after a successful RUN and only when all of these are
true:

1. the validated ThoughtProposal has a non-blank `response_intent`;
2. exactly one selected cognition event has `kind=user_turn`.

Other selected non-user events may coexist.

If there are:

- zero selected user-turn events; or
- more than one selected user-turn event;

then no response guidance is created.

Core refuses to guess which user turn owns the outward instruction.

## Guidance envelope

The mailbox holds at most one strict `ResponseGuidanceEnvelope`:

```text
guidance_id
user_turn_event_id
cycle_id
proposal_ref
cognitive_profile_ref
person_revision
self_revision
text
source_field = thought-proposal.response_intent
```

The text is bounded to the existing ThoughtProposal `response_intent` maximum
of 4096 characters.

Its provenance binds the guidance to:

- one exact user-turn event;
- one exact cognitive cycle;
- one exact ThoughtProposal;
- one exact CognitiveProfile;
- one Person Revision;
- the resulting live SelfState revision.

## What is deliberately excluded

The envelope contains no:

- `interpretation`;
- hypotheses;
- candidate intentions;
- predicted outcomes;
- questions;
- memory queries;
- body intent;
- raw model response;
- hidden reasoning / chain of thought.

The contract fixes:

```text
contains_only_response_intent=true
raw_chain_of_thought_included=false
```

## Mailbox lifecycle

### Successful RUN

Every successful cognitive RUN replaces the mailbox.

If the new cycle creates valid response guidance:

```text
pending_response_guidance = new guidance
```

If the new cycle has no valid outward guidance:

```text
pending_response_guidance = None
```

This prevents an old reply instruction from silently surviving across a newer
cognitive moment.

### IDLE / WAIT

No new cognitive cycle occurred, so the mailbox remains unchanged.

### Session shutdown

The mailbox is cleared.

Nothing is persisted.

## One-shot consume

Trusted in-process code may call:

```python
session.consume_response_guidance(
    user_turn_event_id=<exact event id>
)
```

Semantics:

- no pending guidance -> returns `None`;
- exact event id -> returns the envelope and clears it;
- different event id -> fails closed and leaves the envelope untouched;
- closed session -> fails closed.

A guidance item therefore cannot be accidentally reused for a later user turn.

## Deterministic reference

`response_guidance_ref(...)` is the canonical SHA-256 reference of the entire
validated envelope.

Changing:

- text;
- cycle;
- proposal;
- profile;
- Person Revision;
- SelfState revision;
- bound user-turn event;

changes the guidance reference.

## Authority boundary

C23-A adds no:

- HTTP route;
- automatic model call;
- scheduler;
- thread;
- timer;
- persistence;
- SelfStateStore write;
- Memory 4 write;
- Agent 3 execution;
- tool execution;
- BodyRig actuation;
- VoiceRig actuation.

The envelope fixes:

```text
durable_memory_write_authority=false
execution_authority=false
scheduling_authority=false
production_activation=false
```

## What this unlocks

The safe sequence can now become:

```text
one canonical user turn
        |
        v
C21 reported evidence
        |
        v
C22 explicit cognitive RUN
        |
        v
ThoughtProposal.response_intent
        |
        v
C23-A one-shot guidance bound to exact user-turn event
```

The next slice can expose a private one-shot consume boundary for the Go backend.

That boundary can return the outward guidance text because it is explicitly
response-facing content, while continuing to hide every other ThoughtProposal
field.
