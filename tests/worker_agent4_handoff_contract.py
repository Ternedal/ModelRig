#!/usr/bin/env python3
"""Pure ADR-A4-008 contracts, identity and backward-compatibility tests."""

from __future__ import annotations

import unittest
from datetime import datetime, timezone

from app.agent4.domain import (
    CampaignEventKind,
    CampaignState,
    CampaignStatus,
    CampaignValidationError,
)
from app.agent4.handoff import (
    CampaignDispatchAcknowledgement,
    CampaignDispatchOutcome,
    CampaignDispatchRequest,
    CampaignHandoffExecutor,
    CampaignSignalAcknowledgement,
    CampaignSignalRequest,
    CampaignSignalType,
    DispatchOutcomeKind,
    campaign_dispatch_id,
    campaign_signal_id,
)

NOW = datetime(2026, 8, 1, 21, 45, tzinfo=timezone.utc)


class _Executor:
    def dispatch(self, request):
        return CampaignDispatchAcknowledgement(
            dispatch_id=request.dispatch_id,
            runtime_reference="agent3:run-1",
        )

    def signal(self, request):
        return CampaignSignalAcknowledgement(signal_id=request.signal_id)

    def query_outcome(self, dispatch_id):
        return CampaignDispatchOutcome(
            dispatch_id=dispatch_id,
            kind=DispatchOutcomeKind.UNKNOWN,
        )


