# C27-H — Default-off autonomous post-RUN SelfState checkpoint coupling

Status: draft, scheduler-owned integration only,
`production_activation=false`.

C27-H lets the existing C25-C scheduler-owned autonomous cognition bridge reuse
the single C27-G policy-checkpoint service.

It adds no scheduler, thread, timer or polling loop.

> **Before new autonomous cognition, unresolved checkpoint pressure must be
> handled. After a RUN, durability is evaluated immediately.**

## Activation

Exact opt-in:

```text
KALIV_CONSCIOUSNESS_AUTONOMOUS_CHECKPOINT_ENABLED=1
```

This switch does not replace the existing gates.

For the coupled production path to exist, the worker must already satisfy the
existing C25-C/C25-B gates and expose the C27-G service.

With this flag off, C25-C never reads:

```text
app.state.consciousness_policy_checkpoint
```

and behaves exactly as before.

## Required service

When the autonomous checkpoint flag is on and autonomous scheduler/cognition are
otherwise active, C25-C requires a live:

```text
PolicyDrivenSelfStateCheckpointAdapter
```

from C27-G.

Missing or invalid C27-G service fails bridge construction closed rather than
running autonomous cognition without the requested persistence coupling.

## Owner-loop flow

C25-C still uses the existing SchedulerService thread only as the cadence
source.

The actual operation is submitted to the FastAPI owner loop:

```text
scheduler thread
-> owner loop
-> preflight C27-F maybe_checkpoint_once()
-> C25-B tick_once()
-> if RUN: post-run C27-F maybe_checkpoint_once()
-> scheduler-thread status update
```

Both C27-F calls run on the same owner loop as the C19 cognitive session.

## Preflight checkpoint

Every coupled scheduler callback first evaluates the current C27-B plan through
C27-F.

Possible outcomes:

- IDLE: proceed;
- HOLD: proceed;
- COMMITTED: proceed from the newly reanchored ledger;
- failure: do **not** call C25-B in that callback.

This gives a failed prior post-RUN checkpoint a chance to recover before any new
autonomous model call.

## Post-RUN checkpoint

If C25-B returns RUN, C27-H invokes C27-F again immediately.

With the default C27-E policy, the freshly appended
`post_cycle_reduction` transition requests CHECKPOINT, so the normal successful
path is:

```text
RUN
-> C27-E completed_cognitive_cycle pressure
-> C27-C
-> C27-A atomic final SelfState replacement
-> C27-B reanchor
```

C25-B records its autonomous-cognition accounting before C27-H performs the
post-RUN checkpoint.

Persistence failure therefore cannot erase the fact that the model call already
occurred.

## Post-RUN failure

A post-RUN checkpoint failure does not replay cognition.

C25-C records:

- the completed RUN;
- one checkpoint failure;
- sanitized checkpoint stage/type;
- the bridge failure.

On the next scheduler callback, preflight checkpoint runs before C25-B.

If the failure happened before durable commit, that preflight may retry the
pending checkpoint.

If the failure was the C27-C post-write acknowledgement split, the durable store
has already advanced; the next preflight fails on the stale in-memory anchor
instead of repeating the write.

That blocks further autonomous cognition until process recovery/restart resolves
continuity.

## Receipt ownership

C25-B `AutonomousCognitionTickReceipt` remains unchanged.

It still describes the cognition tick only and therefore continues to report:

```text
self_state_store_write_applied = false
```

C27-H persistence observability belongs to the C25-C scheduler-bridge status,
not the cognition receipt.

## Bridge status

C27-H extends the existing scheduler status with:

- `checkpoint_enabled`;
- checkpoint evaluation count;
- checkpoint commit count;
- checkpoint failure count;
- last checkpoint outcome;
- sanitized last checkpoint error.

A post-RUN checkpoint failure may therefore coexist with:

```text
last_outcome = RUN
```

because cognition really did complete.

## Timeout / shutdown

C25-C retains its existing timeout, cancellation and single-flight behavior.

C27-H creates no retry loop.

During graceful process shutdown, C25-C still clears its SchedulerService hook
and drains/cancels any in-flight owner-loop callback before the outer lifecycle
continues to C27-D.

C27-D therefore remains the final separately gated graceful-shutdown checkpoint
safety net.

## Authority boundary

C27-H adds only one narrowly scoped authority:

- when its exact opt-in is on, C25-C may call the already-mounted C27-G
  checkpoint service before/after its own autonomous cognition callback.

It adds no:

- new cadence source;
- scheduler ownership;
- thread;
- timer;
- polling;
- HTTP route;
- model-visible capability;
- model call beyond the existing C25-B RUN;
- Memory 4 write;
- Agent 3/tool execution;
- BodyRig/VoiceRig mutation.

All existing C25 and C27 gates remain mandatory.
