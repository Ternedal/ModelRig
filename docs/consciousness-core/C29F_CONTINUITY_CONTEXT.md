# C29-F — Bounded continuity projection into C15 model context

Status: draft, bounded advisory model context only,
`production_activation=false`.

C29-F lets the replaceable ThoughtEngine receive the already-adjudicated C29-E
continuity classification without receiving raw sleep/liveness lifecycle
internals and without becoming authority over continuity.

> **The model may observe continuity evidence. The model does not decide what
> continuity is.**

## Input authority

C29-E remains the Core-owned source for the process-local continuity
classification.

C29-F accepts only an authenticated `PostWakeContinuityState` that matches the
current:

- Self id;
- Person Revision.

Mismatch fails before the model call.

## Model-visible projection

The C15 context packet may contain:

```text
continuity:
  continuity_state_ref
  dormancy_kind
  knowledge
  exact_offline_duration_ms
  offline_duration_upper_bound_ms
  duration_confidence
  cognition_during_gap = false
  crash_timestamp_claimed = false
  identity_authority = false
  persistent_state_authority = false
  durable_memory_write_authority = false
  execution_authority = false
  scheduling_authority = false
  production_activation = false
```

The four knowledge values remain:

```text
PLANNED_EXACT
PLANNED_UNKNOWN
UNPLANNED_BOUNDED
UNPLANNED_UNBOUNDED
```

The projection never carries both exact duration and upper bound.

## Deliberately excluded

The ThoughtEngine does **not** receive from this projection:

- SleepRecord;
- WakeAcknowledgement;
- raw WakeReceipt;
- RuntimeLivenessWitness;
- last-known-alive witness ref;
- last-known-alive temporal anchor ref;
- raw liveness anchor data;
- crash timestamp;
- persistence handles or store paths.

The canonical C29-E state ref is enough to bind the bounded projection to
Core-owned evidence.

## Compatibility

When a live session has no C29-E continuity state, the new optional field is
removed from the context dictionary before `ThoughtEngine.think()`.

This preserves the pre-C29-F no-continuity model-context shape rather than
adding a new `continuity: null` token to every ordinary cycle.

## Runtime path

Production flow:

```text
C19 ProductionCognitiveSession.continuity_state
-> C18-B ProductionSupervisorBridge.step()
-> C18-A CognitionSupervisorKernel.run_once()
-> C15 CognitiveCycleCoordinator.run()
-> bounded ContinuityContextProjection
-> ThoughtEngine context only
```

The older direct C17 wake-first-cycle path derives the same C29-E state from the
authenticated WakeReceipt and passes the same bounded projection to C15.

## ThoughtRequest

C29-F does not change the C3 `ThoughtRequest` wire contract.

The projection is model context, not a new model-controlled request authority.
The exact live WorldState already contains wake continuity provenance from C19,
including the canonical C29-E state ref.

## No authority transfer

The projection explicitly fixes all authority fields false.

The ThoughtEngine still cannot:

- rewrite SelfState;
- classify a crash as planned sleep;
- change exact/upper-bound duration semantics;
- persist memory;
- schedule work;
- execute tools;
- mutate BodyRig or VoiceRig.

Any ThoughtProposal remains subject to the existing C16/C17/C18 adjudication
and execution boundaries.

## Qualification target

Focused tests prove:

1. no continuity preserves the old engine context shape with no new null key;
2. `UNPLANNED_BOUNDED` exposes only the bounded classification/upper bound;
3. raw liveness witness and anchor refs do not reach the model projection;
4. `PLANNED_EXACT` exposes exact duration but no upper bound;
5. foreign continuity state fails before the model call;
6. the full production C19 -> C18 -> C15 path reaches the model with exactly one
   bounded projection.

## Next slice

C29-G may let deterministic executive policy use C29-E continuity knowledge
directly for bounded reorientation policy—for example treating a long or
uncertain unplanned gap as higher reorientation salience—without allowing the
model or continuity state itself to schedule cognition.
