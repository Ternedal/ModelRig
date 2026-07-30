# A4-05 — health observations and watchdog policy

This slice defines pure, deterministic health assessment for delegated campaign
runtimes. It does not poll, signal, pause, fail or renew anything itself.

## Observation contract

`CampaignHealthObservation` binds one timezone-aware observation to a campaign
and lifecycle state. It may carry runtime start, heartbeat, progress and
resource-lease timestamps plus a consecutive health-failure count. Future or
naive timestamps and negative counters fail closed.

## Decision priority

For active delegated states (`RUNNING`, `PAUSING`, `CANCELLING`) the policy uses
this strict precedence:

1. missing or stale heartbeat → `FAIL_CLOSED`;
2. expired resource lease → `FAIL_CLOSED` with `UNSAFE` health;
3. consecutive failure threshold → `REQUEST_PAUSE`;
4. live heartbeat but stalled progress → `REQUEST_CHECKPOINT`;
5. lease inside renewal window → `RENEW_RESOURCES`;
6. otherwise → healthy, no action.

Non-active campaign states are `NOT_APPLICABLE`. The decision includes measured
ages and remaining lease time so an eventual watchdog executor can audit why an
action was selected.

## Safety

- no background thread, polling interval or timer;
- no campaign state mutation or persistence;
- no Agent 3 signal or resource-manager call;
- no message substring heuristics;
- exact threshold boundaries are inclusive and deterministic.

## Deferred

Observation storage, heartbeat ingestion, recurring watchdog execution,
operator override and escalation timing remain separate slices.
