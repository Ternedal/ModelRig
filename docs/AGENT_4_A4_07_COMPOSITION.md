# Agent 4 A4-07 — explicit dormant runtime composition

**Status:** dormant implementation  
**Activation:** explicit host calls only  
**Background work:** none  
**API routes:** none

## Purpose

A4-01 through A4-06 provide validated components, but a host could still wire
repositories, queues, event buses and resource managers inconsistently. A4-07
adds one canonical single-process composition factory without turning Agent 4
into a running service.

## Factory contract

`compose_agent4_runtime(...)` requires:

- an explicit filesystem root;
- an implementation of `CampaignExecutor`;
- fixed process-local resource capacities;
- a resource resolver;
- optional clock, retry policy and lease TTL values.

It returns an immutable `Agent4RuntimeContext` containing one shared object graph:

- `JsonCampaignRepository`;
- `JsonCheckpointStore`;
- `JsonlCampaignTimelineStore`;
- `DurableCampaignEventBus`;
- `CampaignQueue`;
- `InMemoryResourceLeaseManager`;
- `ResourceAwareCampaignSchedulerService`;
- `CampaignCheckpointService`;
- `CampaignRetryPlanner`;
- `CampaignRetrySchedulingService`;
- `CampaignWatchdogFailClosedService`.

The scheduler, checkpoint service, retry service and watchdog failure service all
share the same repository, clock and durable event timeline. Scheduler and retry
handling share the same queue. Resource-aware dispatch, retry terminalization and
watchdog failure share the same lease manager.

## Filesystem layout

The factory reserves but does not create:

```text
<root>/
├── campaigns/
├── checkpoints/
└── timeline/
```

Constructing a context performs no write and creates no directory. Directories are
created only by the first explicit persistence or timeline append.

## Explicit operations

`Agent4RuntimeContext.recover()` is the only composition-level recovery entrypoint.
The factory never calls it automatically.

`Agent4RuntimeContext.watchdog(...)` creates a coordinator only when requested.
Checkpoint actions are wired only when the host supplies a checkpoint payload
provider; payload identity and contents remain host-owned.

## Safety boundary

- no route, mount, startup hook, thread, timer or polling loop;
- no automatic recovery, dispatch, retry, checkpoint or watchdog execution;
- no global singleton or module-level runtime;
- no Agent 3 import or execution-contract change;
- no distributed resource or timeline coordination;
- invalid executor, clock, root or resolver boundaries fail before filesystem
  activation.

A4-07 is composition, not production activation. A future host integration must
remain a separate, explicitly reviewed slice.
