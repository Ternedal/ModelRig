# T-030 — caller-driven campaign scheduler

**Status:** implemented on the Agent 4 foundation branch  
**Activation:** explicit composition only  
**Background loop:** not included  
**Agent 3 adapter:** protocol only

## Delivered behavior

`CampaignSchedulerService` composes the foundation contracts into one
single-process lifecycle coordinator.

Supported commands:

- submit an immediate or future campaign;
- dispatch the highest-priority ready campaign;
- request pause and acknowledge paused state;
- resume a paused Agent 3 runtime without consuming another attempt;
- cancel queued campaigns immediately;
- request cancellation of running, pausing or paused runtimes;
- acknowledge cancellation;
- record successful or failed completion;
- read one campaign or list the durable campaign snapshot.

## Dispatch contract

A ready campaign is persisted as `RUNNING` before it is delegated to the
executor. This makes an interrupted dispatch visible to the future T-031
recovery slice.

```text
QUEUED/SCHEDULED
      |
persist RUNNING
      |
CampaignExecutor.dispatch
      | \
      |  \ exception or empty reference
      |   └─ persist FAILED + FAILED event
      |
      └─ STARTED event + runtime reference
```

If persistence of the running state fails, the campaign is restored to the
in-memory queue and is not dispatched.

## Pause and resume

Pause and cancellation are cooperative:

```text
RUNNING → PAUSING → PAUSED → RUNNING
            |          |
            |          └─ CANCELLING → CANCELLED
            └──────────── CANCELLING → CANCELLED
```

Resume uses `CampaignExecutor.signal(..., "resume")`; it does not create a new
dispatch attempt. A failed lifecycle signal is converted into a durable
`FAILED` state with a phase-specific event.

## Dormancy guarantee

The service owns no thread and no timer. `dispatch_ready()` performs at most
one explicit dispatch. A later host can drive it from an API, a scheduler or a
test harness without changing the domain or persistence contracts.

## Deferred to T-031+

- rehydrate the in-memory queue after restart;
- reconcile campaigns found in `RUNNING`, `PAUSING` or `CANCELLING`;
- persist event history;
- cross-process leases and admission control;
- retries and backoff;
- API and WebSocket surfaces.
