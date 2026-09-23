# C30-F — Deterministic episode boundary policy

Status: draft, stacked on C30-E, `production_activation=false`.

C30-F defines who is allowed to decide that the current experiential episode ends or rotates. The replaceable ThoughtEngine is deliberately absent from that authority.

## Decisions

`KEEP` leaves the active episode untouched. `CLOSE_ONLY` ends it without opening a successor. `CLOSE_AND_ROTATE` authorizes a later owner to close the current episode and open a fresh process-local episode at the exact same trusted boundary anchor.

## Trusted signals

- `SESSION_CLOSE` from `core_lifecycle` -> `CLOSE_ONLY / SESSION_CLOSE`.
- `DORMANCY` from `core_lifecycle` -> `CLOSE_ONLY / DORMANCY`.
- `ACTIVE_GOAL_SET_CHANGED` from `goal_transition` -> `CLOSE_AND_ROTATE / GOAL_TRANSITION`.
- `FOCUS_SHIFT` from `core_focus_policy` -> `CLOSE_AND_ROTATE / FOCUS_SHIFT`.
- `EXPLICIT_BOUNDARY` from `operator_explicit` -> `CLOSE_AND_ROTATE / EXPLICIT_BOUNDARY`.

Authority is exact per signal kind. A focus signal cannot masquerade as operator authority and vice versa.

## Goal transitions

A goal-set boundary must contain unique previous/next active-goal refs and the sets must actually differ. Reordering the same set is not an episode boundary.

## Temporal integrity

The boundary signal carries one trusted C11 TemporalAnchor. It must remain in the episode runtime epoch and cannot precede the latest retained episode moment in sequence or monotonic time.

## Model boundary

`thought_engine_authority=false` and `raw_chain_of_thought_authority=false` are explicit signal invariants. No model proposal or chain-of-thought can directly segment experience.

## Pure policy

C30-F does not mutate the episode. The returned decision fixes `episode_mutation_applied=false`, `model_calls=0`, and all persistence/memory/execution/scheduling/timer authority fields false.

## Qualification

Focused tests prove KEEP, lifecycle close-only, actual goal-set rotation, focus/operator rotation, exact authority mapping, time/epoch rejection, no goal-data smuggling, and explicit denial of model segmentation authority.

## Next slice

C30-G may let C19 apply one validated boundary decision atomically, retaining a bounded closed-episode receipt/ref while opening the next empty episode on rotation.
