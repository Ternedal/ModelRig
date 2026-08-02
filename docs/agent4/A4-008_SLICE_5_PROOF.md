# ADR-A4-008 Slice 5 — end-to-end proof report

**Measured base:** `main @ 2b60ded928b4f136e33237e83979e860293e801f`

**Scope:** dormant proof only. No production composition, route, flag or
activation is introduced.

## Evidence classes

### Unit evidence

The Slice 1–4 tests prove immutable request identities, envelope validation,
atomic repository replacement, receiver deduplication, tombstones, conservative
outcome mapping, signal non-replay, barrier placement and explicit resolution
in isolation.

### Integration evidence

`tests/worker_agent4_handoff_e2e.py` constructs the real Agent 4 repository,
scheduler and recovery service against the real Agent 3 adapter,
`AgentRunStore` and `Agent3Orchestrator`. It proves both authoritative stores
across the following complete flows:

- normal dispatch and acknowledgement;
- crash before receiver call, negative commitment, permanent tombstone and a
  new caller-driven attempt with a new identity;
- receiver acceptance followed by sender-confirmation failure, then terminal
  recovery without a second runtime;
- missing receiver run evidence becoming `unknown`, intervention and resource
  reconciliation without automatic scheduling or redispatch;
- unsupported PAUSE remaining a requested signal and becoming explicit signal
  intervention without redelivery;
- resource barrier preventing lease acquisition and preventing the real adapter
  from being reached;
- terminal recovery preserving an existing marker until the explicit durable
  resolution operation.

### CI evidence

The exact PR head must pass:

- the focused end-to-end suite;
- all ten mutation proofs;
- Agent 3 diagnostics;
- Agent 3 full diagnostics and the complete repository suite;
- normal CI including platform jobs;
- CodeQL;
- generated `CURRENT_STATE.md` parity.

CI is code evidence. It is not physical-rig evidence.

### Physical evidence

No physical-rig execution is performed or claimed in Slice 5.

**mock-bevis og rigtigt adapter-bevis er nødvendige, men ikke tilstrækkelige. Fysisk rig-bevis bundet til eksakt SHA og min separate, eksplicitte aktiveringsbeslutning kræves.**

## Traceability for all 17 mandatory ADR tests

This table is duplicated as `ADR_A4_008_TRACEABILITY` in the end-to-end test.
The automated traceability test parses the ADR, requires exactly tests 1–17,
verifies every referenced class and function in the repository AST, and requires
all 17 rows in this report.

| ADR test | Named automated test(s) |
|---:|---|
| 1 | `Slice3Tests.test_requested_state_and_intent_share_replace_boundary` |
| 2 | `Agent4Agent3EndToEndTests.test_crash_before_receiver_call_tombstones_and_requires_new_attempt` |
| 3 | `CampaignAdapterTests.test_dispatch_is_atomic_and_idempotent_for_same_request`; `CampaignAdapterRaceTests.test_bind_dispatch_duplicate_after_prepare_gap_returns_existing_ack` |
| 4 | `Agent4Agent3EndToEndTests.test_crash_after_receiver_acceptance_recovers_terminal_without_redispatch` |
| 5 | `Agent4Agent3EndToEndTests.test_missing_receiver_run_recovers_unknown_without_redispatch` |
| 6 | `Agent4Agent3EndToEndTests.test_crash_before_receiver_call_tombstones_and_requires_new_attempt` |
| 7 | `CampaignAdapterTests.test_signal_is_requested_before_call_and_never_redelivered` |
| 8 | `Agent4Agent3EndToEndTests.test_stack_is_caller_driven_and_starts_no_background_work` |
| 9 | `Agent4HandoffPersistenceTests.test_v3_round_trip_contains_both_typed_collections` |
| 10 | `Agent4Agent3EndToEndTests.test_storage_and_dormant_architecture_gates_are_armed` |
| 11 | `Agent4Agent3EndToEndTests.test_crash_before_receiver_call_tombstones_and_requires_new_attempt`; `CampaignAdapterRaceTests.test_bind_dispatch_rechecks_tombstone_after_prepare_gap` |
| 12 | `Agent4Agent3EndToEndTests.test_crash_before_receiver_call_tombstones_and_requires_new_attempt` |
| 13 | `Slice3Tests.test_not_dispatched_is_ready_without_auto_redispatch` |
| 14 | `Slice3Tests.test_accepted_running_and_unknown_follow_marker_rule`; `Slice3Tests.test_terminal_attestation_never_auto_clears_existing_marker` |
| 15 | `BarrierPlacementTests.test_existing_marker_blocks_before_any_lease_acquire_attempt`; `Agent4Agent3EndToEndTests.test_real_adapter_is_not_reached_when_resource_barrier_is_set` |
| 16 | `Agent4Agent3EndToEndTests.test_recovery_and_barrier_have_no_automatic_execution_calls` |
| 17 | `Agent4Agent3EndToEndTests.test_terminal_recovery_preserves_marker_until_explicit_resolution` |

## Ten sabotage proofs

Each test copies `worker/app` to an isolated temporary PYTHONPATH, applies one
mutation, runs only the named unmodified contract test and requires it to fail.
The harness rejects syntax and import errors as proof.

| Sabotage | Broken property | Test required to become red |
|---:|---|---|
| 1 | `BEGIN IMMEDIATE` weakened to deferred `BEGIN` | `test_transaction_is_immediate_and_blocks_competing_writer` |
| 2 | tombstone recheck removed after prepare gap | `test_bind_dispatch_rechecks_tombstone_after_prepare_gap` |
| 3 | competing duplicate reported as newly created | `test_bind_dispatch_duplicate_after_prepare_gap_returns_existing_ack` |
| 4 | duplicate advances a second runtime path | `test_bind_dispatch_duplicate_after_prepare_gap_returns_existing_ack` |
| 5 | missing receiver run falsely attested terminal/released | `test_missing_run_row_for_nonterminal_effect_is_unknown` |
| 6 | signal marked acknowledged before operation | `test_signal_is_requested_before_call_and_never_redelivered` |
| 7 | unresolved signal replayed | `test_signal_is_requested_before_call_and_never_redelivered` |
| 8 | `unknown` automatically requeued | `test_missing_receiver_run_recovers_unknown_without_redispatch` |
| 9 | terminal lookup automatically clears marker | `test_terminal_attestation_never_auto_clears_existing_marker` |
| 10 | resource barrier bypassed | `test_existing_marker_blocks_before_any_lease_acquire_attempt` |

A green mutation is a proof failure and blocks landing.

## PAUSING and CANCELLING limitation

PAUSE remains fail-closed because Agent 3 cannot safely suspend a synchronous
in-flight side effect. CANCEL can persist intent and top-level cancellation but
cannot physically stop a synchronous side effect already executing.

**execution-status kan afvige fra en levende runtime, indtil signal-outcome-opslag leveres i en senere slice.**

Recovery therefore never infers signal success and never resends a requested
signal. It records execution intervention and resource reconciliation instead.
This is an accepted limitation, not an activation-ready signal contract.

## Activation conclusion

Slice 5 can prove the code contract against mocks and the real dormant adapter.
It cannot prove physical resource release, real rig behavior or unattended
operational safety. ADR-A4-008 Decision 8 remains above every feature flag and
write surface.

No route, flag, production object graph or activation decision is included in
this proof.
