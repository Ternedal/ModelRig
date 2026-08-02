#!/usr/bin/env python3
"""Fail-closed regressions for ADR-A4-008 Slice 2 persistence."""

from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from app.agent4.domain import (
    CampaignEventKind,
    CampaignRecord,
    CampaignSpec,
    CampaignState,
    CampaignStatus,
    CampaignValidationError,
)
from app.agent4.handoff import (
    CampaignDispatchAcknowledgement,
    CampaignDispatchRequest,
    CampaignSignalAcknowledgement,
)
from app.agent4.handoff_persistence import (
    CampaignHandoffIntent,
    CampaignHandoffPhase,
)
from app.agent4.projection import CampaignProjectionIntent
from app.agent4.repository import CampaignRepositoryError, JsonCampaignRepository


NOW = datetime(2026, 8, 2, 11, 30, tzinfo=timezone.utc)


def _record(*, revision: int, attempt: int) -> CampaignRecord:
    spec = CampaignSpec(
        campaign_id="handoff-regression",
        name="Handoff regression",
        workflow="agent3.write-pilot",
        created_at=NOW,
    )
    return CampaignRecord(
        spec=spec,
        state=CampaignState(
            campaign_id=spec.campaign_id,
            status=CampaignStatus.RUNNING,
            revision=revision,
            attempt=attempt,
            updated_at=NOW,
        ),
    )


def _intent(
    record: CampaignRecord,
    *,
    workflow: str | None = None,
) -> CampaignHandoffIntent:
    return CampaignHandoffIntent(
        campaign_id=record.spec.campaign_id,
        state_revision=record.state.revision,
        request=CampaignDispatchRequest(
            campaign_id=record.spec.campaign_id,
            attempt=record.state.attempt,
            workflow=workflow or record.spec.workflow,
            campaign_revision=record.state.revision,
        ),
    )


def _confirmation(
    record: CampaignRecord,
    intent: CampaignHandoffIntent,
) -> CampaignProjectionIntent:
    return CampaignProjectionIntent(
        campaign_id=record.spec.campaign_id,
        state_revision=record.state.revision,
        kind=CampaignEventKind.DISPATCH_CONFIRMED,
        occurred_at=NOW,
        payload={
            "dispatch_id": intent.intent_id,
            "runtime_reference": "agent3:run-1",
        },
        producer_id="slice-2-regression",
    )


class Agent4HandoffPersistenceRegressionTests(unittest.TestCase):
    def test_acknowledged_intent_cannot_bypass_repository_transition(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository = JsonCampaignRepository(Path(directory))
            record = _record(revision=1, attempt=1)
            requested = _intent(record)
            acknowledged = requested.acknowledge(
                CampaignDispatchAcknowledgement(
                    dispatch_id=requested.intent_id,
                    runtime_reference="agent3:run-1",
                )
            )

            with self.assertRaises(CampaignRepositoryError):
                repository.save_with_handoffs(record, (acknowledged,))
            self.assertIsNone(repository.get(record.spec.campaign_id))

    def test_conflicting_requested_payloads_with_same_identity_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository = JsonCampaignRepository(Path(directory))
            record = _record(revision=1, attempt=1)
            first = _intent(record)
            conflicting = _intent(record, workflow="agent3.other-workflow")
            self.assertEqual(first.intent_id, conflicting.intent_id)
            self.assertNotEqual(first, conflicting)

            with self.assertRaises(CampaignRepositoryError):
                repository.save_with_handoffs(record, (first, conflicting))
            self.assertIsNone(repository.get(record.spec.campaign_id))

    def test_record_regression_cannot_make_preserved_intent_future(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository = JsonCampaignRepository(Path(directory))
            current = _record(revision=2, attempt=2)
            intent = _intent(current)
            repository.save_with_handoffs(current, (intent,))

            with self.assertRaises(CampaignRepositoryError):
                repository.save(_record(revision=1, attempt=1))

            self.assertEqual(repository.get(current.spec.campaign_id), current)
            self.assertEqual(repository.pending_handoffs(), (intent,))

    def test_dispatch_and_signal_acknowledgement_types_cannot_cross(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository = JsonCampaignRepository(Path(directory))
            record = _record(revision=1, attempt=1)
            intent = _intent(record)
            repository.save_with_handoffs(record, (intent,))

            with self.assertRaises(CampaignValidationError):
                repository.acknowledge_handoff(
                    record.spec.campaign_id,
                    intent.intent_id,
                    CampaignSignalAcknowledgement(signal_id=intent.intent_id),
                )

            self.assertEqual(repository.pending_handoffs(), (intent,))

    def test_acknowledgement_and_audit_intent_are_one_atomic_rewrite(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repository = JsonCampaignRepository(root)
            record = _record(revision=1, attempt=1)
            intent = _intent(record)
            confirmation = _confirmation(record, intent)
            repository.save_with_handoffs(record, (intent,))
            acknowledgement = CampaignDispatchAcknowledgement(
                dispatch_id=intent.intent_id,
                runtime_reference="agent3:run-1",
            )

            self.assertTrue(
                repository.acknowledge_handoff(
                    record.spec.campaign_id,
                    intent.intent_id,
                    acknowledgement,
                    projection_intents=(confirmation,),
                )
            )

            restarted = JsonCampaignRepository(root)
            persisted = restarted.pending_handoffs()[0]
            self.assertIs(persisted.phase, CampaignHandoffPhase.ACKNOWLEDGED)
            self.assertEqual(persisted.acknowledgement, acknowledgement)
            self.assertEqual(restarted.pending_projections(), (confirmation,))

    def test_failed_ack_rewrite_persists_neither_ack_nor_audit_intent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repository = JsonCampaignRepository(root)
            record = _record(revision=1, attempt=1)
            intent = _intent(record)
            confirmation = _confirmation(record, intent)
            repository.save_with_handoffs(record, (intent,))

            with patch(
                "app.agent4.repository.os.replace",
                side_effect=OSError("injected acknowledgement failure"),
            ):
                with self.assertRaises(CampaignRepositoryError):
                    repository.acknowledge_handoff(
                        record.spec.campaign_id,
                        intent.intent_id,
                        CampaignDispatchAcknowledgement(
                            dispatch_id=intent.intent_id,
                            runtime_reference="agent3:run-1",
                        ),
                        projection_intents=(confirmation,),
                    )

            restarted = JsonCampaignRepository(root)
            self.assertEqual(restarted.pending_handoffs(), (intent,))
            self.assertEqual(restarted.pending_projections(), ())


if __name__ == "__main__":
    unittest.main()
