# C30-B — Live cognitive episode tracker

Status: draft, stacked on C30-A, `production_activation=false`.

C30-B attaches one bounded process-local C30-A episode to the live C19 session using accepted cognitive RUNs only.

## No independent clock

C30-B does not sample a new clock. Every `COGNITIVE_RUN` moment reuses the exact `SupervisorBridgeStep.clock_sample` that C18 already sampled for the RUN.

The moment TemporalAnchor therefore binds the same runtime epoch, monotonic time and clock sequence as the accepted supervisor transition.

## Lifecycle

A new session starts with no episode. IDLE/WAIT changes nothing. The first successful RUN opens one episode and appends the first `COGNITIVE_RUN` moment at the same trusted sample. Later successful RUNs append one moment each.

A wake-backed session uses `POST_WAKE_RECOVERY` as the opening reason; an ordinary session uses `SESSION_START`.

The episode is cleared when the process-local C19 session closes.

## Moment provenance

The moment `source_ref` is the canonical SupervisorCycleReceipt ref. Active goals are copied as refs only from the accepted next SelfState. If the accepted selected event set includes `user_turn`, the participant list contains only `actor:user`; no user text is copied.

Salience is the maximum salience of the selected canonical supervisor events for that RUN. The tracker does not ask the ThoughtEngine to score experience.

## Bounding

C30-A retains at most 128 recent moments while tracking total `moment_count` and `evicted_moment_count`, so a long-running session does not block cognition or become an unbounded process-local history store.

## Authority boundary

C30-B adds no model call, event, scheduler, timer, route, persistence, Memory 4 write, SelfState mutation, execution authority, or BodyRig/VoiceRig mutation.

## Cleanup hardening

The C30-B lifecycle patch also repairs the process-local close boundary so `_continuity_orientation` is cleared together with C29 continuity/recovery state. This restores the intended C29-K close invariant.

## Qualification

Focused tests prove IDLE no-op, first-RUN opening, exact clock-sample reuse, wake-backed opening reason, later RUN append, reference-only user participation, active-goal refs, and close cleanup.

## Next slice

C30-C may admit already-authoritative non-model events (world evidence, user turn, memory recall, embodiment and prediction resolution) as reference-only episode moments without creating duplicate cognition or new durable memory.
