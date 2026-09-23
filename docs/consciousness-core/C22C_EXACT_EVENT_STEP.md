# C22-C — Exact-event profile-backed one-shot cognition

Status: draft, loopback-only, default off, `production_activation=false`.

C22-C adds exact causal binding to the C22-B one-shot cognition boundary.

C22-B can safely advance the next pending cognitive work item. C22-C is for a
trusted caller that must prove cognition was attempted for one **specific**
pending CognitionEvent — primarily the exact user-turn event admitted by C21.

## Activation

Exact independent opt-in:

```text
KALIV_CONSCIOUSNESS_EVENT_STEP_ENABLED=1
```

Existing Core, supervisor and live-session gates remain independent prerequisites.

## Surface

```text
POST /experimental/consciousness/step-event

{
  "required_event_id": "cevt-..."
}
```

The body is bounded to 1 KiB and accepts exactly one field.

The caller cannot supply:

- prompt/user text;
- model/provider/profile;
- SelfState/WorldState/Workspace;
- Memory 4 or embodiment refs;
- tool/action/authority fields.

## Pre-model fail-closed checks

The required event id must:

1. match the CognitionEvent id schema;
2. already exist in the live supervisor pending-event set;
3. if the canonical plan is RUN, be among that plan's selected event ids.

All three conditions are checked before ThoughtEngine invocation.

This prevents a later normal-chat coupling from admitting event B but
accidentally running cognition for older event A.

## WAIT semantics

If the required event is pending but supervisor pacing returns WAIT:

- zero model calls occur;
- the event remains pending;
- live cognitive context is unchanged;
- the response says WAIT.

WAIT is not converted into a retry. The caller may choose to make another
explicit request later.

## RUN semantics

RUN means:

- the required event is canonically selected;
- exactly one ThoughtEngine call occurs;
- at most one C18/C19 live context transition is adopted;
- selected event ids are recorded in the response.

There is no recursion, retry, timer, thread or automatic repeat.

## Profile source

The CognitiveProfile is loaded fresh from C22-A on every request.

The HTTP caller cannot choose a profile. Missing/malformed local profile
configuration fails generically before cognition.

## Response privacy

The response carries:

- required event id;
- WAIT/RUN decision;
- selected event ids;
- profile/config refs;
- Self/World/Workspace refs;
- completed-cycle count;
- transition receipt ref for RUN;
- explicit authority=false facts.

It never returns ThoughtProposal interpretation, hypotheses, provider output,
prompt material or raw inner monologue.

## Failure behavior

- non-loopback -> 403 before body/profile IO;
- malformed/extra body field -> 422 before profile IO;
- no live session/profile -> 503;
- required event absent/unselected -> 409 before model call;
- provider failure -> generic 502 without provider error text.

## Authority

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

C22-C still does not connect normal `/api/v1/chat` automatically. That latency-
and model-call-changing coupling remains a separately reviewed next slice.
