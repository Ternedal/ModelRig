# Agent 4 foundation contract

**Milestone:** A4-01 foundation  
**Status:** dormant implementation  
**Runtime activation:** none  
**Agent 3 contract changes:** none

## Purpose

Agent 4 turns isolated Agent 3 executions into durable campaigns. The foundation establishes the data and boundary contracts needed before any host cadence or operator API is allowed to run.

## Invariants

1. **Dormant by default.** Importing Agent 4 creates no thread, task, file, socket, schedule or Agent 3 execution.
2. **Agent 3 remains authoritative for execution.** Agent 4 delegates through `CampaignExecutor`; it does not reach into Agent 3 internals.
3. **State is immutable.** Campaign transitions return new states and increment a monotonic revision.
4. **Transitions fail closed.** Undefined state transitions raise `CampaignTransitionError`.
5. **Times are UTC-aware.** Naive timestamps are rejected at every boundary.
6. **Payloads are JSON-safe.** Mutable inputs are copied/frozen and unsupported or non-finite values are rejected.
7. **Queue selection is deterministic.** `CampaignQueue` selects ready campaigns by priority, ready time, insertion sequence and campaign id.
8. **Persistence is crash-safe at the file boundary.** Records are written to a temporary file, flushed, fsynced and atomically replaced.
9. **Persisted identity is bound to its filename.** A record moved or rewritten under another campaign id is rejected.
10. **Events are ordered per campaign.** Sequence gaps and duplicate event ids are rejected.

## State model

```text
QUEUED ───────► SCHEDULED ───────► RUNNING ───────► SUCCEEDED
   │                 │                │  │
   │                 │                │  └────────► FAILED
   │                 │                ├───────────► PAUSING ─► PAUSED
   │                 │                └───────────► CANCELLING ─► CANCELLED
   └─────────────────┴────────────────────────────────────────► CANCELLED
```

Paused campaigns may be queued, scheduled, resumed or cancelled. Terminal states have no outgoing transitions.

## Persistence schema

Campaign files use the versioned schema:

```text
modelrig-agent4/campaign-record/v1
```

Each record contains exactly one campaign specification and its latest state. The filename is a SHA-256 binding of `campaign_id`; the identifier itself remains inside the JSON document for validation and diagnostics.

## CI contract

The shared `_tests.yml` workflow already auto-discovers:

- `tests/worker_*.py`
- `tests/workflow_*.py`

Therefore the foundation adds tests without modifying the central workflow. The unit gate covers domain, queue, repository and event contracts. The workflow gate composes the full dormant path:

```text
spec → queue → transition → event → repository → restore
```

## Delivered follow-on contracts

- A4-01 startup recovery;
- A4-02 checkpoint payload storage;
- A4-03 resource admission;
- A4-04 retry policy and durable failure handling;
- A4-05 health policy and explicit health intervention adapters.

## Deliberately deferred

- Agent 3 runtime adapter;
- host cadence or background polling loop;
- REST/WebSocket endpoints;
- cross-process or distributed leases;
- evidence vault and append-only persistent timeline;
- multi-host orchestration.

Each deferred item must be introduced behind a separately testable contract.
