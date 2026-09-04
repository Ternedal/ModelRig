#!/usr/bin/env python3
"""A4-19 campaign-list cursor and snapshot contracts."""

from __future__ import annotations

import sys
import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "worker"))

from app.agent4.campaign_list_query import (  # noqa: E402
    CAMPAIGN_LIST_CURSOR_SCHEMA,
    CampaignListQueryCursor,
    CampaignListQueryError,
    CampaignListSnapshotSummary,
    page_campaign_records,
)
from app.agent4.domain import (  # noqa: E402
    CampaignRecord,
    CampaignSpec,
    CampaignState,
    CampaignStatus,
    CampaignValidationError,
)

BASE_TIME = datetime(2026, 8, 9, 10, 0, tzinfo=timezone.utc)


def _record(index: int, status: CampaignStatus = CampaignStatus.QUEUED) -> CampaignRecord:
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
            last_error=("fixture failure" if status is CampaignStatus.FAILED else None),
        ),
    )


def _summaries(
    records: tuple[CampaignRecord, ...],
) -> dict[str, CampaignListSnapshotSummary]:
    return {
        record.spec.campaign_id: CampaignListSnapshotSummary(
            timeline_entries=index,
            event_entries=index,
            evidence_entries=max(0, index - 1),
            latest_timeline_hash=f"{index:x}" * 64,
        )
        for index, record in enumerate(records, start=1)
    }


