# Agent 4 — Autonomous Campaign Orchestrator

Agent 4 is the orchestration layer above the validated Agent 3 runtime. It owns
campaign scheduling, durable orchestration state, recovery and operator-facing
control. It does **not** change Agent 3 execution contracts.

## Current scope: A4-01 through A4-07

The branch provides dormant, standard-library-only orchestration contracts:

- immutable `CampaignSpec`, `CampaignState`, `CampaignEvent` and `CampaignRecord`;
- explicit, fail-closed campaign state transitions;
- deterministic scheduling with priority and future start times;
- atomic JSON campaign persistence with schema and filename binding;
- durable checkpoints and caller-driven startup recovery;
- process-local resource leases and resource-aware admission;
- deterministic retry classification and durable retry scheduling;
- pure watchdog policy, guarded coordination and explicit service adapters;
- append-only, hash-chained campaign timelines with JSON evidence metadata;
- one explicit, dormant runtime-composition factory over the shared components;
- unit and composition tests automatically discovered by the shared CI glob.

Runtime activation, API routes and background threads are deliberately absent.
Importing `app.agent4` has no side effects and cannot start Agent 3 work.

## Stable Agent 4 identities

Agent 4 uses its own namespace so it cannot collide with ModelRig roadmap tasks:

1. `A4-01` — foundation, lifecycle and startup recovery.
2. `A4-02` — durable checkpoints.
3. `A4-03` — resource leases and scheduler admission.
4. `A4-04` — retry classification and durable retry scheduling.
5. `A4-05` — health policy, watchdog coordinator and adapters.
6. `A4-06` — append-only timeline and evidence metadata integration.
7. `A4-07` — explicit dormant runtime composition.

Retired aliases and provenance rules are documented only in
`docs/AGENT_4_IDENTITY.md`.

## Package layout

```text
worker/app/agent4/
├── __init__.py
├── checkpoint.py
├── composition.py
├── contracts.py
├── domain.py
├── event_bus.py
├── health.py
├── recovery.py
├── repository.py
├── resource_admission.py
├── resources.py
├── retry.py
├── retry_scheduling.py
├── scheduler.py
├── service.py
├── timeline.py
├── watchdog.py
└── watchdog_adapters.py
```

## Test locally

```bash
PYTHONPATH=worker python tests/worker_agent4_foundation.py
PYTHONPATH=worker python tests/workflow_agent4_foundation.py
PYTHONPATH=worker python tests/worker_agent4_timeline.py
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
implementations. See `docs/AGENT_4_A4_01_SCHEDULER.md`.

## A4-06 timeline and evidence

`JsonlCampaignTimelineStore` persists one append-only JSONL timeline per campaign.
Every entry is filename-bound, strictly sequenced and linked to the previous entry
by SHA-256. `DurableCampaignEventBus` accepts an event only after the corresponding
line has been flushed and fsynced. Evidence stores JSON metadata and immutable
artifact references; it does not embed or fetch binary content. See
`docs/AGENT_4_A4_06_TIMELINE.md`.

## A4-07 runtime composition

`compose_agent4_runtime(...)` wires one shared repository, checkpoint store,
timeline, event bus, queue, resource manager, scheduler, retry service and
watchdog failure boundary. Composition creates no directory, runs no recovery and
starts no background behavior. See `docs/AGENT_4_A4_07_COMPOSITION.md`.
