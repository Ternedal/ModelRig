# C31-G — Model-swap continuity qualification

C31-G proves that replacing the external ThoughtEngine can change Kaliv's
cognitive capability without changing who Kaliv is or moving authority into the
model adapter.

The qualification is intentionally side-effect free. It performs no model call,
model activation, persistence write, Memory 4 write, scheduling action or Agent 3
action. It compares two already-validated CognitiveProfile values and continuity
evidence before and after a swap.

A swap qualifies only when:

- the ThoughtEngine identity actually changes;
- at least one declared cognitive capability changes;
- `self_id` remains unchanged;
- Person ID and Person Revision remain unchanged;
- the durable-memory authority reference remains unchanged;
- the ordered continuity-reference set remains unchanged.

The resulting receipt explicitly records that the ThoughtEngine has no identity,
durable-memory, execution or scheduling authority. Production activation remains
false.

This extends the earlier experiments-only model-swap proof into the C31 lived
continuity contract while leaving SelfState, Person/Profile, Memory 4, Agent 3 and
the existing lifecycle/scheduler boundaries authoritative.
