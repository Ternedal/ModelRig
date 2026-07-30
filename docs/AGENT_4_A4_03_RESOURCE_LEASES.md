# A4-03 — resource leases and concurrency limits

**Status:** process-local lease kernel implemented  
**Scheduler integration:** included in a separate A4-03 slice  
**Cross-host coordination:** out of scope

## Purpose

Agent 4 needs an explicit admission boundary before campaigns can compete for
GPU slots, browser instances, Android devices or other bounded resources.
`InMemoryResourceLeaseManager` provides that boundary without starting any
worker or changing Agent 3.

## Guarantees

- fixed named capacities;
- positive integer resource vectors;
- atomic all-or-none acquisition across multiple resource types;
- no oversubscription under concurrent callers;
- one active lease per campaign;
- idempotent replay of the same campaign/request pair;
- conflict on a changed request for an already leased campaign;
- timezone-aware TTL expiration and lazy reclamation;
- explicit renew, release and release-by-campaign operations;
- immutable lease and snapshot values.

## Process boundary

Leases are intentionally in memory. A4-01 startup recovery marks interrupted
active campaigns failed, so a restarted Agent 4 process cannot silently resume
work while forgetting ownership. Durable or distributed leases require a
separate backend and fencing-token design.

## Scheduler admission

The A4-03 scheduler integration:

1. resolves a resource vector for a campaign;
2. skips ready campaigns that cannot currently be admitted;
3. acquires before Agent 3 dispatch;
4. releases on completion, cancellation or failed dispatch;
5. defines pause/resume ownership semantics explicitly.
