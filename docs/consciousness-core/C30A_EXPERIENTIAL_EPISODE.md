# C30-A — Experiential episode primitive

Status: draft, process-local reference structure only, `production_activation=false`.

C30-A introduces a bounded temporal container for a current lived/interaction episode without creating a second autobiographical-memory system.

> An episode organizes experience. It does not become durable memory merely because Core experienced it.

## Episode state

`ExperienceEpisodeState` binds one exact Self and Person Revision, one trusted C11 opening anchor, one runtime epoch, an ordered bounded list of `EpisodeMoment` records, and an optional trusted closing anchor.

An episode is either `ACTIVE` or `CLOSED`. It cannot cross a runtime epoch in C30-A; sleep/restart continuity remains owned by C29.

## Moment semantics

Moments are reference-only. Supported kinds are `COGNITIVE_RUN`, `WORLD_EVIDENCE`, `USER_TURN`, `MEMORY_RECALL`, `EMBODIMENT_CHANGE`, `PREDICTION_RESOLUTION`, `GOAL_TRANSITION`, and `RECOVERY_COMPLETION`.

Each moment carries only a canonical source ref, a trusted C11 `TemporalAnchor`, bounded salience, optional active-goal refs, and optional participant refs.

`raw_text_persisted=false` and `raw_chain_of_thought_persisted=false` are invariant.

## Temporal ordering

All moments must remain in the opening runtime epoch, advance temporal sequence strictly, and never move monotonic time backwards. Close evidence must occur at or after the final moment and cannot cross runtime epoch.

## Boundaries

Opening reasons: `SESSION_START`, `POST_WAKE_RECOVERY`, `EXPLICIT_BOUNDARY`.

Closing reasons: `FOCUS_SHIFT`, `GOAL_TRANSITION`, `DORMANCY`, `SESSION_CLOSE`, `EXPLICIT_BOUNDARY`.

C30-A does not decide automatically when a boundary occurs; that is a later policy/integration concern.

## Authority boundary

The primitive has zero model calls and no durable-memory, SelfState-store, execution, scheduling, timer, goal-activation, BodyRig or VoiceRig authority.

Memory 4 remains the only durable autobiographical-memory authority. `ExperienceCandidate` remains the existing bridge for reviewed/durable memory handoff; C30-A does not bypass it.

## Qualification

Focused tests prove empty active opening, ordered reference-only append, sequence/monotonic rejection, runtime-epoch isolation, canonical refs, terminal close semantics, and absence of raw text/chain-of-thought fields.

## Next slice

C30-B may attach one live episode to C19 and append only successfully accepted cognitive RUNs using the already-existing C18 trusted clock sample, adding no extra clock cadence or model call.
