# Consciousness Core C14 — persistent runtime SelfState

C14 turns the C1 SelfState contract into an atomic model-independent runtime
continuity authority.

Bootstrap is explicit and review-bound. The code does not invent a self from a
prompt, display name or model identity. A bootstrap authority binds an explicit
stable self_id to one stable person_id and approved active Person Revision.

Normal state advancement can change current world/workspace/personality-state
references, goals, intentions, affect, uncertainty and last-experience reference.
It has no surface for changing self_id, person_id or Person Revision.

Changing Person Revision uses a separate explicit rebind authority tied to the
same self/person and exact old/new approved revisions.

SelfState persistence is one bounded SHA-256-bound JSON envelope written
atomically under the Kaliv data root. It is current continuity state, not an
autobiographical Memory 4 store.

This slice has no production entrypoint wiring and no model/tool/scheduler/action
authority.

production_activation=false.
