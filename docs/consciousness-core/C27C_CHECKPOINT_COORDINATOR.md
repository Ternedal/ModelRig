# C27-C — Explicit durable SelfState checkpoint coordinator

Status: draft, explicit trusted in-process commit only, production_activation=false.

C27-C is the first slice that connects the verified C27-B runtime transition
ledger to the C27-A atomic C14 store primitive.

It is deliberately caller-driven. There is no automatic checkpoint cadence in
this slice.

> **Durability is now possible, but it is not yet automatic.**

## Inputs

The coordinator owns one live ProductionCognitiveSession and one C14
SelfStateStore. The session provides the current C27-B checkpoint plan plus
the exact pending ordered SelfState values; the store provides the current
durable anchor.

## IDLE

If the session has no pending transitions, checkpoint_once() returns IDLE with
zero transitions and self_state_store_write_applied=false. The store is not
written.

## Pre-write verification

Before disk mutation C27-C verifies plan/state count, every canonical state ref,
the final state ref, the current durable store anchor, exact Self/Person/Person
Revision binding, and the revision-before value. A stale durable store fails
before write_chain().

## Durable commit

After preconditions pass, C27-C calls SelfStateStore.write_chain() with the
exact pending states. C27-A independently validates the full +1 chain and
performs one bounded fsync + atomic final replacement.

## Store receipt and ledger acknowledgement

The returned C27-A receipt must exactly match the unchanged C27-B plan:
previous durable ref, final ref, every transition state ref, revision before,
revision after, and transition count.

Only then may C19 acknowledge the receipt. C27-B verifies it again before
promoting the final state to the new in-memory durable anchor and clearing the
pending chain.

A successful result reports COMMITTED, self_state_store_write_applied=true,
ledger_reanchored=true and intermediate_history_persisted=false.

## Failures before store write

Plan/state/anchor mismatch performs zero store writes. A C27-A write failure
leaves the C27-B ledger pending; C27-C has no retry loop.

## Failure after store write

If the durable write succeeds but C19 ledger acknowledgement unexpectedly
fails, C27-C raises an explicit 'durable checkpoint committed but session
acknowledgement failed' error and never retries the write. The durable state is
already authoritative, so the safe recovery is to fail/restart the live
session and bootstrap from that new durable anchor.

## Atomicity claim

C27-C does not claim one transaction across C18 SupervisorState, C19 live
context, C27-B ledger and filesystem persistence. The only atomic operation is
C27-A's final SelfState file replacement.

## History semantics

Intermediate states are continuity evidence supplied to C27-A. Only the final
SelfState is persisted, so intermediate_history_persisted=false. Memory 4
remains the autobiographical-memory authority.

## Authority boundary

C27-C adds no automatic invocation, lifespan hook, feature flag, HTTP route,
scheduler, thread, timer, model call, Memory 4 write, Agent 3/tool execution or
BodyRig/VoiceRig mutation.

It does add one explicit trusted in-process SelfState persistence operation when
checkpoint_once() is deliberately called.

## Next slice

C27-D may decide when a production worker is allowed to invoke C27-C
automatically. That later slice must define the exact activation gate,
checkpoint timing, failure policy and shutdown ordering. C27-C makes none of
those policy decisions.
