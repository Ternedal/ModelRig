"""A4-13 bounded evidence query and operator-read contract cases."""

from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.agent4 import (
    CampaignEvidenceReference,
    CampaignNotFoundError,
    CampaignSpec,
    CampaignValidationError,
    compose_agent4_runtime,
)
from app.agent4.operator_evidence import (
    Agent4OperatorEvidenceReadService,
    CampaignEvidenceRecordNotFoundError,
)
from app.agent4.timeline_evidence import (
    CampaignEvidenceRecordService,
    JsonCampaignEvidenceRecordStore,
)
from app.agent4.timeline_evidence_query import (
    MAX_EVIDENCE_QUERY_PAGE_SIZE,
    CampaignEvidenceQueryCursor,
    CampaignEvidenceQueryCursorError,
    CampaignEvidenceQueryService,
)

BASE_TIME = datetime(2026, 8, 1, 9, 0, tzinfo=timezone.utc)


class _Clock:
    def now(self) -> datetime:
        return BASE_TIME


class _Executor:
    def dispatch(self, spec, state) -> str:
        return f"runtime:{spec.campaign_id}:{state.attempt}"

    def signal(self, campaign_id: str, command: str) -> None:
        return None


class Agent4EvidenceOperatorReadTests(unittest.TestCase):
    @staticmethod
    def _spec(campaign_id: str) -> CampaignSpec:
        return CampaignSpec(
            campaign_id=campaign_id,
            name=f"Campaign {campaign_id}",
            workflow="agent3.write-pilot",
            created_at=BASE_TIME,
        )

    @staticmethod
    def _reference(evidence_id: str, digest: str) -> CampaignEvidenceReference:
        return CampaignEvidenceReference(
            evidence_id=evidence_id,
            media_type="application/json",
            location=f"evidence/{evidence_id}.json",
            sha256=digest,
            size_bytes=128,
            metadata={"source": "operator-test"},
        )

    def _compose(self, root: Path):
        context = compose_agent4_runtime(
            root / "runtime",
            executor=_Executor(),
            resource_capacities={"gpu": 1},
            resource_resolver=lambda spec: {"gpu": 1},
            clock=_Clock(),
            resource_lease_ttl=timedelta(minutes=15),
        )
        records = JsonCampaignEvidenceRecordStore(root / "evidence")
        recorder = CampaignEvidenceRecordService(
            timeline=context.timeline,
            records=records,
        )
        query = CampaignEvidenceQueryService(records)
        operator = Agent4OperatorEvidenceReadService(
            scheduler=context.scheduler,
            records=records,
            query=query,
        )
        return context, records, recorder, query, operator

    def test_construction_is_dormant_and_uses_one_store(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            context, records, _, query, operator = self._compose(
                Path(directory) / "agent4"
            )
            self.assertIs(operator.scheduler, context.scheduler)
            self.assertIs(operator.records, records)
            self.assertIs(operator.query, query)
            self.assertEqual(list(Path(directory).iterdir()), [])

    def test_direct_lookup_and_verification_are_campaign_bound(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            context, _, recorder, _, operator = self._compose(Path(directory))
            campaign_id = "campaign-evidence-read"
            context.scheduler.submit(self._spec(campaign_id))
            event = context.timeline.latest(campaign_id)
            self.assertIsNotNone(event)
            assert event is not None
            record = recorder.record(
                campaign_id,
                self._reference("report", "a" * 64),
                recorded_at=BASE_TIME + timedelta(minutes=1),
                related_event_id=event.event.event_id,
            )

            self.assertEqual(operator.evidence(campaign_id, "report"), record)
            verification = operator.verification(campaign_id)
            self.assertEqual(verification.record_count, 1)
            self.assertEqual(verification.head_hash, record.record_hash)
            with self.assertRaises(CampaignEvidenceRecordNotFoundError):
                operator.evidence(campaign_id, "missing")
            with self.assertRaises(CampaignNotFoundError):
                operator.evidence("missing-campaign", "report")

    def test_pages_are_hash_bound_bounded_and_snapshot_stable(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            context, _, recorder, _, operator = self._compose(Path(directory))
            campaign_id = "campaign-evidence-page"
            context.scheduler.submit(self._spec(campaign_id))
            first = recorder.record(
                campaign_id,
                self._reference("first", "a" * 64),
                recorded_at=BASE_TIME + timedelta(minutes=1),
            )
            second = recorder.record(
                campaign_id,
                self._reference("second", "b" * 64),
                recorded_at=BASE_TIME + timedelta(minutes=2),
            )

            page = operator.evidence_page(campaign_id, limit=1)
            self.assertEqual(page.records, (first,))
            self.assertEqual(page.head_cursor.sequence, 2)
            self.assertTrue(page.has_more)

            third = recorder.record(
                campaign_id,
                self._reference("third", "c" * 64),
                recorded_at=BASE_TIME + timedelta(minutes=3),
            )
            stable = operator.evidence_page(
                campaign_id,
                after=page.next_cursor,
                snapshot_head=page.head_cursor,
                limit=10,
            )
            self.assertEqual(stable.records, (second,))
            self.assertEqual(stable.head_cursor.sequence, 2)
            self.assertFalse(stable.has_more)

            fresh = operator.evidence_page(
                campaign_id,
                after=page.next_cursor,
                limit=10,
            )
            self.assertEqual(fresh.records, (second, third))
            self.assertEqual(fresh.head_cursor.sequence, 3)

    def test_cursor_tampering_limits_and_composition_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            context, records, recorder, query, operator = self._compose(
                Path(directory)
            )
            campaign_id = "campaign-cursor"
            context.scheduler.submit(self._spec(campaign_id))
            record = recorder.record(
                campaign_id,
                self._reference("proof", "d" * 64),
                recorded_at=BASE_TIME + timedelta(minutes=1),
            )
            cursor = query.cursor_at(campaign_id, 1)
            self.assertEqual(
                CampaignEvidenceQueryCursor.from_dict(cursor.to_dict()),
                cursor,
            )
            self.assertEqual(cursor.record_hash, record.record_hash)

            with self.assertRaises(CampaignEvidenceQueryCursorError):
                operator.evidence_page(
                    campaign_id,
                    after=CampaignEvidenceQueryCursor(
                        campaign_id=campaign_id,
                        sequence=1,
                        record_hash="e" * 64,
                    ),
                )
            with self.assertRaises(CampaignEvidenceQueryCursorError):
                operator.evidence_page(
                    campaign_id,
                    after=CampaignEvidenceQueryCursor(
                        campaign_id="other",
                        sequence=0,
                        record_hash=None,
                    ),
                )
            for invalid in (0, MAX_EVIDENCE_QUERY_PAGE_SIZE + 1, True):
                with self.assertRaises(CampaignValidationError):
                    operator.evidence_page(campaign_id, limit=invalid)
            with self.assertRaises(CampaignNotFoundError):
                operator.evidence_page("missing")

            other = JsonCampaignEvidenceRecordStore(Path(directory) / "other")
            with self.assertRaises(CampaignValidationError):
                Agent4OperatorEvidenceReadService(
                    scheduler=context.scheduler,
                    records=records,
                    query=CampaignEvidenceQueryService(other),
                )

        with self.assertRaises(TypeError):
            CampaignEvidenceQueryService(object())  # type: ignore[arg-type]
