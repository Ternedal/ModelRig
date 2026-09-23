# C30-G — Atomic episode boundary application

Status: draft, stacked on C30-F, `production_activation=false`.

C30-G lets the process-local C19 session owner apply one exact C30-F boundary decision without taking another clock sample or creating durable episode history.

## KEEP

`KEEP` returns the exact same active episode. No mutation is applied and the receipt contains no boundary/close refs.

## CLOSE_ONLY

C19 closes the exact active episode at the already-validated boundary anchor and keeps no active successor. The receipt binds the previous active episode ref, closed episode ref, signal ref and boundary anchor id.

## CLOSE_AND_ROTATE

C19 first closes the exact current episode, computes its canonical closed ref, and then opens one fresh empty episode at the exact same trusted boundary anchor with C30-F's next open reason.

The new episode has zero moments. The next accepted event/RUN may append at the same opening sample when appropriate under the C30-A first-moment rule.

## No parallel history store

The full closed episode is not retained in session state. C19 retains only the current active successor (if any) and the latest `EpisodeBoundaryApplicationReceipt`.

`closed_episode_contents_retained=false` is explicit in the receipt.

## Stale-decision protection

The C30-F decision must bind the canonical ref of the exact currently active episode. A decision created for another episode fails before mutation.

## Session API

`ProductionCognitiveSession.apply_episode_boundary(signal)` evaluates C30-F and applies C30-G atomically in process-local state. Passing no signal yields a receipted `KEEP`. The operation itself never samples the clock; callers must supply any trusted boundary signal/anchor.

## Authority boundary

C30-G adds no model call, persistent episode store, Memory 4 write, SelfState-store write, scheduler, timer, execution authority, goal activation or BodyRig/VoiceRig mutation.

## Qualification

Focused tests prove KEEP, rotate, close-only, stale-decision rejection, no additional session clock sample, successor continuation, latest-receipt behavior and close cleanup.

## Next slice

C30-H may derive bounded episode-closure evidence for optional Memory 4 experience-candidate review without automatically persisting an episode or granting Core durable-memory authority.