class CampaignListQueryTests(unittest.TestCase):
    def test_pages_newest_first_without_duplicates_or_loss(self) -> None:
        records = tuple(_record(index) for index in range(1, 6))
        summaries = _summaries(records)
        first = page_campaign_records(records, summaries=summaries, limit=2)
        self.assertEqual(
            [record.spec.campaign_id for record in first.records],
            ["campaign-5", "campaign-4"],
        )
        self.assertTrue(first.has_more)
        self.assertEqual(first.start_cursor.position, 0)
        self.assertEqual(first.next_cursor.position, 2)
        self.assertEqual(first.head_cursor.position, 5)

        second = page_campaign_records(
            records,
            summaries=summaries,
            after=first.next_cursor,
            snapshot_head=first.head_cursor,
            limit=2,
        )
        third = page_campaign_records(
            records,
            summaries=summaries,
            after=second.next_cursor,
            snapshot_head=first.head_cursor,
            limit=2,
        )
        values = first.records + second.records + third.records
        self.assertEqual(
            [record.spec.campaign_id for record in values],
            [
                "campaign-5",
                "campaign-4",
                "campaign-3",
                "campaign-2",
                "campaign-1",
            ],
        )
        self.assertEqual(len({record.spec.campaign_id for record in values}), 5)
        self.assertFalse(third.has_more)
        self.assertEqual(third.next_cursor, first.head_cursor)

    def test_status_filter_is_canonical_and_cursor_bound(self) -> None:
        records = (
            _record(1, CampaignStatus.RUNNING),
            _record(2, CampaignStatus.PAUSED),
            _record(3, CampaignStatus.RUNNING),
            _record(4, CampaignStatus.FAILED),
        )
        summaries = _summaries(records)
        first = page_campaign_records(
            records,
            summaries=summaries,
            statuses=(CampaignStatus.PAUSED, CampaignStatus.RUNNING),
            limit=1,
        )
        self.assertEqual(
            [status.value for status in first.start_cursor.statuses],
            ["paused", "running"],
        )
        self.assertEqual(first.start_cursor.total, 3)

        with self.assertRaisesRegex(CampaignListQueryError, "status filter"):
            page_campaign_records(
                records,
                summaries=summaries,
                statuses=(CampaignStatus.RUNNING,),
                after=first.next_cursor,
                snapshot_head=first.head_cursor,
                limit=1,
            )

    def test_campaign_change_between_pages_is_rejected_as_stale(self) -> None:
        records = tuple(_record(index) for index in range(1, 4))
        summaries = _summaries(records)
        first = page_campaign_records(records, summaries=summaries, limit=1)
        changed = list(records)
        changed[1] = replace(
            changed[1],
            state=replace(
                changed[1].state,
                status=CampaignStatus.RUNNING,
                revision=changed[1].state.revision + 1,
            ),
        )
        with self.assertRaisesRegex(CampaignListQueryError, "stale snapshot"):
            page_campaign_records(
                tuple(changed),
                summaries=summaries,
                after=first.next_cursor,
                snapshot_head=first.head_cursor,
                limit=1,
            )

    def test_summary_change_between_pages_is_rejected_as_stale(self) -> None:
        records = tuple(_record(index) for index in range(1, 4))
        summaries = _summaries(records)
        first = page_campaign_records(records, summaries=summaries, limit=1)
        changed = dict(summaries)
        changed["campaign-2"] = replace(
            changed["campaign-2"],
            evidence_entries=changed["campaign-2"].evidence_entries + 1,
            latest_timeline_hash="f" * 64,
        )
        with self.assertRaisesRegex(CampaignListQueryError, "stale snapshot"):
            page_campaign_records(
                records,
                summaries=changed,
                after=first.next_cursor,
                snapshot_head=first.head_cursor,
                limit=1,
            )

    def test_cursor_round_trip_and_tamper_detection(self) -> None:
        records = tuple(_record(index) for index in range(1, 4))
        summaries = _summaries(records)
        first = page_campaign_records(records, summaries=summaries, limit=1)
        restored = CampaignListQueryCursor.from_dict(first.next_cursor.to_dict())
        self.assertEqual(restored, first.next_cursor)
        self.assertEqual(
            restored.to_dict()["schema"],
            CAMPAIGN_LIST_CURSOR_SCHEMA,
        )

        tampered_position = replace(restored, position=2)
        with self.assertRaisesRegex(CampaignListQueryError, "identity"):
            page_campaign_records(
                records,
                summaries=summaries,
                after=tampered_position,
                snapshot_head=first.head_cursor,
                limit=1,
            )

        tampered_last = replace(restored, last_campaign_id="campaign-1")
        with self.assertRaisesRegex(CampaignListQueryError, "identity"):
            page_campaign_records(
                records,
                summaries=summaries,
                after=tampered_last,
                snapshot_head=first.head_cursor,
                limit=1,
            )

        tampered_hash = replace(restored, snapshot_sha256="f" * 64)
        with self.assertRaisesRegex(CampaignListQueryError, "stale snapshot"):
            page_campaign_records(
                records,
                summaries=summaries,
                after=tampered_hash,
                snapshot_head=first.head_cursor,
                limit=1,
            )

    def test_summary_and_limit_validation_fail_closed(self) -> None:
        records = (_record(1),)
        summaries = _summaries(records)
        page = page_campaign_records(records, summaries=summaries, limit=1)
        raw = page.next_cursor.to_dict()
        raw["schema"] = "unknown"
        with self.assertRaisesRegex(CampaignValidationError, "schema"):
            CampaignListQueryCursor.from_dict(raw)
        with self.assertRaisesRegex(CampaignValidationError, "summary is missing"):
            page_campaign_records(records, summaries={}, limit=1)
        for invalid in (0, 1001, True, "1"):
            with self.assertRaises(CampaignValidationError):
                page_campaign_records(
                    records,
                    summaries=summaries,
                    limit=invalid,  # type: ignore[arg-type]
                )

    def test_empty_snapshot_has_valid_genesis_head(self) -> None:
        page = page_campaign_records((), summaries={}, limit=10)
        self.assertEqual(page.records, ())
        self.assertEqual(page.start_cursor.position, 0)
        self.assertEqual(page.head_cursor.position, 0)
        self.assertIsNone(page.head_cursor.last_campaign_id)
        self.assertFalse(page.has_more)


if __name__ == "__main__":
    unittest.main()
