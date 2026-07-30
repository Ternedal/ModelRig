#!/usr/bin/env python3
"""A4-07 verified timeline cursor, paging and replay contract tests."""

from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta, timezone

from app.agent4.domain import CampaignEvent, CampaignEventKind, CampaignValidationError
from app.agent4.timeline import CampaignEvidence, GENESIS_HASH, JsonlCampaignTimelineStore
from app.agent4.timeline_replay import (
    MAX_TIMELINE_PAGE_SIZE,
    CampaignTimelineCursor,
    CampaignTimelineCursorError,
    CampaignTimelineReplayHandlerError,
    CampaignTimelineReplayService,
)


BASE_TIME = datetime(2026, 7, 30, 14, 0, tzinfo=timezone.utc)


class Agent4TimelineReplayTests(unittest.TestCase):
    def event(self, sequence: int, campaign_id: str = "campaign-replay") -> CampaignEvent:
        return CampaignEvent(
            event_id=f"{campaign_id}:{sequence}",
            campaign_id=campaign_id,
            kind=(
                CampaignEventKind.STARTED
                if sequence == 1
                else CampaignEventKind.CHECKPOINTED
            ),
            sequence=sequence,
            occurred_at=BASE_TIME + timedelta(seconds=sequence),
            payload={"sequence": sequence},
        )

    def evidence(self, evidence_id: str, offset: int = 30) -> CampaignEvidence:
        return CampaignEvidence(
            evidence_id=evidence_id,
            campaign_id="campaign-replay",
            category="operator-proof",
            source="test",
            recorded_at=BASE_TIME + timedelta(seconds=offset),
            payload={"accepted": True, "id": evidence_id},
        )

    def populated(self, directory: str):
        store = JsonlCampaignTimelineStore(directory)
        store.append_event(self.event(1))
        store.append_evidence(self.evidence("proof-1"))
        store.append_event(self.event(2))
        return store, CampaignTimelineReplayService(store)

    def test_construction_is_dormant_and_empty_page_is_genesis(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = JsonlCampaignTimelineStore(directory)
            service = CampaignTimelineReplayService(store)
            page = service.page("campaign-replay")
            self.assertEqual(page.entries, ())
            self.assertEqual(page.start_cursor.timeline_sequence, 0)
            self.assertEqual(page.next_cursor.content_hash, GENESIS_HASH)
            self.assertEqual(page.head_cursor, page.next_cursor)
            self.assertFalse(page.has_more)

    def test_page_cursor_remains_valid_after_clean_append(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store, service = self.populated(directory)
            first = service.page("campaign-replay", limit=2)
            self.assertEqual(
                [entry.timeline_sequence for entry in first.entries], [1, 2]
            )
            self.assertTrue(first.has_more)

            store.append_evidence(self.evidence("proof-2", offset=40))
            resumed = service.page(
                "campaign-replay", after=first.next_cursor, limit=10
            )
            self.assertEqual(
                [entry.timeline_sequence for entry in resumed.entries], [3, 4]
            )
            self.assertFalse(resumed.has_more)

    def test_cursor_rejects_wrong_campaign_future_and_hash_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            _, service = self.populated(directory)
            with self.assertRaises(CampaignTimelineCursorError):
                service.page(
                    "campaign-replay",
                    after=CampaignTimelineCursor("other", 0, GENESIS_HASH),
                )
            with self.assertRaises(CampaignTimelineCursorError):
                service.cursor_at("campaign-replay", 4)
            with self.assertRaises(CampaignTimelineCursorError):
                service.page(
                    "campaign-replay",
                    after=CampaignTimelineCursor("campaign-replay", 1, "f" * 64),
                )

    def test_cursor_at_binds_the_exact_verified_entry(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store, service = self.populated(directory)
            cursor = service.cursor_at("campaign-replay", 2)
            history = store.history("campaign-replay")
            self.assertEqual(cursor.timeline_sequence, 2)
            self.assertEqual(cursor.content_hash, history[1].content_hash)
            self.assertEqual(service.cursor_at("campaign-replay", 0).content_hash, GENESIS_HASH)

    def test_replay_preserves_interleaved_order_and_completes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            _, service = self.populated(directory)
            observed: list[tuple[str, int]] = []
            result = service.replay(
                "campaign-replay",
                lambda entry: observed.append(
                    (entry.entry_type.value, entry.timeline_sequence)
                ),
            )
            self.assertEqual(observed, [("event", 1), ("evidence", 2), ("event", 3)])
            self.assertEqual(result.replayed_count, 3)
            self.assertTrue(result.completed)
            self.assertEqual(result.last_cursor, result.head_cursor)

    def test_bounded_replay_resumes_without_duplicates(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            _, service = self.populated(directory)
            observed: list[int] = []
            first = service.replay(
                "campaign-replay",
                lambda entry: observed.append(entry.timeline_sequence),
                max_entries=2,
            )
            self.assertEqual(observed, [1, 2])
            self.assertFalse(first.completed)

            second = service.replay(
                "campaign-replay",
                lambda entry: observed.append(entry.timeline_sequence),
                after=first.last_cursor,
            )
            self.assertEqual(observed, [1, 2, 3])
            self.assertTrue(second.completed)

    def test_handler_failure_exposes_safe_resume_cursor(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            _, service = self.populated(directory)
            observed: list[int] = []

            def fail_on_evidence(entry) -> None:
                if entry.timeline_sequence == 2:
                    raise RuntimeError("consumer failed")
                observed.append(entry.timeline_sequence)

            with self.assertRaises(CampaignTimelineReplayHandlerError) as raised:
                service.replay("campaign-replay", fail_on_evidence)

            error = raised.exception
            self.assertEqual(observed, [1])
            self.assertEqual(error.failed_entry.timeline_sequence, 2)
            self.assertEqual(error.last_successful_cursor.timeline_sequence, 1)
            replayed: list[int] = []
            service.replay(
                "campaign-replay",
                lambda entry: replayed.append(entry.timeline_sequence),
                after=error.last_successful_cursor,
            )
            self.assertEqual(replayed, [2, 3])

    def test_invalid_limits_and_handlers_fail_without_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store, service = self.populated(directory)
            before = store.history("campaign-replay")
            for invalid in (0, -1, True, MAX_TIMELINE_PAGE_SIZE + 1):
                with self.assertRaises(CampaignValidationError):
                    service.page("campaign-replay", limit=invalid)
            with self.assertRaises(TypeError):
                service.replay("campaign-replay", None)  # type: ignore[arg-type]
            self.assertEqual(store.history("campaign-replay"), before)

    def test_replay_head_is_a_stable_snapshot_when_handler_appends(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store, service = self.populated(directory)
            appended = False

            def handler(entry) -> None:
                nonlocal appended
                if not appended:
                    appended = True
                    store.append_evidence(self.evidence("late-proof", offset=50))

            result = service.replay("campaign-replay", handler)
            self.assertTrue(result.completed)
            self.assertEqual(result.head_cursor.timeline_sequence, 3)
            later = service.page("campaign-replay", after=result.last_cursor)
            self.assertEqual([entry.timeline_sequence for entry in later.entries], [4])


if __name__ == "__main__":
    unittest.main()
