# C17 — Bounded interruptible cognitive supervisor

Status: draft, isolated, `production_activation=false`.

C17 introduces the control plane that turns a C16 executive decision into at
most one next bounded cognitive-cycle transition.

It is deliberately **not** a background loop.

> **One adjudication in. At most one next-cycle candidate out.**

## Mapping

```text
ACCEPT_COGNITION -> COMPLETE
VERIFY           -> NEXT_CYCLE(reasoning_mode=verify)
REQUERY          -> NEXT_CYCLE(reasoning_mode=normal)
DECOMPOSE        -> NEXT_CYCLE(reasoning_mode=deep)
HOLD             -> PAUSE
explicit interrupt -> INTERRUPTED
budget exhausted   -> BUDGET_EXHAUSTED
```

An explicit interrupt always wins.

## Budget

The supervisor carries an explicit, caller-visible `SupervisorBudget`:

- total cognitive cycles;
- verification cycles;
- requery cycles;
- decomposition cycles.

The default budget is intentionally small:

```text
max_cycles=4
max_verify_cycles=2
max_requery_cycles=1
max_decompose_cycles=2
```

No internal retry counter is hidden from the caller.

`SupervisorProgress` is immutable and records consumed cycles and per-decision
consumption. A NEXT_CYCLE directive contains the exact
`progress_if_executed` value the caller should use only if that cycle actually
runs.

## Transition candidate

For VERIFY/REQUERY/DECOMPOSE, C17 deterministically derives:

- a new cycle ID;
- a control workspace candidate describing why another thought cycle is needed;
- a new bounded CognitiveWorkspace;
- a new in-memory PersistentSelfState candidate whose workspace ref points to the
  new workspace;
- the next reasoning mode.

The SelfState transition uses the existing Core-owned `advance_self_state`
function, preserving:

- `self_id`;
- `person_id`;
- exact Person Revision;
- personality binding;
- goals/intentions;
- affect;
- autobiographical reference.

Only the SelfState revision/workspace pointer advances.

## No implicit persistence

The transition is still only a candidate:

```text
persistence_committed=false
model_invoked=false
execution_authority=false
scheduling_authority=false
durable_memory_write_authority=false
production_activation=false
```

C17 never calls `SelfStateStore`.

A later runtime integration must separately decide whether to atomically commit
the candidate before invoking the next C15 cycle.

## Workspace control candidate

The next workspace includes a high-salience `thought_result` candidate with
provenance back to the exact C16 AdjudicationReceipt.

Examples:

- VERIFY: independent verification is required;
- REQUERY: a fresh bounded proposal is required;
- DECOMPOSE: the current task must be split into a more tractable cognitive step.

The control candidate is information for cognition, not a command to an external
executor.

## Bounded workspace behavior

The C2 limit remains 256 candidates.

If the previous workspace already contains 256 entries, C17 deterministically
retains the 255 highest-salience candidates and adds the new supervisor control
candidate. The ordinary C15 workspace selector then applies the existing
`max_active` bound.

## Binding checks

Before issuing any directive, C17 verifies that:

- C16 adjudication cycle/request/proposal matches the C15 cycle;
- adjudication workspace hash matches the C15 cycle receipt;
- supplied workspace hash matches the C15 cycle receipt;
- supplied SelfState hash matches the C15 cycle receipt;
- self/person binding matches;
- SupervisorProgress points at the current cycle.

Stale state/progress fails closed.

## What C17 does not do

C17 does not:

- call ThoughtEngine;
- invoke C15 automatically;
- schedule another cycle;
- create a thread/task/timer;
- write Memory 4;
- call Agent 3/tools;
- actuate BodyRig/VoiceRig;
- persist SelfState;
- create an unbounded recursive reasoning loop.

The next runtime slice may consume exactly one transition candidate, commit the
state transition under explicit Core authority, run exactly one C15 cycle, pass
it through C16, and return control to C17.
