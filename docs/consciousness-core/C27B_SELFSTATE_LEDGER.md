# C27-B — Runtime SelfState transition ledger

Status: draft, process-local continuity ledger only,
`production_activation=false`.

C27-B teaches the live C19 session to retain the complete ordered SelfState
transition chain since the current durable C14 anchor.

It performs **no disk write**.

> **Before durability can be automatic, the runtime must be able to prove every
> SelfState revision it intends to checkpoint.**

## Why a ledger is necessary

C27-A can atomically checkpoint a complete `+1` state chain, but it deliberately
does not discover or authorize runtime transitions.

C19 owns the live context and therefore sees the transitions in the only place
where their exact ordering is unambiguous.

A representative runtime sequence is:

```text
durable N
-> C19 bootstrap N+1
-> C20 world evidence N+2
-> C18 supervisor orientation N+3
-> C16 post-cycle reduction N+4
```

C27-B records that exact sequence in RAM.

## Ledger bootstrap

Production `ProductionCognitiveSession` receives both:

- the exact durable SelfState read by the factory;
- the C19-A bootstrap context derived from that state.

The ledger requires the bootstrap state to be exactly:

```text
durable revision + 1
same self_id
same person_id
same person_revision
```

The first transition is:

```text
kind = session_bootstrap
source = canonical SessionBootstrapReceipt ref
```

Direct unit-test sessions that do not provide a durable anchor retain the
pre-C27 behavior and own no ledger.

## Captured transition kinds

C27-B records only actual SelfState-changing transitions:

```text
session_bootstrap
world_evidence
supervisor_orientation
post_cycle_reduction
```

The sequence source refs are receipt-bound:

- session bootstrap -> canonical session-bootstrap receipt ref;
- world evidence -> canonical WorldTransitionReceipt ref;
- supervisor orientation -> canonical SupervisorCycleReceipt ref;
- post-cycle reduction -> canonical CognitiveTransitionReceipt ref.

## Operations that do not create ledger entries

No SelfState transition is recorded for:

- generic CognitionEvent admission;
- wake-followup event admission;
- prediction-error event admission;
- Memory 4 recall event admission;
- embodiment-change event admission;
- IDLE supervisor step;
- WAIT supervisor step;
- exact world-evidence replay;
- response-guidance consume.

Those operations do not advance SelfState and therefore must not manufacture a
revision.

## Preflight / commit discipline

A transition is first prepared against the ledger's current exact state.

Preparation validates:

```text
revision == current + 1
self_id unchanged
person_id unchanged
person_revision unchanged
capacity available
source ref bounded/canonical input
```

For C20 admission, ledger preparation occurs **before** the C18 event queue side
effect.

Only after C18 accepts the event is the prepared transition committed to the
ledger and the prospective live World/Self state adopted.

For a cognitive step, C27-B reserves room for the two possible SelfState
transitions before entering C18 whenever pending events could yield a RUN.

This prevents bounded-ledger exhaustion from first being discovered after
supervisor side effects.

## RUN ordering

A successful RUN exposes both verified states in the existing
`SupervisorCycleResult`:

1. `oriented_self_state`;
2. C16 `reduction.next_self_state`.

C27-B appends them in exactly that order:

```text
supervisor_orientation
post_cycle_reduction
```

The live C19 state is adopted only after the existing C19 identity/world/
personality checks.

## Bound

The process-local ledger holds at most:

```text
128 pending SelfState transitions
```

When capacity is exhausted, state-changing work must wait for a separately
authorized checkpoint instead of dropping old transitions or skipping
revisions.

The ledger never silently truncates continuity.

## Checkpoint plan

The live session can expose a bounded
`RuntimeSelfStateCheckpointPlan` containing:

- durable anchor SelfState ref;
- final live SelfState ref;
- exact Self / Person / Person Revision;
- revision before/after;
- ordered transition metadata;
- transition count.

The plan explicitly states:

```text
self_state_store_write_applied = false
durable_memory_write_authority = false
execution_authority = false
scheduling_authority = false
production_activation = false
```

It is a plan, not proof of persistence.

## Exact states for C27-A

A trusted in-process caller may obtain the pending ordered SelfState objects
through the C19 checkpoint-state seam.

Those states are the exact values C27-A later validates again before one atomic
final store replacement.

C27-B does not itself call `SelfStateStore.write_chain()`.

## Checkpoint acknowledgement

The ledger can consume a successful C27-A
`SelfStateCheckpointReceipt`.

It verifies exact equality of:

- durable anchor ref;
- final state ref;
- every transition state ref;
- Self / Person / Person Revision;
- revision before/after;
- transition count.

Only then does it:

1. promote the final state to the new in-memory durable anchor;
2. clear the pending transition chain.

A mismatched receipt cannot reset the ledger.

## Authority boundary

C27-B adds no:

- disk persistence;
- automatic checkpoint;
- model call;
- HTTP route;
- model-visible tool;
- scheduler;
- thread;
- timer;
- Memory 4 write;
- Agent 3/tool execution;
- BodyRig/VoiceRig actuation.

## Next slice

C27-C may add a separately default-off production checkpoint coordinator that:

1. obtains the current C27-B plan + exact pending states;
2. calls C27-A `write_chain()`;
3. verifies the returned receipt against the unchanged plan;
4. marks the ledger checkpointed only after durable success.

That slice must define failure semantics explicitly and must not pretend C18,
C19 and disk storage are one transaction.
