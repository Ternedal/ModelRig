# T-032 — resource leases and concurrency limits

**Status:** process-local lease kernel implemented  
**Scheduler integration:** separate follow-up slice  
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

Leases are intentionally in memory. T-031 startup recovery marks interrupted
active campaigns failed, so a restarted Agent 4 process cannot silently resume
work while forgetting ownership. Durable or distributed leases require a
separate backend and fencing-token design.

## Next slice

The scheduler integration will:

1. resolve a resource vector for a campaign;
2. skip ready campaigns that cannot currently be admitted;
3. acquire before Agent 3 dispatch;
4. release on completion, cancellation or failed dispatch;
5. define pause/resume ownership semantics explicitly.
