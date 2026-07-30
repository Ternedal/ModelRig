# A4-04 — retry classification and deterministic backoff

This slice adds a pure retry-decision kernel. It does not mutate campaign state,
requeue work, sleep or activate an automatic retry loop. Durable scheduling is a
separate A4-04 slice.

## Failure contract

`FailureDescriptor` is a persistable description of one failed phase. It carries
an exact error type, message, phase, optional `retry_after` delay and optional
JSON metadata. The default classifier intentionally uses exact error-type names
rather than message substring heuristics.

The built-in categories are:

- `transient`
- `rate_limited`
- `resource_exhausted`
- `permanent`
- `cancelled`

Only the first three are retryable by default. Unknown errors fail closed as
`permanent`.

## Backoff contract

`RetryPolicy` uses deterministic exponential backoff:

```text
delay = min(initial_delay * multiplier ** (failed_attempt - 1), max_delay)
```

An explicit `retry_after` value is honoured as a minimum delay. Jitter is
intentionally deferred so that the foundation remains deterministic and easy to
replay in tests.

## Budget contract

`CampaignRetryPlanner` reads `CampaignSpec.max_attempts` and the current failed
attempt number. It returns an immutable `RetryDecision` with:

- retry or terminal disposition;
- category;
- failed and remaining attempt counts;
- delay and next ready timestamp when retryable;
- an explicit reason.

Retryable failures become terminal once the campaign's attempt budget is
exhausted. Permanent and cancelled failures are terminal immediately.

## Validation

The existing `tests/workflow_agent4_foundation.py` gate includes seven
retry-policy scenarios. The complete Agent 4 stack passes 60 tests at this
slice.

## Deferred

Operator overrides, deterministic jitter, automatic failure ingestion and
automatic redispatch remain separate future slices.
