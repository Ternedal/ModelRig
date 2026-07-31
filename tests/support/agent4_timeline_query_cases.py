"""A4-07 verified timeline query paging contract cases."""

from __future__ import annotations

import tempfile
import unittest
from datetime import timedelta
from pathlib import Path

from app.agent4 import (
    CampaignEventKind,
    CampaignTimelineQueryCursor,
    CampaignTimelineQueryCursorError,
    CampaignTimelineQueryService,
    CampaignValidationError,
    JsonCampaignTimelineStore,
    TimelineCampaignEventRecorder,
)

from agent4_timeline_cases import BASE_TIME


class Agent4TimelineQueryTests(unittest.TestCase):
    def _query_timeline(
        self,
        root: Path,
        *,
        campaign_id: str = "campaign-query",
        count: int = 3,
    ) -> JsonCampaignTimelineStore:
        timeline = JsonCampaignTimelineStore(root / "timeline")
        recorder = TimelineCampaignEventRecorder(timeline)
        for index in range(count):
            recorder.record(
                campaign_id,
                (
                    CampaignEventKind.CREATED
                    if index == 0
                    else CampaignEventKind.STARTED
                ),
                occurred_at=BASE_TIME + timedelta(seconds=index),
                payload={"index": index},
            )
        return timeline

    def test_empty_page_uses_genesis_cursors_and_round_trips(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            service = CampaignTimelineQueryService(
                JsonCampaignTimelineStore(Path(directory) / "timeline")
            )
            page = service.page("missing")

            self.assertEqual(page.entries, ())
            self.assertEqual(page.start_cursor.sequence, 0)
            self.assertEqual(page.next_cursor, page.start_cursor)
            self.assertEqual(page.head_cursor, page.start_cursor)
            self.assertFalse(page.has_more)
            self.assertEqual(
                CampaignTimelineQueryCursor.from_dict(
                    page.start_cursor.to_dict()
                ),
                page.start_cursor,
            )

    def test_bounded_pages_are_contiguous_and_hash_bound(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            timeline = self._query_timeline(root, count=5)
            service = CampaignTimelineQueryService(timeline)

            first = service.page("campaign-query", limit=2)
            second = service.page(
                "campaign-query",
                after=first.next_cursor,
                limit=2,
                snapshot_head=first.head_cursor,
            )
            third = service.page(
                "campaign-query",
                after=second.next_cursor,
                limit=2,
                snapshot_head=first.head_cursor,
            )

            self.assertEqual(
                [entry.event.sequence for entry in first.entries],
                [1, 2],
            )
            self.assertEqual(
                [entry.event.sequence for entry in second.entries],
                [3, 4],
            )
            self.assertEqual(
                [entry.event.sequence for entry in third.entries],
                [5],
            )
            self.assertTrue(first.has_more)
            self.assertTrue(second.has_more)
            self.assertFalse(third.has_more)
            self.assertEqual(first.head_cursor.sequence, 5)
            self.assertEqual(third.next_cursor, first.head_cursor)
            self.assertEqual(
                first.next_cursor.entry_hash,
                first.entries[-1].entry_hash,
            )

    def test_snapshot_head_excludes_clean_append_until_next_query(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            timeline = self._query_timeline(root, count=2)
            service = CampaignTimelineQueryService(timeline)
            first = service.page("campaign-query", limit=1)

            TimelineCampaignEventRecorder(timeline).record(
                "campaign-query",
                CampaignEventKind.STARTED,
                occurred_at=BASE_TIME + timedelta(seconds=2),
                payload={"index": 2},
            )

            frozen = service.page(
                "campaign-query",
                after=first.next_cursor,
                snapshot_head=first.head_cursor,
                limit=10,
            )
            grown = service.page(
                "campaign-query",
                after=first.next_cursor,
                limit=10,
            )

            self.assertEqual(
                [entry.event.sequence for entry in frozen.entries],
                [2],
            )
            self.assertFalse(frozen.has_more)
            self.assertEqual(frozen.head_cursor.sequence, 2)
            self.assertEqual(
                [entry.event.sequence for entry in grown.entries],
                [2, 3],
            )
            self.assertEqual(grown.head_cursor.sequence, 3)

    def test_old_cursor_remains_valid_after_append_only_growth(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            timeline = self._query_timeline(root, count=1)
            service = CampaignTimelineQueryService(timeline)
            cursor = service.cursor_at("campaign-query", 1)

            TimelineCampaignEventRecorder(timeline).record(
                "campaign-query",
                CampaignEventKind.STARTED,
                occurred_at=BASE_TIME + timedelta(seconds=1),
            )
            page = service.page(
                "campaign-query",
                after=cursor,
                limit=1,
            )

            self.assertEqual(
                [entry.event.sequence for entry in page.entries],
                [2],
            )
            self.assertFalse(page.has_more)

    def test_cursor_identity_hash_and_bounds_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            service = CampaignTimelineQueryService(
                self._query_timeline(root, count=2)
            )
            valid = service.cursor_at("campaign-query", 1)

            with self.assertRaises(CampaignTimelineQueryCursorError):
                service.page(
                    "campaign-query",
                    after=CampaignTimelineQueryCursor(
                        campaign_id="other",
                        sequence=valid.sequence,
                        entry_hash=valid.entry_hash,
                    ),
                )
            with self.assertRaises(CampaignTimelineQueryCursorError):
                service.page(
                    "campaign-query",
                    after=CampaignTimelineQueryCursor(
                        campaign_id="campaign-query",
                        sequence=1,
                        entry_hash="f" * 64,
                    ),
                )
            with self.assertRaises(CampaignTimelineQueryCursorError):
                service.page(
                    "campaign-query",
                    after=CampaignTimelineQueryCursor(
                        campaign_id="campaign-query",
                        sequence=3,
                        entry_hash="f" * 64,
                    ),
                )
            with self.assertRaises(CampaignTimelineQueryCursorError):
                service.page(
                    "campaign-query",
                    after=service.cursor_at("campaign-query", 2),
                    snapshot_head=service.cursor_at("campaign-query", 1),
                )

    def test_cursor_at_and_input_validation_are_explicit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            service = CampaignTimelineQueryService(
                self._query_timeline(root, count=2)
            )
            genesis = service.cursor_at("campaign-query", 0)
            head = service.cursor_at("campaign-query", 2)

            self.assertIsNone(genesis.entry_hash)
            self.assertEqual(head.sequence, 2)
            self.assertIsNotNone(head.entry_hash)
            with self.assertRaises(CampaignTimelineQueryCursorError):
                service.cursor_at("campaign-query", 3)
            with self.assertRaises(CampaignValidationError):
                service.cursor_at("campaign-query", -1)
            with self.assertRaises(CampaignValidationError):
                service.page("campaign-query", limit=0)
            with self.assertRaises(CampaignValidationError):
                service.page("campaign-query", limit=1_001)
            with self.assertRaises(TypeError):
                service.page(
                    "campaign-query",
                    after="not-a-cursor",  # type: ignore[arg-type]
                )

    def test_cursor_value_validation_is_strict(self) -> None:
        with self.assertRaises(CampaignValidationError):
            CampaignTimelineQueryCursor(
                campaign_id="campaign-query",
                sequence=0,
                entry_hash="a" * 64,
            )
        with self.assertRaises(CampaignValidationError):
            CampaignTimelineQueryCursor(
                campaign_id="campaign-query",
                sequence=1,
                entry_hash=None,
            )
        with self.assertRaises(CampaignValidationError):
            CampaignTimelineQueryCursor(
                campaign_id="campaign-query",
                sequence=1,
                entry_hash="A" * 64,
            )
        with self.assertRaises(CampaignValidationError):
            CampaignTimelineQueryCursor.from_dict(
                {
                    "schema": "unsupported",
                    "campaign_id": "campaign-query",
                    "sequence": 0,
                    "entry_hash": None,
                }
            )
