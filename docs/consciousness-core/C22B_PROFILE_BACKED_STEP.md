# C22-B — Profile-backed private one-shot cognition step

Status: draft, loopback-only, default off, `production_activation=false`.

C22-B connects the operator-calibrated C22-A CognitiveProfile source to the
existing C19-B live cognitive session through one deliberately tiny production
control boundary.

The route is a control signal, not a prompt API.

## Activation

Exact opt-in:

```text
KALIV_CONSCIOUSNESS_STEP_ENABLED=1
```

Existing Consciousness Core, supervisor and live-session lifecycle prerequisites
still apply. This flag does not create those services.

## Surface

```text
POST /experimental/consciousness/step
Content-Length: 0
```

The request body must be empty.

The caller cannot supply:

- prompt or user text;
- model/provider name;
- CognitiveProfile values;
- event id;
- SelfState/WorldState/Workspace;
- Memory 4 refs;
- embodiment refs;
- tools/actions/authorities.

The current profile is loaded locally from C22-A on every explicit request.

## Flow

```text
loopback request
  -> exact C22-B gate
  -> empty-body validation
  -> existing live C19-B ProductionCognitiveSession
  -> fresh C22-A local profile load
  -> session.step(profile) exactly once
       -> IDLE: no pending event, 0 model calls
       -> WAIT: pacing prevents cycle, 0 model calls
       -> RUN: one bounded supervisor/cognitive cycle, exactly 1 model call
  -> bounded receipt
```

There is no retry, recursive loop, background task, timer or scheduler.

## Response boundary

The receipt contains only control-plane evidence:

- IDLE / WAIT / RUN decision;
- selected event ids for RUN;
- whether the ThoughtEngine was invoked;
- model-call count (0 or 1);
- canonical profile/config calibration references;
- SelfState / WorldState / Workspace refs;
- transition receipt ref when context changed;
- completed-cycle count;
- explicit authority=false facts.

Raw `ThoughtProposal`, hypotheses, interpretation, provider output, prompt text,
model error text and private inner-monologue content are never returned.

## Profile semantics

C22-B does not invent or cache capability values. Each request calls the C22-A
profile source afresh.

Therefore an operator can replace the configured model/calibration for a later
explicit step without rebinding:

- `self_id`;
- Person Revision;
- personality;
- durable memory.

Missing or invalid profile configuration returns a generic unavailable response.
There is no synthetic fallback profile.

## Authority invariants

Even a successful RUN receipt pins:

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

The live session may update its in-memory cognitive context through its existing
C19/C20/C18 contracts. C22-B itself owns no durable write or action authority.

## Failure behavior

- non-loopback -> 403 before body/profile IO;
- non-empty or malformed-length body -> 422 before profile IO;
- no live session -> 503;
- missing/malformed profile -> generic 503;
- session/single-flight conflict -> generic 409;
- ThoughtEngine/provider failure -> generic 502.

Provider exceptions and private cognition are not reflected into HTTP errors.

## Non-goal

C22-B does not automatically couple normal `/api/v1/chat` to cognition.
Such coupling changes latency and model-call behavior and remains a separately
reviewed slice.
