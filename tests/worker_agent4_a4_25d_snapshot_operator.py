#!/usr/bin/env python3
"""A4-25d contracts for immutable snapshot-bound Agent 4 operator reads."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "worker"))

from app.agent4.domain import (  # noqa: E402
    CampaignEvent,
    CampaignEventKind,
    CampaignRecord,
    CampaignSpec,
    CampaignState,
)
from app.agent4.operator_evidence import (  # noqa: E402
    CampaignEvidenceRecordNotFoundError,
)
from app.agent4.service import CampaignNotFoundError  # noqa: E402
from app.agent4.snapshot_cursor import (  # noqa: E402
    OperatorSnapshotCursor,
    OperatorSnapshotCursorError,
)
from app.agent4.snapshot_operator import (  # noqa: E402
    Agent4SnapshotOperatorReadService,
)
from app.agent4.snapshot_operator_api import (  # noqa: E402
    SNAPSHOT_OPERATOR_API_SCHEMA,
    build_agent4_snapshot_operator_router,
)
from app.agent4.snapshot_store import (  # noqa: E402
    JsonOperatorSnapshotStore,
    OperatorCampaignSnapshot,
    OperatorRootSnapshot,
    OperatorSnapshotNotFoundError,
)
from app.agent4.timeline import (  # noqa: E402
    CampaignEvidenceReference,
    JsonCampaignTimelineStore,
)
from app.agent4.timeline_evidence import (  # noqa: E402
    CampaignEvidenceRecordService,
    JsonCampaignEvidenceRecordStore,
)

UTC = timezone.utc
BASE = datetime(2026, 8, 10, 19, 30, tzinfo=UTC)


class _Clock:
    def __init__(self, value: datetime = BASE + timedelta(minutes=10)) -> None:
        self.value = value

    def now(self) -> datetime:
        return self.value


def _record(campaign_id: str, *, revision: int = 0) -> CampaignRecord:
    return CampaignRecord(
        spec=CampaignSpec(
            campaign_id=campaign_id,
            name=f"Campaign {campaign_id}",
            workflow="agent3.write-pilot",
            created_at=BASE + timedelta(seconds=ord(campaign_id[-1]) if campaign_id else 0),
        ),
        state=CampaignState(
            campaign_id=campaign_id,
            revision=revision,
            updated_at=BASE + timedelta(seconds=revision),
        ),
    )


def _event(campaign_id: str, sequence: int) -> CampaignEvent:
    return CampaignEvent(
        event_id=f"{campaign_id}-event-{sequence}",
        campaign_id=campaign_id,
        kind=(
            CampaignEventKind.CREATED
            if sequence == 1
            else CampaignEventKind.RECOVERED
        ),
        sequence=sequence,
        occurred_at=BASE + timedelta(seconds=sequence),
        payload={"sequence": sequence},
    )


class _Fixture:
    def __init__(
        self,
        directory: str,
        *,
        max_age: timedelta = timedelta(hours=1),
        clock: _Clock | None = None,
    ) -> None:
        root = Path(directory)
        self.clock = clock or _Clock()
        self.timeline = JsonCampaignTimelineStore(root / "timeline")
        self.evidence = JsonCampaignEvidenceRecordStore(root / "evidence")
        self.evidence_recorder = CampaignEvidenceRecordService(
            timeline=self.timeline,
            records=self.evidence,
        )
        self.snapshots = JsonOperatorSnapshotStore(
            root / "snapshots",
            max_age=max_age,
            clock=self.clock.now,
        )
        self.service = Agent4SnapshotOperatorReadService(
            snapshots=self.snapshots,
            timeline=self.timeline,
            evidence=self.evidence,
        )
        self.current: OperatorRootSnapshot | None = None

    def append_event(self, campaign_id: str) -> None:
        sequence = len(self.timeline.list(campaign_id)) + 1
        self.timeline.append(_event(campaign_id, sequence))

    def append_evidence(self, campaign_id: str, suffix: str) -> str:
        timeline = self.timeline.list(campaign_id)
        if not timeline:
            raise AssertionError("timeline required before evidence")
        evidence_id = f"{campaign_id}-evidence-{suffix}"
        reference = CampaignEvidenceReference(
            evidence_id=evidence_id,
            media_type="application/json",
            location=f"evidence/{evidence_id}.json",
            sha256=(suffix[0].lower() if suffix else "a") * 64,
            size_bytes=10,
            metadata={"fixture": suffix},
        )
        self.evidence_recorder.record(
            campaign_id,
            reference,
            recorded_at=BASE + timedelta(minutes=len(self.evidence.list(campaign_id)) + 1),
            related_event_id=timeline[-1].event.event_id,
        )
        return evidence_id

    def publish(
        self,
        records: tuple[CampaignRecord, ...],
        *,
        at: datetime,
    ) -> OperatorRootSnapshot:
        mapping: dict[str, str] = {}
        for record in records:
            campaign_id = record.spec.campaign_id
            timeline = self.timeline.list(campaign_id)
            evidence = self.evidence.list(campaign_id)
            campaign_snapshot = OperatorCampaignSnapshot.create(
                record,
                timeline_head_sequence=len(timeline),
                timeline_head_sha256=(timeline[-1].entry_hash if timeline else None),
                evidence_head_sequence=len(evidence),
                evidence_head_sha256=(evidence[-1].record_hash if evidence else None),
                latest_evidence_timeline_head_sha256=(
                    evidence[-1].timeline_head_hash if evidence else None
                ),
            )
            self.snapshots.write_campaign_snapshot(campaign_snapshot)
            mapping[campaign_id] = campaign_snapshot.snapshot_id
        root = OperatorRootSnapshot.create(
            root_sequence=(self.current.root_sequence + 1 if self.current else 1),
            parent_snapshot_id=(self.current.snapshot_id if self.current else None),
            published_at=at,
            campaigns=mapping,
        )
        self.snapshots.publish_root(
            root,
            expected_parent=(self.current.snapshot_id if self.current else None),
        )
        self.current = root
        return root


class SnapshotBoundOperatorTests(unittest.TestCase):
    def test_old_root_keeps_immutable_record_and_timeline_prefix_after_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = _Fixture(directory)
            fixture.append_event("campaign-a")
            first_record = _record("campaign-a", revision=0)
            first = fixture.publish((first_record,), at=BASE)

            fixture.append_event("campaign-a")
            second_record = _record("campaign-a", revision=1)
            second = fixture.publish(
                (second_record,),
                at=BASE + timedelta(minutes=1),
            )

            old_detail = fixture.service.campaign(
                "campaign-a",
                snapshot_id=first.snapshot_id,
            )
            old_timeline = fixture.service.timeline_page(
                "campaign-a",
                snapshot_id=first.snapshot_id,
                limit=100,
            )
            current_detail = fixture.service.campaign("campaign-a")

            self.assertEqual(old_detail.snapshot_id, first.snapshot_id)
            self.assertEqual(old_detail.campaign.record.state.revision, 0)
            self.assertEqual(old_detail.campaign.timeline_entries, 1)
            self.assertEqual(len(old_timeline.page.entries), 1)
            self.assertEqual(old_timeline.head_cursor.snapshot_id, first.snapshot_id)
            self.assertEqual(old_timeline.page.head_cursor.sequence, 1)
            self.assertEqual(current_detail.snapshot_id, second.snapshot_id)
            self.assertEqual(current_detail.campaign.record.state.revision, 1)
            self.assertEqual(current_detail.campaign.timeline_entries, 2)

    def test_list_continuation_stays_on_original_root_after_new_campaign(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = _Fixture(directory)
            for campaign_id in ("campaign-a", "campaign-b"):
                fixture.append_event(campaign_id)
            first = fixture.publish(
                (_record("campaign-a"), _record("campaign-b")),
                at=BASE,
            )

            page1 = fixture.service.campaign_page(limit=1)
            self.assertEqual(page1.snapshot_id, first.snapshot_id)
            self.assertTrue(page1.has_more)

            fixture.append_event("campaign-c")
            second = fixture.publish(
                (
                    _record("campaign-a"),
                    _record("campaign-b"),
                    _record("campaign-c"),
                ),
                at=BASE + timedelta(minutes=1),
            )

            page2 = fixture.service.campaign_page(
                after=page1.next_cursor,
                snapshot_head=page1.head_cursor,
                limit=1,
            )

            self.assertEqual(page2.snapshot_id, first.snapshot_id)
            self.assertNotEqual(page2.snapshot_id, second.snapshot_id)
            self.assertEqual(len(page2.campaigns), 1)
            self.assertFalse(page2.has_more)

            with self.assertRaises(OperatorSnapshotCursorError):
                fixture.service.campaign_page(
                    snapshot_id=second.snapshot_id,
                    after=page1.next_cursor,
                    snapshot_head=page1.head_cursor,
                    limit=1,
                )

    def test_campaign_absent_from_old_root_is_not_backfilled_from_new_state(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = _Fixture(directory)
            fixture.append_event("campaign-a")
            first = fixture.publish((_record("campaign-a"),), at=BASE)
            fixture.append_event("campaign-b")
            fixture.publish(
                (_record("campaign-a"), _record("campaign-b")),
                at=BASE + timedelta(minutes=1),
            )

            with self.assertRaises(CampaignNotFoundError):
                fixture.service.campaign(
                    "campaign-b",
                    snapshot_id=first.snapshot_id,
                )

    def test_evidence_detail_page_and_verification_are_truncated_to_root(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = _Fixture(directory)
            fixture.append_event("campaign-a")
            first_evidence = fixture.append_evidence("campaign-a", "a")
            first = fixture.publish((_record("campaign-a"),), at=BASE)

            fixture.append_event("campaign-a")
            second_evidence = fixture.append_evidence("campaign-a", "b")
            fixture.publish(
                (_record("campaign-a", revision=1),),
                at=BASE + timedelta(minutes=1),
            )

            page = fixture.service.evidence_page(
                "campaign-a",
                snapshot_id=first.snapshot_id,
                limit=100,
            )
            verification = fixture.service.verification(
                "campaign-a",
                snapshot_id=first.snapshot_id,
            )
            detail = fixture.service.evidence(
                "campaign-a",
                first_evidence,
                snapshot_id=first.snapshot_id,
            )

            self.assertEqual([item.evidence_id for item in page.page.records], [first_evidence])
            self.assertEqual(page.page.head_cursor.sequence, 1)
            self.assertEqual(verification.verification.record_count, 1)
            self.assertEqual(detail.evidence.evidence_id, first_evidence)
            with self.assertRaises(CampaignEvidenceRecordNotFoundError):
                fixture.service.evidence(
                    "campaign-a",
                    second_evidence,
                    snapshot_id=first.snapshot_id,
                )

    def test_restart_preserves_retained_snapshot_meaning_without_session_state(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = _Fixture(directory)
            fixture.append_event("campaign-a")
            first = fixture.publish((_record("campaign-a"),), at=BASE)
            fixture.append_event("campaign-a")
            fixture.publish(
                (_record("campaign-a", revision=1),),
                at=BASE + timedelta(minutes=1),
            )

            root = Path(directory)
            restarted_store = JsonOperatorSnapshotStore(
                root / "snapshots",
                max_age=timedelta(hours=1),
                clock=fixture.clock.now,
            )
            restarted = Agent4SnapshotOperatorReadService(
                snapshots=restarted_store,
                timeline=JsonCampaignTimelineStore(root / "timeline"),
                evidence=JsonCampaignEvidenceRecordStore(root / "evidence"),
            )

            detail = restarted.campaign(
                "campaign-a",
                snapshot_id=first.snapshot_id,
            )
            self.assertEqual(detail.snapshot_id, first.snapshot_id)
            self.assertEqual(detail.campaign.record.state.revision, 0)
            self.assertEqual(detail.campaign.timeline_entries, 1)

    def test_expired_historical_root_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            clock = _Clock(BASE)
            fixture = _Fixture(
                directory,
                max_age=timedelta(minutes=1),
                clock=clock,
            )
            fixture.append_event("campaign-a")
            first = fixture.publish((_record("campaign-a"),), at=BASE)
            fixture.append_event("campaign-a")
            fixture.publish(
                (_record("campaign-a", revision=1),),
                at=BASE + timedelta(minutes=2),
            )
            clock.value = BASE + timedelta(minutes=3)

            with self.assertRaises(OperatorSnapshotNotFoundError):
                fixture.service.campaign(
                    "campaign-a",
                    snapshot_id=first.snapshot_id,
                )

    def test_snapshot_cursor_round_trip_preserves_root_and_inner_cursor(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = _Fixture(directory)
            fixture.append_event("campaign-a")
            root = fixture.publish((_record("campaign-a"),), at=BASE)
            page = fixture.service.timeline_page("campaign-a", limit=1)

            decoded = OperatorSnapshotCursor.from_dict(
                page.next_cursor.to_dict(),
                cursor_type=type(page.page.next_cursor),
            )

            self.assertEqual(decoded.snapshot_id, root.snapshot_id)
            self.assertEqual(decoded.cursor, page.page.next_cursor)


class SnapshotBoundOperatorApiTests(unittest.TestCase):
    def _client(self, fixture: _Fixture) -> TestClient:
        app = FastAPI()
        app.include_router(build_agent4_snapshot_operator_router(fixture.service))
        return TestClient(app)

    def test_v2_response_returns_authoritative_snapshot_id_and_bound_cursors(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = _Fixture(directory)
            fixture.append_event("campaign-a")
            root = fixture.publish((_record("campaign-a"),), at=BASE)
            client = self._client(fixture)

            response = client.get(
                "/experimental/agent4/operator/campaigns",
                params={"limit": "1"},
            )

            self.assertEqual(response.status_code, 200)
            body = response.json()
            self.assertEqual(body["schema"], SNAPSHOT_OPERATOR_API_SCHEMA)
            self.assertEqual(body["snapshot_id"], root.snapshot_id)
            self.assertEqual(body["next_cursor"]["snapshot_id"], root.snapshot_id)
            self.assertEqual(body["head_cursor"]["snapshot_id"], root.snapshot_id)

    def test_unknown_valid_snapshot_id_is_wire_distinct_410(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = _Fixture(directory)
            fixture.append_event("campaign-a")
            fixture.publish((_record("campaign-a"),), at=BASE)
            client = self._client(fixture)

            response = client.get(
                "/experimental/agent4/operator/campaigns/campaign-a",
                params={"snapshot_id": "f" * 64},
            )

            self.assertEqual(response.status_code, 410)
            self.assertEqual(
                response.json()["detail"],
                "agent4 operator snapshot unavailable",
            )

    def test_cursor_snapshot_mismatch_is_rejected_without_falling_to_current(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = _Fixture(directory)
            fixture.append_event("campaign-a")
            first = fixture.publish((_record("campaign-a"),), at=BASE)
            page = fixture.service.campaign_page(limit=1)
            fixture.append_event("campaign-b")
            second = fixture.publish(
                (_record("campaign-a"), _record("campaign-b")),
                at=BASE + timedelta(minutes=1),
            )
            client = self._client(fixture)

            response = client.get(
                "/experimental/agent4/operator/campaigns",
                params={
                    "snapshot_id": second.snapshot_id,
                    "after": json.dumps(page.next_cursor.to_dict()),
                    "snapshot_head": json.dumps(page.head_cursor.to_dict()),
                },
            )

            self.assertNotEqual(first.snapshot_id, second.snapshot_id)
            self.assertEqual(response.status_code, 422)

    def test_v2_rejects_v1_snapshot_head_parameter_on_timeline(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = _Fixture(directory)
            fixture.append_event("campaign-a")
            fixture.publish((_record("campaign-a"),), at=BASE)
            client = self._client(fixture)

            response = client.get(
                "/experimental/agent4/operator/campaigns/campaign-a/timeline",
                params={"snapshot_head": "{}"},
            )

            self.assertEqual(response.status_code, 422)


if __name__ == "__main__":
    unittest.main()
