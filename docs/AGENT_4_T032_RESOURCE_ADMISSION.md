# Agent 4 T-032 — resource-aware scheduler admission

This slice composes the dormant T-030 lifecycle coordinator with the T-032
process-local resource lease kernel. It is additive: the original
`CampaignSchedulerService` remains unchanged, while
`ResourceAwareCampaignSchedulerService` provides explicit resource-aware
admission for hosts that opt into it.

## Admission contract

- The host still calls `dispatch_ready()` explicitly; there is no background
  scheduler, timer, thread, API route or automatic startup behavior.
- Ready campaigns are inspected in deterministic queue order.
- A campaign acquires its complete resource vector atomically before it leaves
  the queue.
- A resource-blocked campaign remains queued and does not block the next
  admissible campaign.
- The campaign is persisted as `RUNNING` before delegation to Agent 3.
- Persistence failure releases the lease and restores the campaign to the queue.
- Dispatch failure or an empty runtime reference fails the campaign closed and
  releases the lease.

## Lease lifecycle

- `PAUSED` releases resources.
- Resume reacquires the full vector before signaling the runtime and does not
  consume another attempt.
- A blocked resume fails without changing the durable `PAUSED` state.
- Cooperative cancellation retains resources until cancellation is
  acknowledged, preventing premature reuse while the delegated runtime may
  still be active.
- Cancellation acknowledgement, terminal completion and signal failure release
  the lease.
- `renew_resources()` extends a lease only for an active delegated lifecycle
  state.

## Validation

The existing `tests/worker_agent4_resources.py` gate now covers both the lease
kernel and scheduler admission. This avoids a new test-glob entry and therefore
requires no generated `CURRENT_STATE.md` change.

The gate includes head-of-line blocking, dispatch failure cleanup, pause/resume,
blocked resume, cancellation, completion and renewal scenarios. The complete
stack passes 53 Agent 4 tests locally.

## Deferred

Durable or distributed leases, fencing tokens, cross-process arbitration,
operator API mounting and automatic scheduling remain separate future slices.
