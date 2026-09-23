# C29-M — Post-recovery wake-context retirement

Status: draft, model-context projection only, `production_activation=false`.

C29-M closes a subtle continuity leak: after C29-I/K had completed wake reorientation, the explicit C29-F continuity field disappeared, but C19 wake artifacts still remained inside the authoritative WorldState/Workspace serialized to the ThoughtEngine.

## Rule

First accepted post-wake RUN remains fully wake-aware. After exact C29-K `ORIENTED`, later model calls retire only the wake-specific artifacts from a deep-copied model-context payload.

## Exact retirement targets

Using the private exact C29-E continuity-state ref and WakeReceipt ref, C29-M removes from the model-visible copy:

- WorldObservation entries whose `source_refs` contain either exact ref;
- WorkspaceCandidate entries whose `source_ref` equals either exact ref;
- selected candidate ids corresponding to removed candidates.

The explicit C29-F `continuity` field must already be absent after C29-I. If it is still present while retirement is requested, C29-M fails closed.

## What remains authoritative

C29-M does not mutate the C15 CognitiveContextPacket object, RuntimeWorldState, CognitiveWorkspace, SelfState, C29-E continuity state, C29-J completion receipt or C29-K orientation state.

ThoughtRequest refs continue to bind the authoritative Core state. The model-visible materialized context is a bounded projection controlled by Core.

## Runtime path

After C29-K is `ORIENTED`, C19 passes private retirement evidence through C18-B/C18-A to C15. C15 deep-copies the materialized context and retires wake artifacts immediately before the existing ThoughtEngine call.

## Semantics

- `REORIENTING`: no retirement; the first wake-oriented RUN sees wake artifacts and C29-F continuity.
- `ORIENTED`: later RUNs see neither C29-F continuity nor C19 wake observation/candidate artifacts.
- Core itself keeps all authoritative evidence.

## Authority boundary

C29-M adds no model call, event, scheduler, timer, route, persistence, Memory 4 write, SelfState mutation, execution authority or BodyRig/VoiceRig mutation.

## Qualification target

Focused tests prove first-RUN wake visibility, second-RUN retirement, authoritative Core evidence retention, selected-candidate cleanup, and refusal to retire before `ORIENTED`.

## Next step

With C29-M, the sleep/wake continuity path has a complete model-facing lifecycle: detect gap, orient once, complete recovery, retain Core evidence, and retire transient wake salience from later cognition.
