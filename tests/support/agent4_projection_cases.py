"""A4-11 projection-intent and reconciliation contract cases."""

from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from app.agent4.domain import (
    CampaignEvent,
    CampaignEventKind,
    CampaignRecord,
    CampaignSpec,
    CampaignState,
    CampaignStatus,
)
from app.agent4.projection import (
    CampaignProjectionError,
    CampaignProjectionIntent,
    CampaignProjectionReconciler,
    CampaignProjectionSpec,
    CampaignStateProjectionService,
)
from app.agent4.repository import JsonCampaignRepository
from app.agent4.timeline import JsonCampaignTimelineStore


NOW = datetime(2026, 7, 31, 11, 30, tzinfo=timezone.utc)


def _record(*, revision: int = 1) -> CampaignRecord:
    spec = CampaignSpec(
        campaign_id="projection-campaign",
        name="Projection campaign",
        workflow="agent3.write-pilot",
        created_at=NOW,
    )
    state = CampaignState(
        campaign_id=spec.campaign_id,
        status=CampaignStatus.RUNNING,
        revision=revision,
        attempt=1,
        updated_at=NOW,
    )
    return CampaignRecord(spec=spec, state=state)


class Agent4ProjectionTests(unittest.TestCase):
    def test_projection_identity_is_deterministic_and_payload_independent(self) -> None:
        first = CampaignProjectionIntent(
            campaign_id="projection-campaign",
            state_revision=3,
            kind=CampaignEventKind.STARTED,
            occurred_at=NOW,
            payload={"runtime_reference": "run-a"},
        )
        same_cause = CampaignProjectionIntent(
            campaign_id="projection-campaign",
            state_revision=3,
            kind=CampaignEventKind.STARTED,
            occurred_at=NOW,
            payload={"runtime_reference": "run-b"},
        )
        other_revision = CampaignProjectionIntent(
            campaign_id="projection-campaign",
            state_revision=4,
            kind=CampaignEventKind.STARTED,
            occurred_at=NOW,
        )

        self.assertEqual(first.event_id, same_cause.event_id)
        self.assertNotEqual(first.event_id, other_revision.event_id)
        self.assertEqual(
            CampaignProjectionIntent.from_dict(first.to_dict()),
            first,
        )

    def test_state_and_intent_survive_crash_before_timeline_append(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repository = JsonCampaignRepository(root / "campaigns")
            timeline = JsonCampaignTimelineStore(root / "timeline")
            reconciler = CampaignProjectionReconciler(
                repository=repository,
                timeline=timeline,
            )
            projector = CampaignStateProjectionService(
                repository=repository,
                reconciler=reconciler,
            )
            record = _record()

            projector.persist(
                record,
                (
                    CampaignProjectionSpec(
                        kind=CampaignEventKind.STARTED,
                        occurred_at=NOW,
                        payload={"attempt": 1},
                    ),
                ),
                reconcile=False,
            )

            self.assertEqual(repository.get(record.spec.campaign_id), record)
            self.assertEqual(len(repository.pending_projections()), 1)
            self.assertEqual(timeline.list(record.spec.campaign_id), ())

            restarted_repository = JsonCampaignRepository(root / "campaigns")
            restarted_timeline = JsonCampaignTimelineStore(root / "timeline")
            report = CampaignProjectionReconciler(
                repository=restarted_repository,
                timeline=restarted_timeline,
            ).reconcile(record.spec.campaign_id)

            self.assertEqual(report.appended, 1)
            self.assertEqual(report.acknowledged, 1)
            self.assertEqual(restarted_repository.pending_projections(), ())
            entries = restarted_timeline.list(record.spec.campaign_id)
            self.assertEqual(len(entries), 1)
            self.assertEqual(entries[0].event.kind, CampaignEventKind.STARTED)

    def test_existing_identical_event_is_acknowledged_without_duplicate(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repository = JsonCampaignRepository(root / "campaigns")
            timeline = JsonCampaignTimelineStore(root / "timeline")
            record = _record()
            intent = CampaignProjectionIntent(
                campaign_id=record.spec.campaign_id,
                state_revision=record.state.revision,
                kind=CampaignEventKind.STARTED,
                occurred_at=NOW,
                payload={"attempt": 1},
            )
            repository.save_with_projections(record, (intent,))
            timeline.append(
                CampaignEvent(
                    event_id=intent.event_id,
                    campaign_id=intent.campaign_id,
                    kind=intent.kind,
                    sequence=1,
                    occurred_at=intent.occurred_at,
                    payload=intent.payload,
                )
            )

            report = CampaignProjectionReconciler(
                repository=repository,
                timeline=timeline,
            ).reconcile(record.spec.campaign_id)

            self.assertEqual(report.appended, 0)
            self.assertEqual(report.already_present, 1)
            self.assertEqual(report.acknowledged, 1)
            self.assertEqual(len(timeline.list(record.spec.campaign_id)), 1)
            self.assertEqual(repository.pending_projections(), ())

    def test_conflicting_content_with_same_event_id_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repository = JsonCampaignRepository(root / "campaigns")
            timeline = JsonCampaignTimelineStore(root / "timeline")
            record = _record()
            intent = CampaignProjectionIntent(
                campaign_id=record.spec.campaign_id,
                state_revision=record.state.revision,
                kind=CampaignEventKind.STARTED,
                occurred_at=NOW,
                payload={"attempt": 1},
            )
            repository.save_with_projections(record, (intent,))
            timeline.append(
                CampaignEvent(
                    event_id=intent.event_id,
                    campaign_id=intent.campaign_id,
                    kind=intent.kind,
                    sequence=1,
                    occurred_at=intent.occurred_at,
                    payload={"attempt": 99},
                )
            )

            with self.assertRaises(CampaignProjectionError):
                CampaignProjectionReconciler(
                    repository=repository,
                    timeline=timeline,
                ).reconcile(record.spec.campaign_id)

            self.assertEqual(len(repository.pending_projections()), 1)
            self.assertEqual(len(timeline.list(record.spec.campaign_id)), 1)

    def test_construction_is_dormant_and_creates_no_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "agent4"
            repository = JsonCampaignRepository(root / "campaigns")
            timeline = JsonCampaignTimelineStore(root / "timeline")
            reconciler = CampaignProjectionReconciler(
                repository=repository,
                timeline=timeline,
            )
            CampaignStateProjectionService(
                repository=repository,
                reconciler=reconciler,
            )

            self.assertFalse(root.exists())


__all__ = ["Agent4ProjectionTests"]
