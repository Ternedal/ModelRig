#!/usr/bin/env python3
"""A4-23 failure-scope contract for filtered Agent 4 campaign lists."""

from __future__ import annotations

import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "worker"))

from app.agent4.domain import (  # noqa: E402
    CampaignRecord,
    CampaignSpec,
    CampaignState,
    CampaignStatus,
)
from app.agent4.operator import Agent4OperatorReadService  # noqa: E402
from app.agent4.timeline import (  # noqa: E402
    CampaignTimelineVerification,
    TimelineIntegrityError,
)
from app.agent4.timeline_query import CampaignTimelineQueryService  # noqa: E402

BASE_TIME = datetime(2026, 8, 10, 8, 0, tzinfo=timezone.utc)


def _record(
    index: int,
    status: CampaignStatus,
) -> CampaignRecord:
    campaign_id = f"campaign-{index}"
    return CampaignRecord(
        spec=CampaignSpec(
            campaign_id=campaign_id,
            name=f"Campaign {index}",
            workflow="agent3.read",
            created_at=BASE_TIME + timedelta(minutes=index),
        ),
        state=CampaignState(
            campaign_id=campaign_id,
            status=status,
            revision=index,
            updated_at=BASE_TIME + timedelta(minutes=index),
        ),
    )


class _ReadSource:
    def __init__(self, records: tuple[CampaignRecord, ...]) -> None:
        self._records = records

    def get(self, campaign_id: str) -> CampaignRecord:
        for record in self._records:
            if record.spec.campaign_id == campaign_id:
                return record
        raise KeyError(campaign_id)

    def list(self) -> tuple[CampaignRecord, ...]:
        return self._records


class _Timeline:
    def __init__(self, *, corrupt: set[str] | None = None) -> None:
        self.corrupt = set(corrupt or ())
        self.verify_calls: list[str] = []

    def append(self, event, *, evidence=()):  # pragma: no cover - read test only
        raise AssertionError("A4-23 read test must not append timeline state")

    def list(self, campaign_id: str):
        return ()

    def latest(self, campaign_id: str):
        return None

    def verify(self, campaign_id: str) -> CampaignTimelineVerification:
        self.verify_calls.append(campaign_id)
        if campaign_id in self.corrupt:
            raise TimelineIntegrityError(f"corrupt timeline for {campaign_id}")
        return CampaignTimelineVerification(
            campaign_id=campaign_id,
            entry_count=1,
            evidence_count=0,
            head_hash="a" * 64,
        )

    def replay(self, campaign_id: str, handler) -> int:
        return 0


class Agent4FilterBeforeSummaryTests(unittest.TestCase):
    @staticmethod
    def _service(
        records: tuple[CampaignRecord, ...],
        timeline: _Timeline,
    ) -> Agent4OperatorReadService:
        return Agent4OperatorReadService(
            scheduler=_ReadSource(records),
            timeline=timeline,
            query=CampaignTimelineQueryService(timeline),
        )

    def test_corrupt_excluded_campaign_does_not_widen_filtered_failure_scope(self) -> None:
        records = (
            _record(1, CampaignStatus.RUNNING),
            _record(2, CampaignStatus.QUEUED),
        )
        timeline = _Timeline(corrupt={"campaign-2"})
        service = self._service(records, timeline)

        page = service.campaign_page(statuses=CampaignStatus.RUNNING)

        self.assertEqual(
            [campaign.campaign_id for campaign in page.campaigns],
            ["campaign-1"],
        )
        self.assertEqual(timeline.verify_calls, ["campaign-1"])
        self.assertEqual(page.head_cursor.total, 1)
        self.assertEqual(
            [status.value for status in page.head_cursor.statuses],
            ["running"],
        )

    def test_corrupt_included_campaign_remains_fail_closed(self) -> None:
        records = (
            _record(1, CampaignStatus.RUNNING),
            _record(2, CampaignStatus.QUEUED),
        )
        timeline = _Timeline(corrupt={"campaign-1"})
        service = self._service(records, timeline)

        with self.assertRaisesRegex(TimelineIntegrityError, "campaign-1"):
            service.campaign_page(statuses=CampaignStatus.RUNNING)

        self.assertEqual(timeline.verify_calls, ["campaign-1"])

    def test_each_selected_overview_is_built_exactly_once_in_canonical_order(self) -> None:
        records = (
            _record(1, CampaignStatus.RUNNING),
            _record(2, CampaignStatus.QUEUED),
            _record(3, CampaignStatus.RUNNING),
            _record(4, CampaignStatus.QUEUED),
        )
        timeline = _Timeline()
        service = self._service(records, timeline)

        page = service.campaign_page(
            statuses=(CampaignStatus.RUNNING, CampaignStatus.QUEUED),
            limit=2,
        )

        # Snapshot integrity binds every selected record, not just the visible
        # page, so each selected summary is verified once and then reused.
        self.assertEqual(
            timeline.verify_calls,
            ["campaign-4", "campaign-3", "campaign-2", "campaign-1"],
        )
        self.assertEqual(len(timeline.verify_calls), len(set(timeline.verify_calls)))
        self.assertEqual(
            [campaign.campaign_id for campaign in page.campaigns],
            ["campaign-4", "campaign-3"],
        )
        self.assertEqual(
            [status.value for status in page.head_cursor.statuses],
            ["queued", "running"],
        )
        self.assertEqual(page.head_cursor.total, 4)


if __name__ == "__main__":
    unittest.main()
