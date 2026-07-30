# Agent 4 foundation contract

**Milestone:** T-030 foundation  
**Status:** dormant implementation  
**Runtime activation:** none  
**Agent 3 contract changes:** none

## Purpose

Agent 4 turns isolated Agent 3 executions into durable campaigns. The
foundation establishes the data and boundary contracts needed before any
background scheduler or operator API is allowed to run.

## Invariants

1. **Dormant by default.** Importing Agent 4 creates no thread, task, file,
   socket, schedule or Agent 3 execution.
2. **Agent 3 remains authoritative for execution.** Agent 4 delegates through
   `CampaignExecutor`; it does not reach into Agent 3 internals.
3. **State is immutable.** Campaign transitions return new states and increment
   a monotonic revision.
4. **Transitions fail closed.** Undefined state transitions raise
   `CampaignTransitionError`.
5. **Times are UTC-aware.** Naive timestamps are rejected at every boundary.
6. **Payloads are JSON-safe.** Mutable inputs are copied/frozen and unsupported
   or non-finite values are rejected.
7. **Queue selection is deterministic.** Ready campaigns are selected by
   priority, ready time, insertion sequence and campaign id.
8. **Persistence is crash-safe at the file boundary.** Records are written to a
   temporary file, flushed, fsynced and atomically replaced.
9. **Persisted identity is bound to its filename.** A record moved or rewritten
   under another campaign id is rejected.
10. **Events are ordered per campaign.** Sequence gaps and duplicate event ids
    are rejected.

## State model

```text
QUEUED ───────► SCHEDULED ───────► RUNNING ───────► SUCCEEDED
   │                 │                │  │
   │                 │                │  └────────► FAILED
   │                 │                ├───────────► PAUSING ─► PAUSED
   │                 │                └───────────► CANCELLING ─► CANCELLED
   └─────────────────┴────────────────────────────────────────► CANCELLED
```

Paused campaigns may be queued, scheduled, resumed or cancelled. Terminal
states have no outgoing transitions.

## Persistence schema

Campaign files use the versioned schema:

```text
modelrig-agent4/campaign-record/v1
```

Each record contains exactly one campaign specification and its latest state.
The filename is a SHA-256 binding of `campaign_id`; the identifier itself
remains inside the JSON document for validation and diagnostics.

## CI contract

The shared `_tests.yml` workflow already auto-discovers:

- `tests/worker_*.py`
- `tests/workflow_*.py`

Therefore the foundation adds tests without modifying the central workflow.
The unit gate covers domain, queue, repository and event contracts. The
workflow gate composes the full dormant path:

```text
spec → queue → transition → event → repository → restore
```

## Deliberately deferred

- Agent 3 runtime adapter;
- background polling loop;
- REST/WebSocket endpoints;
- cross-process leases;
- retry policy;
- resource admission;
- checkpoint payload storage;
- evidence vault;
- startup recovery;
- multi-host orchestration.

Each deferred item will be introduced behind a separately testable contract.
