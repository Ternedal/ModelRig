# ADR-A4-008 Slice 5 — end-to-end proof preflight

**Base verified:** `main @ 2b60ded928b4f136e33237e83979e860293e801f`

**Verdict:** the final proof slice can be implemented without a new
architecture decision. The landed Agent 4 handoff runtime and the landed real
Agent 3 adapter already share the typed `CampaignHandoffExecutor` boundary.
Slice 5 therefore adds proof only; it does not add production composition.

## Scope

Slice 5 proves the complete dormant path by constructing, inside tests:

1. the real `JsonCampaignRepository`, queue, scheduler and recovery service;
2. the real `Agent3CampaignHandoffAdapter`;
3. the real `AgentRunStore` and `Agent3Orchestrator`;
4. an injected deterministic Agent 3 tool executor and server-authored launch
   resolver.

The proof covers dispatch, crash before receiver acceptance, crash after
receiver acceptance but before sender confirmation, tombstone recovery, a new
caller-driven attempt, missing receiver evidence, signal intervention,
resource reconciliation and explicit marker resolution.

## Files

- `tests/worker_agent4_handoff_e2e.py` — real-adapter integration and the
  machine-validated 17-test traceability manifest;
- `tests/worker_agent4_handoff_mutation_contract.py` — ten isolated mutations,
  each required to make its named contract test red;
- `docs/agent4/A4-008_SLICE_5_PROOF.md` — evidence classification, traceability,
  mutation matrix, limitations and activation gate;
- generated `CURRENT_STATE.md` entries for the two new auto-discovered tests.

No production module is changed.

## Test matrix

- focused Slice 5 end-to-end suite;
- focused ten-mutation suite;
- existing Agent 3 adapter and race suites;
- existing Agent 4 persistence, runtime, barrier and architecture gates;
- repository-wide auto-discovered suite;
- CodeQL;
- authoritative `CURRENT_STATE.md` generation;
- independent exact-head review before landing.

## Ten mutations

1. replace Agent 3 `BEGIN IMMEDIATE` with deferred `BEGIN`;
2. remove the receiver tombstone recheck after the prepare gap;
3. return `created=True` for a competing duplicate;
4. advance the receiver runtime even when the dispatch was not newly created;
5. attest terminal success when the accepted Agent 3 run row is missing;
6. persist a signal as acknowledged before the operation;
7. replay a requested-but-unacknowledged signal;
8. automatically requeue an `unknown` recovery result;
9. automatically clear an existing resource-reconciliation marker on terminal
   outcome;
10. bypass the resource-admission barrier.

Each mutation runs against a temporary copy of `worker/app` and must produce a
failure in the named unmodified contract test. Syntax or import failures do not
count as proof.

## Explicit exclusions

- no Agent 4 production wiring or composition change;
- no route, write surface, feature flag or activation;
- no polling, thread, timer, subscription or background worker;
- no automatic redispatch, signal resend, cancel or lease reacquisition;
- no second repository, dispatch journal, database or wire model;
- no durable lease reconstruction or per-resource inference;
- no automatic reconciliation-marker clear;
- no claim of physical-rig evidence.

## Stop conditions

Stop for a new architecture decision if the proof requires production wiring,
a new persistence boundary, automatic execution from recovery, weakening the
`unknown` policy, signal-outcome inference, reconstructed resource ownership or
any activation surface.

No stop condition was triggered during preflight.
