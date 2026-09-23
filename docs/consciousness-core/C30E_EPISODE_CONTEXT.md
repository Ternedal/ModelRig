# C30-E — Bounded current-episode model context

Status: draft, stacked on C30-D, `production_activation=false`.

C30-E lets the replaceable ThoughtEngine observe a bounded reference-level projection of the current Core-owned experiential episode.

> The model may know the shape of the current episode. It does not become the authority that defines or remembers it.

## Projection

When a current episode exists, C15 may expose:

- canonical episode ref;
- episode phase and opening reason;
- total / evicted / retained moment counts;
- objective monotonic elapsed milliseconds from episode opening to the latest retained moment;
- at most 16 most recent moment projections.

Each recent moment contains only kind, canonical source ref, salience, participant refs, and temporal sequence.

## Explicitly excluded

The projection never includes raw user text, Memory 4 recalled text or ids, embodiment proposition text, prediction outcome text, model interpretation, hypotheses, response intent, or chain-of-thought.

`raw_text_included=false` and `raw_chain_of_thought_included=false` are explicit invariants.

## Exact identity

C15 requires the episode Self id and Person Revision to match the exact current SelfState before projection. Mismatch fails before ThoughtEngine invocation.

## Compatibility

When there is no current episode, C15 removes the optional `episode` field from the materialized model-context dictionary before `ThoughtEngine.think()`. The pre-C30 context shape therefore remains unchanged.

## Timing semantics

If authoritative user/world/semantic admission opened an episode before a RUN, that RUN may see the episode projection. If the first RUN itself opens the episode through C30-B, that first model call remains pre-episode and the next RUN can see the first `COGNITIVE_RUN` moment.

## Authority boundary

The projection fixes identity, persistent-state, durable-memory-write, execution and scheduling authority to false. It adds no model call, event, persistence, timer, scheduler work or BodyRig/VoiceRig mutation.

## Qualification

Focused tests prove recent-moment cap and elapsed time, no-episode wire compatibility, first user-turn episode visibility without text leakage, second-RUN visibility of the first cognitive moment, and foreign-episode rejection before the model.

## Next slice

C30-F may define deterministic episode-boundary policy from trusted lifecycle/goal/focus evidence so segmentation remains Core-owned rather than model-selected.
