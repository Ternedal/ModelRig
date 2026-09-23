# C29-H — Continuity-aware wake attention wiring

Status: draft, existing wake-attention wiring only,
`production_activation=false`.

C29-H consumes the pure C29-G salience recommendation at two already-existing
wake reorientation seams.

It creates no new event and no new cognition cadence.

## Wired seams

### C19 runtime bootstrap workspace

When C19 receives a WakeReceipt it already derives the exact C29-E continuity
state.

C29-H evaluates C29-G and uses its `attention_salience` for the existing
`wake-continuity` workspace candidate.

The candidate id, source ref and summary contract remain unchanged.

### C26 wake-followup event

`build_wake_followup_event()` now accepts an optional exact C29-E continuity
state.

When supplied it must match:

- Self id;
- Person Revision;
- canonical WakeReceipt ref.

Mismatch fails before event creation.

The existing deterministic wake-followup event id remains bound only to the
WakeReceipt. C29-H changes only its salience.

## Default salience

With exact continuity supplied:

```text
PLANNED_EXACT        -> 0.90
PLANNED_UNKNOWN      -> 0.95
UNPLANNED_BOUNDED    -> 0.98
UNPLANNED_UNBOUNDED  -> 1.00
```

A direct legacy C26 caller that does not supply continuity retains the historical
fallback:

```text
WAKE_FOLLOWUP_SALIENCE = 0.96
```

This preserves compatibility outside the new C19 continuity path.

## Production path

The production C19 factory:

1. bootstraps the live session;
2. obtains the exact process-local C29-E state from that bootstrap;
3. passes that exact state to the existing C26 wake-followup builder;
4. submits the same one wake-followup event as before.

No second event is introduced.

## What does not change

C29-H does not alter:

- wake event id;
- wake event kind;
- wake event source ref;
- WakeReceipt;
- SelfState;
- Memory 4;
- supervisor cadence;
- autonomous scheduler cadence;
- number of model calls.

The change is attention salience only.

## Authority boundary

C29-H adds no:

- automatic cognition authority;
- scheduler;
- timer;
- polling;
- retry;
- route;
- persistence;
- Memory 4 write;
- Agent 3 execution;
- BodyRig/VoiceRig mutation.

C29-G remains a recommendation, and existing C19/C26 owners remain responsible
for their existing objects.

## Qualification target

Focused tests prove:

1. legacy direct C26 without continuity stays at 0.96;
2. all four C29-E classes map to the exact C29-G salience in C26;
3. C19 uses the same four salience values for its existing wake candidate;
4. a continuity state bound to another WakeReceipt fails closed;
5. C26 still creates exactly one wake-followup event.

## Next slice

C29-I may add a bounded post-wake reorientation horizon in process-local state:
continuity influence may decay after the first accepted cognitive cycle instead
of silently remaining equally salient forever. Such decay must use existing
trusted cycle/clock evidence and must not create a timer or background task.
