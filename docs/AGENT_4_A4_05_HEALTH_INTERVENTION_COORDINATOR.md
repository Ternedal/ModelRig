# A4-05 — caller-driven health intervention coordinator

This slice adds the explicit execution boundary around the pure A4-05 health policy. It creates no polling loop, observation cadence or automatic runtime behavior.

## Durable-state guard

Before routing an action, the coordinator loads the durable campaign record and requires that the campaign exists, the observation lifecycle status matches durable state, and the observation timestamp is not older than the durable state update.

A stale observation therefore cannot pause, renew, checkpoint or close a campaign that has already moved on.

## Handler routing

Action handlers are supplied explicitly by the host and receive the durable record, validated observation and immutable decision. The coordinator routes exactly one action: `RENEW_RESOURCES`, `REQUEST_CHECKPOINT`, `REQUEST_PAUSE` or `FAIL_CLOSED`.

Healthy and non-applicable decisions perform no action. Missing handlers are composition errors; handler failures are wrapped and never fall through to a different action.

## Safety

- no background thread, polling, timer or retry loop;
- no repository mutation by the coordinator;
- no implicit Agent 3 or resource-manager dependency;
- intervention execution occurs only through caller-provided adapters;
- evaluation remains available without executing handlers;
- observation cadence belongs to the future host, not to Agent 4.

## Follow-on contract

A separate A4-05 slice supplies concrete checkpoint, pause, terminal-state and resource-renewal adapters. Observation persistence and host cadence remain separate integration decisions.
