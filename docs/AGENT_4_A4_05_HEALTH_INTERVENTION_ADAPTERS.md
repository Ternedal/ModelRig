# A4-05 — concrete health intervention service adapters

This slice connects the caller-driven health intervention coordinator to existing dormant Agent 4 services without adding polling, host cadence or automatic startup behavior.

## Adapter map

`HealthInterventionServiceAdapters` builds explicit handlers for:

- resource renewal through the configured lifecycle service;
- pause requests through the configured lifecycle service;
- checkpoints through `CampaignCheckpointService` and a host payload provider;
- fail-closed handling through `CampaignHealthFailClosedService`.

Checkpoint service and payload provider must be configured together. If they are omitted, the coordinator continues to treat a checkpoint recommendation without a handler as a composition error.

## Fail-closed boundary

The fail-closed service closes the time-of-check/time-of-use window by reloading the durable record and requiring it to exactly match the coordinator's record. It accepts only active delegated states (`RUNNING`, `PAUSING`, `CANCELLING`), persists `FAILED`, records the existing ordered watchdog wire event, and only then releases optional resource ownership.

The persistent event phase and payload key remain `watchdog` / `watchdog_action` in this mechanical rename. Changing that wire format requires a separate migration decision.

A persistence failure therefore never releases resources. A campaign that moved on after evaluation is not mutated by stale evidence.

## Safety

- no background thread, timer or recurring schedule;
- no automatic observation ingestion;
- no implicit checkpoint payload or identifier generation;
- no fallback to a different action when one adapter fails;
- all mutations continue through explicit caller-driven services.
