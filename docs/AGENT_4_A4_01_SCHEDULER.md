# A4-01 — caller-driven campaign scheduler

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
executor. This makes an interrupted dispatch visible to A4-01 startup recovery.

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

## Follow-on contracts

- A4-01 startup recovery rehydrates durable work and fails interrupted active
  work closed;
- A4-02 persists checkpoint payloads;
- A4-03 adds resource leases and admission;
- A4-04 adds retry decisions and durable retry scheduling;
- A4-05 adds health assessment and explicit watchdog adapters.

Persistent event history, cross-process coordination and operator/API surfaces
remain deferred.
