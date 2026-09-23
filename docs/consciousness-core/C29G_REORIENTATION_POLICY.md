# C29-G — Continuity-driven reorientation policy

Status: draft, pure deterministic policy only,
`production_activation=false`.

C29-G turns the already-authenticated C29-E continuity class into a bounded
wake/reorientation attention recommendation.

It does not enqueue cognition.

> **Continuity may influence attention. It does not gain scheduler authority.**

## Default ordering

The default policy is monotonic:

```text
PLANNED_EXACT        -> ORDINARY              -> 0.90
PLANNED_UNKNOWN      -> UNCERTAINTY_ELEVATED  -> 0.95
UNPLANNED_BOUNDED    -> RECOVERY_ELEVATED     -> 0.98
UNPLANNED_UNBOUNDED  -> RECOVERY_MAXIMUM      -> 1.00
```

The numeric values are bounded salience recommendations, not urgency timers,
deadlines, probabilities or execution priorities.

## Why monotonic

A less certain or less orderly continuity boundary may deserve at least as much
reorientation attention as a more ordinary planned boundary.

The policy validator therefore rejects a custom policy where salience decreases
as continuity knowledge becomes less certain/unplanned.

## Input

C29-G accepts only an already-validated C29-E
`PostWakeContinuityState`.

It does not inspect:

- SleepRecord;
- WakeAcknowledgement;
- RuntimeLivenessStore;
- model output;
- Memory 4;
- body/voice state.

## Output

`ContinuityReorientationDecision` contains:

- canonical continuity-state ref;
- exact C29-E knowledge class;
- reorientation mode;
- attention salience;
- bounded reason code.

It fixes:

```text
model_calls = 0
self_state_store_write_applied = false
automatic_cognition_authority = false
durable_memory_write_authority = false
execution_authority = false
scheduling_authority = false
production_activation = false
```

## No automatic cognition

A C29-G decision is advisory Core policy only.

It cannot:

- create CognitionEvent;
- call ThoughtEngine;
- trigger the autonomous scheduler;
- force a supervisor RUN;
- persist SelfState;
- resume goals or open loops;
- write Memory 4;
- execute Agent 3;
- mutate BodyRig or VoiceRig.

A separate reviewed slice is required before any existing wake-attention seam
may consume the salience recommendation.

## Custom policy

An operator/test may provide another
`ContinuityReorientationPolicy` when all values remain in [0,1] and preserve
the monotonic ordering:

```text
planned_exact
<= planned_unknown
<= unplanned_bounded
<= unplanned_unbounded
```

This remains a pure function and adds no runtime configuration switch.

## Qualification target

Focused tests prove:

1. all four continuity classes map deterministically;
2. the default ordering is 0.90 / 0.95 / 0.98 / 1.00;
3. every authority field remains false;
4. mapping input is accepted as strict validated state;
5. a valid custom monotonic policy is honored;
6. a non-monotonic policy fails closed.

## Next slice

C29-H may wire C29-G into the existing C19/C26 wake-attention seams so
continuity changes only the salience of already-authorized wake reorientation,
without creating any new event or cognition cadence.
