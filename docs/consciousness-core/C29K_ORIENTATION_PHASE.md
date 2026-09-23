# C29-K — Explicit recovery orientation phase

Status: draft, process-local descriptive Core state only, `production_activation=false`.

C29-K makes the post-wake recovery phase explicit inside the live process.

## Phases

`REORIENTING` exists while the exact C29-I one-RUN window is active. `ORIENTED` exists only after the exact C29-J recovery completion receipt has been created.

## REORIENTING

The state binds the canonical C29-E continuity-state ref and knowledge class, keeps `direct_model_context_active=true`, has no completion ref/cycle id, and sets `reorientation_complete=false`.

## ORIENTED

The transition requires the matching consumed C29-I window plus matching C29-J completion receipt. The result binds the canonical recovery-completion ref and completed cycle id, sets `direct_model_context_active=false`, and `reorientation_complete=true`.

## Session integration

A wake-created `ProductionCognitiveSession` opens C29-K alongside C29-I. IDLE/WAIT leaves it unchanged. On the first successful RUN, C19 validates the next live state, consumed window, C29-J completion and C29-K orientation before publishing the process-local values together.

A normal no-wake session has no C29-K state.

## Non-goals

C29-K does not mutate RuntimeWorldState or SelfState. It does not add model context, a CognitionEvent, persistence, Memory 4 data, scheduler state, or UI state.

## Authority boundary

The state fixes `model_calls=0`, `self_state_store_write_applied=false`, `durable_memory_write_authority=false`, `execution_authority=false`, `scheduling_authority=false`, `timer_authority=false`, and `production_activation=false`.

## Qualification target

Focused tests prove strict REORIENTING -> ORIENTED transition, matching evidence, IDLE preservation, atomic first-RUN session transition, and close cleanup.

## Next slice

C29-L may expose a minimal read-only continuity/recovery status snapshot to diagnostics or a future UI surface without exposing raw lifecycle evidence or introducing control authority.
