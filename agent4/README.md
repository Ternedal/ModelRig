# Agent 4 — Autonomous Campaign Orchestrator

Agent 4 is the orchestration layer above the validated Agent 3 runtime. It owns
campaign scheduling, durable orchestration state, recovery and operator-facing
control. It does **not** change Agent 3 execution contracts.

## Current milestone: T-030 foundation

The branch currently provides a dormant, standard-library-only foundation:

- immutable `CampaignSpec`, `CampaignState`, `CampaignEvent` and `CampaignRecord`;
- explicit, fail-closed campaign state transitions;
- deterministic scheduling with priority and future start times;
- atomic JSON campaign persistence with schema and filename binding;
- ordered per-campaign event publication;
- protocols for repositories, executors, clocks, IDs and event delivery;
- unit and composition tests automatically discovered by the shared CI glob.

Runtime activation, API routes and background threads are deliberately absent.
Importing `app.agent4` has no side effects and cannot start Agent 3 work.

## Package layout

```text
worker/app/agent4/
├── __init__.py
├── contracts.py
├── domain.py
├── event_bus.py
├── repository.py
├── scheduler.py
└── service.py
```

## Test locally

```bash
PYTHONPATH=worker python tests/worker_agent4_foundation.py
PYTHONPATH=worker python tests/workflow_agent4_foundation.py
```

## Architectural boundary

```text
Kaliv / RigGate
       |
Agent 4 operator API        (later milestone)
       |
Agent 4 orchestrator        (this package)
       |
CampaignExecutor protocol
       |
Agent 3 runtime             (unchanged)
```

## T-030 lifecycle service

`CampaignSchedulerService` now provides explicit submit, dispatch, pause,
resume, cancellation and completion commands. It is caller-driven and remains
fully dormant until a host composes it with repository, executor, event and
clock implementations. See `docs/AGENT_4_T030_SCHEDULER.md`.

## Next slices

1. T-031 startup recovery and persisted checkpoints.
2. T-032 resource leases and concurrency limits.
3. T-033 retry classification and backoff.
4. T-034 health observations and watchdog policy.
5. T-035 append-only timeline/evidence integration.
