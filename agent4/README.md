# Agent 4 — Autonomous Campaign Orchestrator

Agent 4 is the orchestration layer above the validated Agent 3 runtime. It owns
campaign lifecycle coordination, durable orchestration state, recovery and
operator-facing control. It does **not** change Agent 3 execution contracts.

## Current milestone: dormant A4-01–A4-11 foundation

The package provides a dormant, standard-library-only orchestration foundation:

- immutable `CampaignSpec`, `CampaignState`, `CampaignEvent` and `CampaignRecord`;
- explicit, fail-closed campaign state transitions;
- a deterministic campaign queue with priority and future start times;
- atomic JSON campaign persistence with schema and filename binding;
- authoritative campaign state with durable audit-projection intents;
- deterministic event identity and caller-driven crash reconciliation;
- ordered per-campaign event publication;
- immutable checkpoints;
- process-local resource leases and caller-driven resource admission;
- deterministic retry classification and durable failure handling;
- pure health assessment with caller-driven intervention adapters;
- append-only, hash-chained campaign timelines with immutable evidence
  references;
- durable at-least-once delivery cursors and an explicit shared process-local
  single-flight guard;
- verified, bounded timeline query cursors with stable snapshot paging;
- bounded durable consumer batches over the existing delivery cursor;
- one explicit dormant composition of the complete B-reference object graph;
- one live writer context per canonical dataroot in a process;
- bounded transport-independent operator reads over that exact object graph;
- protocols for repositories, executors, clocks, IDs and event delivery;
- tests automatically discovered through the shared CI entrypoints.

Runtime activation, API routes and background threads are deliberately absent.
Importing `app.agent4` has no side effects and cannot start Agent 3 work.

## Stable Agent 4 identities

Agent 4 uses its own namespace so it cannot collide with ModelRig roadmap tasks:

1. `A4-01` — foundation, lifecycle and startup recovery.
2. `A4-02` — durable checkpoints.
3. `A4-03` — resource leases and caller-driven admission.
4. `A4-04` — retry classification and durable failure handling.
5. `A4-05` — health policy, intervention coordination and adapters.
6. `A4-06` — append-only timeline, evidence references and durable delivery.
7. `A4-07` — verified bounded timeline query paging.
8. `A4-08` — bounded durable consumer batches.
9. `A4-09` — explicit dormant B-reference runtime composition.
10. `A4-10` — bounded transport-independent operator reads.
11. `A4-11` — authoritative state and reparable audit projection.

Retired aliases and provenance rules are documented only in
`docs/AGENT_4_IDENTITY.md`.

## Package layout

```text
worker/app/agent4/
├── __init__.py
├── campaign_queue.py
├── checkpoint.py
├── composition.py
├── contracts.py
├── domain.py
├── event_bus.py
├── failure_handling.py
├── health.py
├── health_intervention.py
├── health_intervention_adapters.py
├── operator.py
├── projected_services.py
├── projection.py
├── recovery.py
├── repository.py
├── resource_admission.py
├── resources.py
├── retry.py
├── service.py
├── timeline.py
├── timeline_batches.py
├── timeline_delivery.py
├── timeline_delivery_flights.py
├── timeline_query.py
└── timeline_recorder.py
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

## Lifecycle and evidence

`CampaignSchedulerService` provides explicit submit, dispatch, pause, resume,
cancellation and completion commands. It is caller-driven and remains fully
dormant until a host composes it with repository, executor, event and clock
implementations. The class name describes its lifecycle-facing API; the passive
queue it uses lives separately in `campaign_queue.py`.

A4-06 adds explicit timeline append, verification, replay and delivery
operations. It does not subscribe to lifecycle events automatically. Multiple
delivery-service instances coordinate only when the host explicitly shares one
`InMemoryCampaignTimelineDeliverySingleFlight` guard.

A4-07 adds read-only, bounded query paging with hash-bound cursors and an
optional stable snapshot-head. It writes no delivery progress and mounts no API.

A4-08 adds a caller-driven bounded batch wrapper that reuses the A4-06 durable
cursor and shared single-flight guard. It introduces no second progress format.

A4-09 wires lifecycle, checkpoint, failure, health, delivery, query and batch
services into one explicit object graph. Construction creates no files and calls
no service method. The composition uses `TimelineCampaignEventRecorder`
directly; it does not put an event bus inside or in front of timeline storage.

A4-10 adds a bounded read model over the exact A4-09 scheduler, timeline and
query instances. Status filtering is applied before limits, and timeline paging
reuses A4-07 hash-bound cursors rather than defining a parallel offset format.

A4-11 keeps the durable campaign record authoritative and stores any pending
audit work in the same atomic repository envelope. State-writing services add
deterministic projection intents and immediately invoke the shared reconciler.
If timeline append succeeds but acknowledgement does not, the same event-id is
retried idempotently. If append never happens, the pending intent survives and
can be repaired through the explicit `reconcile_projections()` call. The
reconciler never dispatches Agent 3 work and starts no cadence of its own.

See:

- `docs/AGENT_4_A4_01_SCHEDULER.md`;
- `docs/AGENT_4_A4_06_TIMELINE.md`;
- `docs/AGENT_4_A4_06_DELIVERY_SINGLE_FLIGHT.md`;
- `docs/AGENT_4_A4_07_TIMELINE_QUERY.md`;
- `docs/AGENT_4_A4_08_BATCH_DELIVERY.md`;
- `docs/AGENT_4_A4_09_COMPOSITION.md`;
- `docs/AGENT_4_A4_10_OPERATOR_READ.md`;
- `docs/agent4/ADR-A4-006_STATE_PROJECTION.md`.
