#!/usr/bin/env python3
"""ADR-A4-008 Slice 2 durable handoff persistence contracts."""

from __future__ import annotations

import hashlib
import json
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
    CampaignDispatchOutcome,
    CampaignDispatchRequest,
    CampaignSignalAcknowledgement,
    CampaignSignalRequest,
    CampaignSignalType,
    DispatchOutcomeKind,
)
from app.agent4.handoff_persistence import (
    CampaignHandoffIntent,
    CampaignHandoffPhase,
)
from app.agent4.projection import CampaignProjectionIntent
from app.agent4.repository import CampaignRepositoryError, JsonCampaignRepository


NOW = datetime(2026, 8, 2, 10, 30, tzinfo=timezone.utc)


def _record(
    *,
    campaign_id: str = "handoff-campaign",
    revision: int = 1,
    attempt: int = 1,
    reconciliation_required: bool = False,
) -> CampaignRecord:
    spec = CampaignSpec(
        campaign_id=campaign_id,
        name="Handoff campaign",
        workflow="agent3.write-pilot",
        created_at=NOW,
    )
    state = CampaignState(
        campaign_id=campaign_id,
        status=CampaignStatus.RUNNING,
        revision=revision,
        attempt=attempt,
        updated_at=NOW,
        resource_reconciliation_required=reconciliation_required,
    )
    return CampaignRecord(spec=spec, state=state)


def _dispatch_intent(
    record: CampaignRecord,
    *,
    workflow: str | None = None,
) -> CampaignHandoffIntent:
    request = CampaignDispatchRequest(
        campaign_id=record.spec.campaign_id,
        attempt=record.state.attempt,
        workflow=workflow or record.spec.workflow,
        campaign_revision=record.state.revision,
        parameters={"source": "slice-2"},
    )
    return CampaignHandoffIntent(
        campaign_id=record.spec.campaign_id,
        state_revision=record.state.revision,
        request=request,
    )


def _signal_intent(record: CampaignRecord) -> CampaignHandoffIntent:
    request = CampaignSignalRequest(
        campaign_id=record.spec.campaign_id,
        attempt=record.state.attempt,
        signal_type=CampaignSignalType.PAUSE,
        resulting_revision=record.state.revision,
    )
    return CampaignHandoffIntent(
        campaign_id=record.spec.campaign_id,
        state_revision=record.state.revision,
        request=request,
    )


def _projection(record: CampaignRecord) -> CampaignProjectionIntent:
    return CampaignProjectionIntent(
        campaign_id=record.spec.campaign_id,
        state_revision=record.state.revision,
        kind=CampaignEventKind.DISPATCH_REQUESTED,
        occurred_at=NOW,
        payload={"attempt": record.state.attempt},
        producer_id="slice-2-test",
    )


def _campaign_path(root: Path, campaign_id: str) -> Path:
    digest = hashlib.sha256(campaign_id.encode("utf-8")).hexdigest()
    return root / f"{digest}.campaign.json"


