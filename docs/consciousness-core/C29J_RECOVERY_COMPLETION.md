# C29-J — Process-local recovery completion receipt

Status: draft, diagnostic process-local receipt only, `production_activation=false`.

C29-J gives Consciousness Core an explicit boundary between wake reorientation still active and wake reorientation completed by the first accepted cognitive RUN.

The receipt is not autobiographical memory and is not persisted.

## Completion condition

C29-J completion exists only when all of these are true:

1. C29-E continuity exists;
2. the C29-I reorientation window is ACTIVE;
3. an explicit C18/C19 step results in RUN;
4. the cognitive cycle and C16 reduction validate;
5. the next live session state is valid;
6. the C29-I window can be consumed by that exact cycle.

IDLE and WAIT produce no completion receipt. A failed RUN before live-state adoption produces no completion receipt.

## Exact binding

The completion receipt binds Self id, Person Revision, canonical C29-E continuity-state ref, WakeReceipt ref carried by C29-E, C29-E knowledge class, exact first accepted cognitive cycle id, and exact accepted transition receipt ref.

The receipt therefore describes one specific wake -> reorientation -> accepted cognitive-transition chain.

## Atomic publication

C19 computes the candidate next live state, consumed C29-I window, and C29-J completion receipt before publishing them to the session. The process-local values are then adopted together.

This avoids a visible half-state where reorientation is already consumed but the completion evidence is missing.

## Stability

Once a completion receipt exists, later successful RUNs do not replace it. The receipt remains the proof of the first accepted post-wake reorientation cycle for the current process-local session.

## Session close

C19 clears the completion receipt on session close together with C29-E continuity state and C29-I reorientation window. No C29-J object crosses process restart.

## Authority boundary

The receipt fixes `completion_kind=FIRST_ACCEPTED_RUN`, `reorientation_complete=true`, `continuity_context_consumed=true`, `cognition_during_gap=false`, `crash_timestamp_claimed=false`, `model_calls=0`, and all persistence/execution/scheduling/timer authority fields to false.

The `model_calls=0` field describes the receipt primitive itself. The receipt binds an already-completed cognitive cycle; it does not authorize or invoke that cycle.

C29-J adds no scheduler, timer, event, polling, retry, route, store, Memory 4 write, Agent 3 execution, or BodyRig/VoiceRig mutation.

## Qualification target

Focused tests prove:

1. ACTIVE windows cannot produce a completion receipt;
2. a consumed exact matching window can;
3. IDLE makes zero model calls and produces no completion;
4. first successful RUN publishes a receipt bound to its exact cycle and transition;
5. later RUNs do not overwrite the first completion;
6. close clears the process-local completion.

## Next slice

C29-K may project the completion boundary into deterministic session/world orientation so Core can explicitly distinguish currently reorienting from reorientation completed without exposing additional raw lifecycle internals to the model or creating a new cognition event.
