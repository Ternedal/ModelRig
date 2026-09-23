# C30-C — World and user-turn episode admission

Status: draft, stacked on C30-B, `production_activation=false`.

C30-C admits already-authoritative new world evidence and reported user turns into the current process-local experiential episode before cognition runs.

## Event-driven temporal anchoring

A new admission takes one trusted C18 runtime-clock sample only when the world reducer has produced a non-replay transition and before bridge publication. There is no timer or background cadence.

The episode moment anchor uses the canonical world-evidence ref as its event ref.

## Atomicity

C19 builds the prospective live state and prospective episode first. Bridge event admission remains the first publication side effect. Only after bridge admission and SelfState-ledger commit succeed are live state and episode published together.

If the bridge rejects the event, neither live WorldState/SelfState nor episode state is published.

## Replay

Idempotent world/user replay returns before any new clock sample or episode construction. It therefore adds no moment and queues no duplicate cognition.

## Moment mapping

`world_change` becomes `WORLD_EVIDENCE`. `user_turn` becomes `USER_TURN` and adds only `actor:user` as a participant ref. Raw user text remains in the authoritative reported WorldEvidence/WorldState path and is never copied into the episode moment.

## Opening before cognition

If no episode exists, a new event may open it before the first RUN.

An ordinary session opens with `SESSION_START`. A wake-backed session whose C29-K state is still `REORIENTING` opens with `WAKE_REORIENTATION`. If recovery had already completed, the fallback opening reason is `POST_WAKE_RECOVERY`.

The first later accepted RUN appends to the same episode rather than reopening it.

## Authority boundary

C30-C adds no model call, durable-memory write, SelfState-store write, scheduler, timer, execution, goal activation or BodyRig/VoiceRig mutation.

## Qualification

Focused tests prove new world admission, replay no-op, reference-only user turns, pre-RUN wake episode opening, first-RUN continuation, and rejection atomicity.

## Next slice

C30-D may admit existing `memory_recall`, `embodiment_change` and `prediction_error` attention admissions as reference-only moments under the same publish-after-queue and replay-safe rules.
