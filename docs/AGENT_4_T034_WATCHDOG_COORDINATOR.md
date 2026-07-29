# Agent 4 T-034 — caller-driven watchdog coordinator

This slice adds the explicit execution boundary around the pure T-034 watchdog
policy. It still creates no polling loop or automatic runtime behavior.

## Durable-state guard

Before routing an action, the coordinator loads the durable campaign record and
requires:

- the campaign exists
- the observation lifecycle status exactly matches durable state
- the observation timestamp is not older than the durable state update

A stale observation therefore cannot pause, renew, checkpoint or fail a campaign
that has already moved on.

## Handler routing

Action handlers are supplied explicitly by the host and receive the durable
record, validated observation and immutable decision. The coordinator routes
exactly one action:

- `RENEW_RESOURCES`
- `REQUEST_CHECKPOINT`
- `REQUEST_PAUSE`
- `FAIL_CLOSED`

Healthy and non-applicable decisions perform no action. Missing handlers are
composition errors; handler failures are wrapped and never fall through to a
different action.

## Safety

- no background thread, polling, timer or retry loop
- no repository mutation by the coordinator
- no implicit Agent 3 or resource-manager dependency
- action execution occurs only through caller-provided adapters
- evaluation remains available without executing handlers

## Deferred

Concrete adapters for checkpoint, pause, terminal failure and resource renewal,
observation persistence, event audit and recurring watchdog scheduling remain
separate slices.
