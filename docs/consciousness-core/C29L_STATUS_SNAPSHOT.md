# C29-L — Read-only continuity status snapshot

Status: draft, minimal diagnostic projection only, `production_activation=false`.

C29-L provides one on-demand read-only snapshot of the live continuity/recovery state for diagnostics or a future UI.

## Status values

- `NONE` — no wake continuity exists in this session.
- `REORIENTING` — C29-E continuity exists and C29-K is still reorienting.
- `ORIENTED` — exact C29-J completion has moved C29-K to oriented.

## Visible semantics

The snapshot exposes only adjudicated Core semantics and canonical Core refs: status, C29-E knowledge class, continuity-state ref, orientation-state ref, optional recovery-completion ref, direct-model-context-active, and reorientation-complete.

## Explicitly hidden

The snapshot does not expose raw WakeReceipt, SleepRecord, RuntimeLivenessWitness, last-known-alive witness/anchor refs, duration values, store paths, or persistence handles.

## Construction

`ProductionCognitiveSession.continuity_status` is derived on demand from the current C29-E/C29-J/C29-K process-local state. There is no second stored status value that can drift out of sync.

## Authority boundary

The snapshot fixes `model_calls=0`, `persistence_authority=false`, `durable_memory_write_authority=false`, `execution_authority=false`, `scheduling_authority=false`, `timer_authority=false`, and `production_activation=false`.

It creates no event, model call, route, timer, scheduler work, persistence or memory write.

## Qualification target

Focused tests prove NONE, REORIENTING and ORIENTED projections, zero model calls for status reads, and absence of raw lifecycle fields.

## Next slice

C29-M may define a stable adapter boundary for clients/diagnostics to consume C29-L later. That adapter must remain read-only and default-off and must not turn the status surface into a control plane.
