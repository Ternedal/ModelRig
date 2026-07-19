# Research sharing execution contract

Status: **dormant**. This contract does not enable BrowserHost, CDP, public-network access, a model provider, an API route, or a tool.

## Purpose

`worker/app/research_sharing_execution.py` composes an already prepared `ResearchSharingLease` with one injected asynchronous operation. It owns lifecycle ordering and terminal audit, while the injected transport remains responsible for the real external operation.

The wrapper exists so eventual BrowserHost wiring cannot accidentally:

- call external processing before the exact common receipt is claimed;
- forget cleanup after success, failure, timeout, or cancellation;
- invent a byte count from payload size instead of transport-confirmed progress;
- leak raw exception details into user-visible errors or durable audit;
- return a successful result after cleanup or operation-contract failure.

## Required ordering

One execution follows this sequence:

1. Validate wrapper inputs and the injected operation interface.
2. Claim the exact lease through `ResearchSharingBoundary`.
3. Create a byte meter using the request's authorized maximum.
4. Invoke asynchronous `run(meter)`.
5. Attempt asynchronous `close()` exactly once after `run` starts.
6. Complete the common receipt exactly once with measured bytes and a normalized outcome.
7. Return the result, raise a normalized execution error, or propagate caller cancellation after terminal audit.

A denied, expired, revoked, observe-only, policy-mismatched, or intent-mismatched lease never enters `run` or `close`.

## Byte accounting

`OutboundByteMeter.record_sent(count)` records only bytes the injected transport confirms were sent. It is thread-safe and rejects negative, boolean, and over-budget increments.

The wrapper does not derive outbound bytes from:

- request payload length;
- serialized plan size;
- response size;
- an expected transport frame;
- a guessed retry count.

On partial failure, timeout, cancellation, or cleanup failure, the terminal event carries the meter's confirmed count at that point.

## Normalized terminal outcomes

| Situation | Outcome | Error code |
|---|---|---|
| Successful operation and cleanup | `completed` | none |
| Operation timeout | `failed` | `operation_timeout` |
| Caller cancellation during operation | `failed` | `operation_cancelled` |
| Unexpected operation exception | `failed` | `operation_failed` |
| Operation-reported failure | `failed` | supplied stable code |
| Operation-reported block | `blocked` | supplied stable code |
| Invalid byte/reporting contract | `blocked` | `operation_contract_violation` |
| Byte budget exceeded | `blocked` | `byte_budget_exceeded` |
| Cleanup exception | `blocked` | `cleanup_failed` |
| Cleanup timeout | `blocked` | `cleanup_timeout` |
| Cleanup cancellation | `blocked` | `cleanup_cancelled` |
| Synchronous `run` or `close` | `blocked` | operation/cleanup contract violation |

Raw exception messages are neither returned nor stored in the common audit.

## Cancellation

Caller cancellation is caught long enough to attempt cleanup and complete the receipt with the real measured byte count. The original `CancelledError` is then propagated. A second cancellation or cleanup failure is represented in the terminal audit rather than being reported as success.

## Integration gate

A future BrowserHost adapter may implement the injected asynchronous operation only after all of the following are independently validated:

- controlled CDP ownership and cleanup;
- hostname allowlist enforcement on every navigation and redirect;
- DNS resolution and public-peer pinning at the actual connection boundary;
- exact outbound byte reporting;
- local fallback and rollback behavior;
- physical-rig validation without private or loopback egress.

Until that integration exists and is explicitly activated, this module remains an isolated, test-only composition boundary.