class Agent4HandoffContractTests(unittest.TestCase):
    def test_dispatch_identity_is_deterministic_and_attempt_bound(self) -> None:
        first = campaign_dispatch_id(" campaign-1 ", 1)
        self.assertEqual(first, campaign_dispatch_id("campaign-1", 1))
        self.assertNotEqual(first, campaign_dispatch_id("campaign-1", 2))
        self.assertTrue(first.startswith("agent4-dispatch:v1:"))

    def test_signal_identity_binds_type_and_resulting_revision(self) -> None:
        pause = campaign_signal_id("campaign-1", 2, CampaignSignalType.PAUSE, 8)
        self.assertEqual(
            pause,
            campaign_signal_id("campaign-1", 2, CampaignSignalType.PAUSE, 8),
        )
        self.assertNotEqual(
            pause,
            campaign_signal_id("campaign-1", 2, CampaignSignalType.RESUME, 8),
        )
        self.assertNotEqual(
            pause,
            campaign_signal_id("campaign-1", 2, CampaignSignalType.PAUSE, 9),
        )

    def test_dispatch_request_is_immutable_hashable_and_round_trips(self) -> None:
        parameters = {"nested": {"items": [1, 2]}}
        request = CampaignDispatchRequest(
            campaign_id="campaign-1",
            attempt=1,
            workflow="agent3.write-pilot",
            campaign_revision=3,
            parameters=parameters,
        )
        parameters["nested"]["items"].append(3)

        self.assertEqual(request.parameters["nested"]["items"], (1, 2))
        self.assertEqual(CampaignDispatchRequest.from_dict(request.to_dict()), request)
        self.assertEqual(
            CampaignDispatchRequest.from_dict(request.to_dict()).request_hash,
            request.request_hash,
        )
        with self.assertRaises(CampaignValidationError):
            CampaignDispatchRequest(
                campaign_id="campaign-1",
                attempt=1,
                workflow="agent3.write-pilot",
                campaign_revision=3,
                dispatch_id="forged",
            )

    def test_serialized_numeric_fields_are_not_coerced(self) -> None:
        dispatch = CampaignDispatchRequest(
            campaign_id="campaign-1",
            attempt=1,
            workflow="agent3.write-pilot",
            campaign_revision=3,
        ).to_dict()
        signal = CampaignSignalRequest(
            campaign_id="campaign-1",
            attempt=1,
            signal_type=CampaignSignalType.PAUSE,
            resulting_revision=4,
        ).to_dict()

        malformed = (
            (CampaignDispatchRequest.from_dict, {**dispatch, "attempt": True}),
            (CampaignDispatchRequest.from_dict, {**dispatch, "attempt": 1.9}),
            (
                CampaignDispatchRequest.from_dict,
                {**dispatch, "campaign_revision": True},
            ),
            (
                CampaignDispatchRequest.from_dict,
                {**dispatch, "campaign_revision": 3.9},
            ),
            (CampaignSignalRequest.from_dict, {**signal, "attempt": True}),
            (CampaignSignalRequest.from_dict, {**signal, "attempt": 1.9}),
            (
                CampaignSignalRequest.from_dict,
                {**signal, "resulting_revision": True},
            ),
            (
                CampaignSignalRequest.from_dict,
                {**signal, "resulting_revision": 4.9},
            ),
        )
        for decoder, payload in malformed:
            with self.subTest(decoder=decoder.__qualname__, payload=payload):
                with self.assertRaises(CampaignValidationError):
                    decoder(payload)

    def test_signal_and_acknowledgements_round_trip(self) -> None:
        signal = CampaignSignalRequest(
            campaign_id="campaign-1",
            attempt=1,
            signal_type=CampaignSignalType.CANCEL,
            resulting_revision=4,
        )
        self.assertEqual(CampaignSignalRequest.from_dict(signal.to_dict()), signal)
        acknowledgement = CampaignDispatchAcknowledgement(
            dispatch_id=campaign_dispatch_id("campaign-1", 1),
            runtime_reference="agent3:run-1",
            evidence_pointer="evidence:1",
        )
        self.assertEqual(
            CampaignDispatchAcknowledgement.from_dict(acknowledgement.to_dict()),
            acknowledgement,
        )
        signal_ack = CampaignSignalAcknowledgement(
            signal_id=signal.signal_id,
            evidence_pointer="evidence:2",
        )
        self.assertEqual(
            CampaignSignalAcknowledgement.from_dict(signal_ack.to_dict()),
            signal_ack,
        )

    def test_outcome_matrix_encodes_resource_proof_rule(self) -> None:
        dispatch_id = campaign_dispatch_id("campaign-1", 1)
        cases = (
            CampaignDispatchOutcome(
                dispatch_id=dispatch_id,
                kind=DispatchOutcomeKind.NOT_DISPATCHED,
                resources_released=True,
            ),
            CampaignDispatchOutcome(
                dispatch_id=dispatch_id,
                kind=DispatchOutcomeKind.UNKNOWN,
            ),
            CampaignDispatchOutcome(
                dispatch_id=dispatch_id,
                kind=DispatchOutcomeKind.ACCEPTED,
                runtime_reference="agent3:run-1",
            ),
            CampaignDispatchOutcome(
                dispatch_id=dispatch_id,
                kind=DispatchOutcomeKind.RUNNING,
                runtime_reference="agent3:run-1",
            ),
            CampaignDispatchOutcome(
                dispatch_id=dispatch_id,
                kind=DispatchOutcomeKind.COMPLETED,
                runtime_reference="agent3:run-1",
                resources_released=True,
            ),
            CampaignDispatchOutcome(
                dispatch_id=dispatch_id,
                kind=DispatchOutcomeKind.FAILED,
                runtime_reference="agent3:run-1",
                resources_released=True,
                error="run failed",
            ),
        )
        for outcome in cases:
            with self.subTest(kind=outcome.kind):
                self.assertEqual(
                    CampaignDispatchOutcome.from_dict(outcome.to_dict()),
                    outcome,
                )

        self.assertFalse(cases[0].requires_resource_reconciliation)
        self.assertTrue(cases[1].requires_resource_reconciliation)
        self.assertTrue(cases[2].requires_resource_reconciliation)
        self.assertTrue(cases[3].requires_resource_reconciliation)
        self.assertTrue(cases[4].terminal)
        self.assertTrue(cases[5].terminal)

    def test_terminal_run_state_without_resource_attestation_is_rejected(self) -> None:
        dispatch_id = campaign_dispatch_id("campaign-1", 1)
        for kind, kwargs in (
            (DispatchOutcomeKind.COMPLETED, {}),
            (DispatchOutcomeKind.FAILED, {"error": "failed"}),
        ):
            with self.subTest(kind=kind):
                with self.assertRaises(CampaignValidationError):
                    CampaignDispatchOutcome(
                        dispatch_id=dispatch_id,
                        kind=kind,
                        runtime_reference="agent3:run-1",
                        **kwargs,
                    )

    def test_state_markers_round_trip_and_old_records_default_closed_flags_off(self) -> None:
        legacy = {
            "campaign_id": "campaign-1",
            "status": CampaignStatus.RUNNING.value,
            "revision": 1,
            "attempt": 1,
            "updated_at": NOW.isoformat().replace("+00:00", "Z"),
            "checkpoint_id": None,
            "last_error": None,
        }
        restored = CampaignState.from_dict(legacy)
        self.assertFalse(restored.execution_intervention_required)
        self.assertFalse(restored.resource_reconciliation_required)

        marked = CampaignState(
            campaign_id="campaign-1",
            status=CampaignStatus.RUNNING,
            revision=2,
            attempt=1,
            updated_at=NOW,
            execution_intervention_required=True,
            resource_reconciliation_required=True,
        )
        self.assertEqual(CampaignState.from_dict(marked.to_dict()), marked)
        with self.assertRaises(CampaignValidationError):
            CampaignState.from_dict({**legacy, "resource_reconciliation_required": 1})

    def test_contract_is_runtime_checkable_and_import_is_dormant(self) -> None:
        self.assertIsInstance(_Executor(), CampaignHandoffExecutor)
        self.assertEqual(
            CampaignEventKind.DISPATCH_REQUESTED.value,
            "dispatch_requested",
        )
        self.assertEqual(
            CampaignEventKind.RESOURCE_RECONCILIATION_RESOLVED.value,
            "resource_reconciliation_resolved",
        )

    def test_invalid_identity_inputs_fail_closed(self) -> None:
        for call in (
            lambda: campaign_dispatch_id("campaign-1", 0),
            lambda: campaign_dispatch_id(" ", 1),
            lambda: campaign_signal_id("campaign-1", 1, "bogus", 2),
            lambda: campaign_signal_id("campaign-1", 1, CampaignSignalType.PAUSE, 0),
        ):
            with self.subTest(call=call):
                with self.assertRaises((CampaignValidationError, ValueError)):
                    call()


if __name__ == "__main__":
    unittest.main()
