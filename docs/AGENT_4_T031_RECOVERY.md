# T-031 — startup recovery

**Status:** dormant recovery contract implemented  
**Runtime reconciliation:** fail-closed placeholder  
**Checkpoint payload store:** next T-031 slice

## Recovery policy

A host explicitly calls `CampaignSchedulerService.recover()` during composition.
The service performs no startup work merely by being imported.

| Persisted status | Recovery action |
|---|---|
| `QUEUED`, `SCHEDULED` | Rehydrate the deterministic in-memory queue |
| `PAUSED` | Retain durable pause without dispatching |
| `RUNNING`, `PAUSING`, `CANCELLING` | Persist `FAILED` with an interruption reason |
| `SUCCEEDED`, `FAILED`, `CANCELLED` | Retain terminal record unchanged |

The active-state policy is deliberately conservative. Until an Agent 3 adapter
can prove that a delegated runtime is alive and bound to the same campaign,
Agent 4 must not assume that work is still running after its own process restarts.

## Idempotency

Calling recovery twice does not duplicate queue entries. A second scan reports
`already_queued` for work already restored. Terminal and paused records remain
unchanged.

## Audit events

Requeued and paused campaigns receive a `RECOVERED` event. Interrupted active
campaigns receive ordered `RECOVERED` and `FAILED` events, with
`phase=startup_recovery`.

Event history remains in memory in this slice. Persistent timeline/evidence is
planned for T-035.
