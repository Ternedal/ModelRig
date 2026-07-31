"""A4-06 durable delivery cursor contract cases."""

from __future__ import annotations

import json
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from pathlib import Path

from app.agent4 import (
    CampaignEventKind,
    CampaignTimelineCursor,
    CampaignTimelineCursorStore,
    CampaignTimelineDeliveryService,
    CampaignValidationError,
    JsonCampaignTimelineCursorStore,
    JsonCampaignTimelineStore,
    TimelineCampaignEventRecorder,
    TimelineCursorConflictError,
    TimelineCursorStoreError,
    TimelineDeliveryIntegrityError,
)

from agent4_timeline_cases import BASE_TIME


class Agent4TimelineDeliveryTests(unittest.TestCase):
    def _timeline(
        self,
        root: Path,
        *,
        campaign_id: str = "campaign-delivery",
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

    def test_cursor_store_round_trips_and_enforces_compare_and_swap(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = JsonCampaignTimelineCursorStore(Path(directory))
            self.assertIsInstance(store, CampaignTimelineCursorStore)
            first = CampaignTimelineCursor(
                consumer_id="consumer-a",
                campaign_id="campaign-a",
                sequence=1,
                entry_hash="a" * 64,
                updated_at=BASE_TIME,
            )
            second = CampaignTimelineCursor(
                consumer_id="consumer-a",
                campaign_id="campaign-a",
                sequence=2,
                entry_hash="b" * 64,
                updated_at=BASE_TIME + timedelta(seconds=1),
            )
            store.save(first, expected_sequence=None)
            self.assertEqual(store.get("consumer-a", "campaign-a"), first)
            store.save(second, expected_sequence=1)
            self.assertEqual(store.get("consumer-a", "campaign-a"), second)
            with self.assertRaises(TimelineCursorConflictError):
                store.save(second, expected_sequence=1)
            with self.assertRaises(TimelineCursorConflictError):
                store.save(
                    CampaignTimelineCursor(
                        consumer_id="consumer-a",
                        campaign_id="campaign-a",
                        sequence=4,
                        entry_hash="c" * 64,
                        updated_at=BASE_TIME + timedelta(seconds=2),
                    ),
                    expected_sequence=2,
                )

    def test_delivery_is_ordered_restart_safe_and_reports_pending(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            timeline = self._timeline(root)
            cursors = JsonCampaignTimelineCursorStore(root / "cursors")
            delivered: list[int] = []
            service = CampaignTimelineDeliveryService(
                timeline=timeline,
                cursors=cursors,
            )
            self.assertEqual(
                service.pending_count("consumer-a", "campaign-delivery"),
                3,
            )
            first = service.deliver_next(
                "consumer-a",
                "campaign-delivery",
                lambda entry: delivered.append(entry.event.sequence),
                acknowledged_at=BASE_TIME + timedelta(minutes=1),
            )
            self.assertTrue(first.delivered)
            self.assertEqual(first.remaining, 2)

            restarted = CampaignTimelineDeliveryService(
                timeline=timeline,
                cursors=JsonCampaignTimelineCursorStore(root / "cursors"),
            )
            second = restarted.deliver_next(
                "consumer-a",
                "campaign-delivery",
                lambda entry: delivered.append(entry.event.sequence),
                acknowledged_at=BASE_TIME + timedelta(minutes=2),
            )
            third = restarted.deliver_next(
                "consumer-a",
                "campaign-delivery",
                lambda entry: delivered.append(entry.event.sequence),
                acknowledged_at=BASE_TIME + timedelta(minutes=3),
            )
            empty = restarted.deliver_next(
                "consumer-a",
                "campaign-delivery",
                lambda entry: delivered.append(entry.event.sequence),
                acknowledged_at=BASE_TIME + timedelta(minutes=4),
            )

            self.assertEqual(delivered, [1, 2, 3])
            self.assertEqual(second.cursor.sequence, 2)
            self.assertEqual(third.remaining, 0)
            self.assertFalse(empty.delivered)
            self.assertEqual(empty.cursor.sequence, 3)
            self.assertEqual(
                restarted.pending_count("consumer-a", "campaign-delivery"),
                0,
            )

    def test_handler_failure_does_not_advance_cursor(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            timeline = self._timeline(root, count=1)
            cursors = JsonCampaignTimelineCursorStore(root / "cursors")
            service = CampaignTimelineDeliveryService(
                timeline=timeline,
                cursors=cursors,
            )

            def fail(_entry) -> None:
                raise RuntimeError("consumer failed")

            with self.assertRaisesRegex(RuntimeError, "consumer failed"):
                service.deliver_next(
                    "consumer-a",
                    "campaign-delivery",
                    fail,
                    acknowledged_at=BASE_TIME,
                )
            self.assertIsNone(cursors.get("consumer-a", "campaign-delivery"))

            delivered: list[int] = []
            service.deliver_next(
                "consumer-a",
                "campaign-delivery",
                lambda entry: delivered.append(entry.event.sequence),
                acknowledged_at=BASE_TIME + timedelta(seconds=1),
            )
            self.assertEqual(delivered, [1])

    def test_cursor_save_failure_causes_safe_redelivery(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            timeline = self._timeline(root, count=1)
            durable = JsonCampaignTimelineCursorStore(root / "cursors")

            class FailingCursorStore:
                def __init__(self) -> None:
                    self.failed = False

                def get(self, consumer_id: str, campaign_id: str):
                    return durable.get(consumer_id, campaign_id)

                def save(self, cursor, *, expected_sequence):
                    if not self.failed:
                        self.failed = True
                        raise TimelineCursorStoreError("injected cursor failure")
                    durable.save(cursor, expected_sequence=expected_sequence)

            failing = FailingCursorStore()
            service = CampaignTimelineDeliveryService(
                timeline=timeline,
                cursors=failing,
            )
            delivered: list[int] = []
            with self.assertRaises(TimelineCursorStoreError):
                service.deliver_next(
                    "consumer-a",
                    "campaign-delivery",
                    lambda entry: delivered.append(entry.event.sequence),
                    acknowledged_at=BASE_TIME,
                )
            self.assertEqual(delivered, [1])
            self.assertIsNone(durable.get("consumer-a", "campaign-delivery"))

            service.deliver_next(
                "consumer-a",
                "campaign-delivery",
                lambda entry: delivered.append(entry.event.sequence),
                acknowledged_at=BASE_TIME + timedelta(seconds=1),
            )
            self.assertEqual(delivered, [1, 1])
            self.assertEqual(
                durable.get("consumer-a", "campaign-delivery").sequence,
                1,
            )

    def test_cursor_tampering_and_timeline_anchor_mismatch_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            timeline = self._timeline(root, count=1)
            cursors = JsonCampaignTimelineCursorStore(root / "cursors")
            entry = timeline.latest("campaign-delivery")
            cursors.save(
                CampaignTimelineCursor(
                    consumer_id="consumer-a",
                    campaign_id="campaign-delivery",
                    sequence=1,
                    entry_hash="f" * 64,
                    updated_at=BASE_TIME,
                ),
                expected_sequence=None,
            )
            service = CampaignTimelineDeliveryService(
                timeline=timeline,
                cursors=cursors,
            )
            self.assertIsNotNone(entry)
            with self.assertRaises(TimelineDeliveryIntegrityError):
                service.pending_count("consumer-a", "campaign-delivery")

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store = JsonCampaignTimelineCursorStore(root)
            store.save(
                CampaignTimelineCursor(
                    consumer_id="consumer-a",
                    campaign_id="campaign-a",
                    sequence=1,
                    entry_hash="a" * 64,
                    updated_at=BASE_TIME,
                ),
                expected_sequence=None,
            )
            path = next(root.glob("*.timeline-cursor.json"))
            payload = json.loads(path.read_text(encoding="utf-8"))
            payload["sequence"] = 2
            path.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaises(TimelineCursorStoreError):
                store.get("consumer-a", "campaign-a")

    def test_single_service_serializes_concurrent_delivery(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            timeline = self._timeline(root, count=16)
            cursors = JsonCampaignTimelineCursorStore(root / "cursors")
            service = CampaignTimelineDeliveryService(
                timeline=timeline,
                cursors=cursors,
            )
            observed: list[int] = []

            def deliver(index: int):
                return service.deliver_next(
                    "consumer-a",
                    "campaign-delivery",
                    lambda entry: observed.append(entry.event.sequence),
                    acknowledged_at=BASE_TIME + timedelta(seconds=index),
                )

            with ThreadPoolExecutor(max_workers=8) as pool:
                results = list(pool.map(deliver, range(16)))

            self.assertTrue(all(result.delivered for result in results))
            self.assertEqual(sorted(observed), list(range(1, 17)))
            self.assertEqual(
                cursors.get("consumer-a", "campaign-delivery").sequence,
                16,
            )
            self.assertEqual(
                service.pending_count("consumer-a", "campaign-delivery"),
                0,
            )

    def test_empty_delivery_and_invalid_inputs_are_explicit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            service = CampaignTimelineDeliveryService(
                timeline=JsonCampaignTimelineStore(root / "timeline"),
                cursors=JsonCampaignTimelineCursorStore(root / "cursors"),
            )
            result = service.deliver_next(
                "consumer-a",
                "missing",
                lambda _entry: None,
                acknowledged_at=BASE_TIME,
            )
            self.assertFalse(result.delivered)
            self.assertIsNone(result.cursor)
            with self.assertRaises(TypeError):
                service.deliver_next(
                    "consumer-a",
                    "missing",
                    None,  # type: ignore[arg-type]
                    acknowledged_at=BASE_TIME,
                )
            with self.assertRaises(CampaignValidationError):
                service.deliver_next(
                    "consumer-a",
                    "missing",
                    lambda _entry: None,
                    acknowledged_at=BASE_TIME.replace(tzinfo=None),
                )