class Agent4HandoffPersistenceTests(unittest.TestCase):
    def test_v3_round_trip_contains_both_typed_collections(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repository = JsonCampaignRepository(root)
            record = _record()
            projection = _projection(record)
            handoff = _dispatch_intent(record)

            repository.save_with_intents(
                record,
                projection_intents=(projection,),
                handoff_intents=(handoff,),
            )

            raw = json.loads(
                _campaign_path(root, record.spec.campaign_id).read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(
                raw["schema"],
                "modelrig-agent4/campaign-envelope/v3",
            )
            self.assertEqual(len(raw["projection_intents"]), 1)
            self.assertEqual(len(raw["handoff_intents"]), 1)
            self.assertEqual(repository.get(record.spec.campaign_id), record)
            self.assertEqual(repository.pending_projections(), (projection,))
            self.assertEqual(repository.pending_handoffs(), (handoff,))

    def test_v2_envelope_remains_readable_without_rewrite(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            root.mkdir(parents=True, exist_ok=True)
            record = _record()
            projection = _projection(record)
            path = _campaign_path(root, record.spec.campaign_id)
            original = json.dumps(
                {
                    "schema": "modelrig-agent4/campaign-envelope/v2",
                    "record": record.to_dict(),
                    "projection_intents": [projection.to_dict()],
                },
                indent=2,
                sort_keys=True,
            ) + "\n"
            path.write_text(original, encoding="utf-8")

            repository = JsonCampaignRepository(root)
            self.assertEqual(repository.get(record.spec.campaign_id), record)
            self.assertEqual(repository.pending_projections(), (projection,))
            self.assertEqual(repository.pending_handoffs(), ())
            self.assertEqual(path.read_text(encoding="utf-8"), original)

    def test_bare_record_remains_readable_with_empty_intents(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            root.mkdir(parents=True, exist_ok=True)
            record = _record()
            _campaign_path(root, record.spec.campaign_id).write_text(
                json.dumps(record.to_dict()),
                encoding="utf-8",
            )

            repository = JsonCampaignRepository(root)
            self.assertEqual(repository.get(record.spec.campaign_id), record)
            self.assertEqual(repository.pending_projections(), ())
            self.assertEqual(repository.pending_handoffs(), ())

    def test_requested_dispatch_survives_restart_before_external_call(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            record = _record()
            intent = _dispatch_intent(record)
            JsonCampaignRepository(root).save_with_handoffs(record, (intent,))

            restarted = JsonCampaignRepository(root)
            self.assertEqual(restarted.get(record.spec.campaign_id), record)
            self.assertEqual(restarted.pending_handoffs(), (intent,))
            self.assertIs(
                restarted.pending_handoffs()[0].phase,
                CampaignHandoffPhase.REQUESTED,
            )

    def test_requested_signal_survives_restart_before_external_call(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            record = _record()
            intent = _signal_intent(record)
            JsonCampaignRepository(root).save_with_handoffs(record, (intent,))

            restarted = JsonCampaignRepository(root)
            self.assertEqual(restarted.pending_handoffs(), (intent,))

    def test_dispatch_acknowledgement_changes_only_matching_dispatch(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository = JsonCampaignRepository(Path(directory))
            record = _record()
            dispatch = _dispatch_intent(record)
            signal = _signal_intent(record)
            repository.save_with_handoffs(record, (dispatch, signal))
            acknowledgement = CampaignDispatchAcknowledgement(
                dispatch_id=dispatch.intent_id,
                runtime_reference="agent3:run-1",
                evidence_pointer="evidence:dispatch",
            )

            self.assertTrue(
                repository.acknowledge_handoff(
                    record.spec.campaign_id,
                    dispatch.intent_id,
                    acknowledgement,
                )
            )

            persisted_dispatch, persisted_signal = repository.pending_handoffs()
            self.assertIs(
                persisted_dispatch.phase,
                CampaignHandoffPhase.ACKNOWLEDGED,
            )
            self.assertEqual(
                persisted_dispatch.acknowledgement,
                acknowledgement,
            )
            self.assertEqual(persisted_signal, signal)

    def test_signal_acknowledgement_changes_only_matching_signal(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository = JsonCampaignRepository(Path(directory))
            record = _record()
            dispatch = _dispatch_intent(record)
            signal = _signal_intent(record)
            repository.save_with_handoffs(record, (dispatch, signal))
            acknowledgement = CampaignSignalAcknowledgement(
                signal_id=signal.intent_id,
                evidence_pointer="evidence:signal",
            )

            self.assertTrue(
                repository.acknowledge_handoff(
                    record.spec.campaign_id,
                    signal.intent_id,
                    acknowledgement,
                )
            )

            persisted_dispatch, persisted_signal = repository.pending_handoffs()
            self.assertEqual(persisted_dispatch, dispatch)
            self.assertIs(
                persisted_signal.phase,
                CampaignHandoffPhase.ACKNOWLEDGED,
            )

    def test_acknowledgement_retry_is_idempotent_and_conflict_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository = JsonCampaignRepository(Path(directory))
            record = _record()
            intent = _dispatch_intent(record)
            repository.save_with_handoffs(record, (intent,))
            first = CampaignDispatchAcknowledgement(
                dispatch_id=intent.intent_id,
                runtime_reference="agent3:run-1",
            )
            conflicting = CampaignDispatchAcknowledgement(
                dispatch_id=intent.intent_id,
                runtime_reference="agent3:run-2",
            )

            self.assertTrue(
                repository.acknowledge_handoff(
                    record.spec.campaign_id,
                    intent.intent_id,
                    first,
                )
            )
            self.assertFalse(
                repository.acknowledge_handoff(
                    record.spec.campaign_id,
                    intent.intent_id,
                    first,
                )
            )
            with self.assertRaises(CampaignValidationError):
                repository.acknowledge_handoff(
                    record.spec.campaign_id,
                    intent.intent_id,
                    conflicting,
                )

    def test_invalid_handoff_bindings_and_conflicting_duplicates_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository = JsonCampaignRepository(Path(directory))
            record = _record()
            foreign_record = _record(campaign_id="foreign")
            foreign = _dispatch_intent(foreign_record)
            future_record = _record(revision=2)
            future = _dispatch_intent(future_record)
            requested = _dispatch_intent(record)
            acknowledged = requested.acknowledge(
                CampaignDispatchAcknowledgement(
                    dispatch_id=requested.intent_id,
                    runtime_reference="agent3:run-1",
                )
            )

            with self.assertRaises(CampaignValidationError):
                repository.save_with_handoffs(record, (foreign,))
            with self.assertRaises(CampaignValidationError):
                repository.save_with_handoffs(record, (future,))
            with self.assertRaises(CampaignRepositoryError):
                repository.save_with_handoffs(
                    record,
                    (requested, acknowledged),
                )

    def test_record_and_projection_saves_preserve_handoffs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository = JsonCampaignRepository(Path(directory))
            record = _record()
            handoff = _dispatch_intent(record)
            projection = _projection(record)
            repository.save_with_handoffs(record, (handoff,))
            repository.save(record)
            repository.save_with_projections(record, (projection,))

            self.assertEqual(repository.pending_handoffs(), (handoff,))
            self.assertEqual(repository.pending_projections(), (projection,))

    def test_handoff_acknowledgement_preserves_projection_collection(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository = JsonCampaignRepository(Path(directory))
            record = _record()
            handoff = _dispatch_intent(record)
            projection = _projection(record)
            repository.save_with_intents(
                record,
                projection_intents=(projection,),
                handoff_intents=(handoff,),
            )

            repository.acknowledge_handoff(
                record.spec.campaign_id,
                handoff.intent_id,
                CampaignDispatchAcknowledgement(
                    dispatch_id=handoff.intent_id,
                    runtime_reference="agent3:run-1",
                ),
            )

            self.assertEqual(repository.pending_projections(), (projection,))

    def test_audit_ack_cannot_mutate_handoff_even_with_handoff_identity(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository = JsonCampaignRepository(Path(directory))
            record = _record()
            handoff = _dispatch_intent(record)
            projection = _projection(record)
            repository.save_with_intents(
                record,
                projection_intents=(projection,),
                handoff_intents=(handoff,),
            )

            self.assertFalse(
                repository.acknowledge_projection(
                    record.spec.campaign_id,
                    handoff.intent_id,
                )
            )
            self.assertEqual(repository.pending_handoffs(), (handoff,))
            self.assertTrue(
                repository.acknowledge_projection(
                    record.spec.campaign_id,
                    projection.event_id,
                )
            )
            self.assertEqual(repository.pending_projections(), ())
            self.assertEqual(repository.pending_handoffs(), (handoff,))

    def test_write_failure_before_replace_leaves_previous_envelope_intact(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repository = JsonCampaignRepository(root)
            original_record = _record()
            original_intent = _dispatch_intent(original_record)
            repository.save_with_handoffs(original_record, (original_intent,))
            updated_record = _record(revision=2, attempt=2)
            updated_intent = _dispatch_intent(updated_record)

            with patch(
                "app.agent4.repository.os.replace",
                side_effect=OSError("injected replace failure"),
            ):
                with self.assertRaises(CampaignRepositoryError):
                    repository.save_with_handoffs(
                        updated_record,
                        (updated_intent,),
                    )

            restarted = JsonCampaignRepository(root)
            self.assertEqual(
                restarted.get(original_record.spec.campaign_id),
                original_record,
            )
            self.assertEqual(
                restarted.pending_handoffs(),
                (original_intent,),
            )

    def test_construction_and_intent_values_are_dormant(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "campaigns"
            record = _record()
            _dispatch_intent(record)
            JsonCampaignRepository(root)
            self.assertFalse(root.exists())

    def test_unknown_outcome_is_not_a_handoff_acknowledgement(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository = JsonCampaignRepository(Path(directory))
            record = _record()
            intent = _dispatch_intent(record)
            repository.save_with_handoffs(record, (intent,))
            outcome = CampaignDispatchOutcome(
                dispatch_id=intent.intent_id,
                kind=DispatchOutcomeKind.UNKNOWN,
            )

            with self.assertRaises(CampaignValidationError):
                repository.acknowledge_handoff(
                    record.spec.campaign_id,
                    intent.intent_id,
                    outcome,
                )
            self.assertEqual(repository.pending_handoffs(), (intent,))

    def test_reconciliation_marker_survives_every_slice_two_path(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository = JsonCampaignRepository(Path(directory))
            record = _record(reconciliation_required=True)
            handoff = _dispatch_intent(record)
            projection = _projection(record)
            repository.save_with_intents(
                record,
                projection_intents=(projection,),
                handoff_intents=(handoff,),
            )
            repository.acknowledge_projection(
                record.spec.campaign_id,
                projection.event_id,
            )
            repository.acknowledge_handoff(
                record.spec.campaign_id,
                handoff.intent_id,
                CampaignDispatchAcknowledgement(
                    dispatch_id=handoff.intent_id,
                    runtime_reference="agent3:run-1",
                ),
            )

            persisted = repository.get(record.spec.campaign_id)
            self.assertIsNotNone(persisted)
            self.assertTrue(
                persisted.state.resource_reconciliation_required
            )


if __name__ == "__main__":
    unittest.main()
