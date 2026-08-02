# ADR-A4-008 Slice 3 — measured behavioral preflight

**Base verified:** `main @ cf1ff92a154061700264617457f26787c7a6a9c6`

**Verdict:** Slice 3 can be implemented within ADR-A4-008, including
Clarifications 1 and 2. No new architecture decision is required.

## Measured current behavior

Both existing scheduler paths persisted a bare `RUNNING` record, called the
legacy executor and converted every executor exception directly to `FAILED`.
Startup recovery failed every interrupted active state without consulting a
handoff outcome. The resource-aware path removed queue state and acquired a
process-local lease before either operation.

Slice 2 already provides the required atomic boundary: record, projection
intents and handoff intents share one v3 campaign-envelope replacement.

## Slice 3 behavior

The reference flow becomes:

1. select caller-requested ready work;
2. check the resource-reconciliation barrier where applicable;
3. acquire resources where applicable;
4. derive `RUNNING`, deterministic request and requested handoff;
5. persist state, `DISPATCH_REQUESTED` and handoff in one replacement;
6. call the typed executor;
7. persist acknowledgement, `DISPATCH_CONFIRMED` and `STARTED` atomically;
8. reconcile audit projection caller-driven.

A transport exception after step 5 is not evidence that dispatch did not
occur. The record remains non-terminal with its requested handoff. No lease is
released on that unproved assumption.

Signals use the same requested-before-call and typed-acknowledgement rule. A
transport exception leaves the requested signal and its non-terminal state;
recovery never redelivers it automatically.

## Recovery matrix

- `not_dispatched`: mark ready for a new caller-driven attempt, preserve the old
  tombstoned identity, no resource marker, no dispatch;
- `accepted` / `running`: acknowledge with runtime evidence and set
  `resource_reconciliation_required`;
- `unknown` or query failure: preserve requested handoff, set execution
  intervention and resource reconciliation markers;
- `completed` / `failed`: persist terminal state and authoritative
  acknowledgement, but preserve any marker already present;
- requested signals: intervention plus resource marker, never automatic resend;
- legacy interrupted records without a handoff retain the old fail-closed
  behavior.

## Resource barrier

The global barrier is derived from persisted campaign markers. The
resource-admission path checks it before lease acquisition, queue removal,
transition/persistence to `RUNNING` and the external dispatch. The ordinary
handoff scheduler has no resource barrier and is covered separately.

## Explicit resolution

One caller-driven operation clears one campaign marker only. It requires an
existing marker, one of the three ADR reasons and a non-empty evidence pointer.
The clear and `RESOURCE_RECONCILIATION_RESOLVED` audit intent share one envelope
replacement. Outcome lookup never auto-clears.

## Files

- `worker/app/agent4/handoff_runtime.py` — caller-driven scheduler, recovery,
  barrier and explicit resolution;
- `worker/app/agent4/composition.py` — reference composition switches to the
  typed handoff scheduler/executor;
- focused root contract tests and generated current-state update.

The existing `JsonCampaignRepository` remains the only storage boundary. The
runtime helper uses its existing lock, parser and `_write` replacement for the
single recovery case that must update record and handoff acknowledgement
atomically.

## Explicit exclusions

- no Agent 3 adapter or tombstone registry implementation;
- no route, write surface, feature flag or activation;
- no background thread, timer, polling or subscription;
- no automatic redispatch, signal resend, cancel or lease reacquisition;
- no durable leases, fencing tokens or per-resource barrier;
- no second repository, journal, global marker file or wire model;
- no automatic resource-marker clear.

## Stop conditions

Stop for a new ADR if implementation requires a second storage boundary,
automatic execution from recovery, a weaker unknown policy, reconstructed
resource ownership, per-resource inference, or any activation surface.

No stop condition was triggered during preflight.
