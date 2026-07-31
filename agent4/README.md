# Agent 4 — Autonomous Campaign Orchestrator

Agent 4 is the orchestration layer above the validated Agent 3 runtime. It owns
campaign lifecycle coordination, durable orchestration state, recovery and
operator-facing control. It does **not** change Agent 3 execution contracts.

## Current milestone: A4-01 foundation

The branch currently provides a dormant, standard-library-only foundation:

- immutable `CampaignSpec`, `CampaignState`, `CampaignEvent` and `CampaignRecord`;
- explicit, fail-closed campaign state transitions;
- a deterministic campaign queue with priority and future start times;
- atomic JSON campaign persistence with schema and filename binding;
- ordered per-campaign event publication;
- protocols for repositories, executors, clocks, IDs and event delivery;
- unit and composition tests automatically discovered by the shared CI glob.

Runtime activation, API routes and background threads are deliberately absent.
Importing `app.agent4` has no side effects and cannot start Agent 3 work.

## Stable Agent 4 identities

Agent 4 uses its own namespace so it cannot collide with ModelRig roadmap tasks:

1. `A4-01` — foundation, lifecycle and startup recovery.
2. `A4-02` — durable checkpoints.
3. `A4-03` — resource leases and caller-driven admission.
4. `A4-04` — retry classification and durable failure handling.
5. `A4-05` — health policy, intervention coordination and adapters.
6. `A4-06` — future append-only timeline/evidence integration.

Retired aliases and provenance rules are documented only in
`docs/AGENT_4_IDENTITY.md`.

## Package layout

```text
worker/app/agent4/
├── __init__.py
├── campaign_queue.py
├── checkpoint.py
├── contracts.py
├── domain.py
├── event_bus.py
├── failure_handling.py
├── health.py
├── health_intervention.py
├── health_intervention_adapters.py
├── recovery.py
├── repository.py
├── resource_admission.py
├── resources.py
├── retry.py
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

## A4-01 lifecycle service

`CampaignSchedulerService` provides explicit submit, dispatch, pause, resume,
cancellation and completion commands. It is caller-driven and remains fully
dormant until a host composes it with repository, executor, event and clock
implementations. The class name describes its lifecycle-facing API; the passive
queue it uses lives separately in `campaign_queue.py`. See
`docs/AGENT_4_A4_01_SCHEDULER.md`.
