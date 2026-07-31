"""A4-08 bounded durable timeline batch contract cases."""

from __future__ import annotations

import tempfile
import threading
import unittest
from pathlib import Path

from app.agent4 import (
    CampaignEventKind,
    CampaignTimelineBatchDeliveryService,
    CampaignTimelineDeliveryBusyError,
    CampaignTimelineDeliveryService,
    CampaignValidationError,
    InMemoryCampaignTimelineDeliverySingleFlight,
    JsonCampaignTimelineCursorStore,
    JsonCampaignTimelineStore,
    TimelineCampaignEventRecorder,
)

from agent4_timeline_cases import BASE_TIME


class Agent4TimelineBatchDeliveryTests(unittest.TestCase):
    def _service(
        self,
        root: Path,
        *,
        campaign_id: str = "campaign-batch",
        count: int = 3,
    ) -> tuple[
        CampaignTimelineBatchDeliveryService,
        JsonCampaignTimelineCursorStore,
    ]:
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
                occurred_at=BASE_TIME,
                payload={"index": index},
            )
        cursors = JsonCampaignTimelineCursorStore(root / "cursors")
        delivery = CampaignTimelineDeliveryService(
            timeline=timeline,
            cursors=cursors,
        )
        return (
            CampaignTimelineBatchDeliveryService(
                delivery,
                InMemoryCampaignTimelineDeliverySingleFlight(),
            ),
            cursors,
        )

    def test_bounded_batch_resumes_from_the_durable_cursor(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            service, cursors = self._service(Path(directory), count=3)
            seen: list[int] = []

            first = service.deliver_batch(
                "consumer-a",
                "campaign-batch",
                lambda entry: seen.append(entry.event.sequence),
                acknowledged_at=BASE_TIME,
                max_entries=2,
            )
            self.assertEqual(seen, [1, 2])
            self.assertEqual(first.delivered_count, 2)
            self.assertEqual(first.cursor.sequence, 2)
            self.assertEqual(first.remaining, 1)
            self.assertFalse(first.completed)
            self.assertEqual(
                cursors.get("consumer-a", "campaign-batch").sequence,
                2,
            )

            second = service.deliver_batch(
                "consumer-a",
                "campaign-batch",
                lambda entry: seen.append(entry.event.sequence),
                acknowledged_at=BASE_TIME,
                max_entries=2,
            )
            self.assertEqual(seen, [1, 2, 3])
            self.assertEqual(second.delivered_count, 1)
            self.assertEqual(second.cursor.sequence, 3)
            self.assertEqual(second.remaining, 0)
            self.assertTrue(second.completed)

    def test_handler_failure_keeps_only_prior_entries_acknowledged(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            service, cursors = self._service(Path(directory), count=3)
            attempted: list[int] = []

            def fail_on_second(entry) -> None:
                attempted.append(entry.event.sequence)
                if entry.event.sequence == 2:
                    raise RuntimeError("reject sequence two")

            with self.assertRaisesRegex(RuntimeError, "reject sequence two"):
                service.deliver_batch(
                    "consumer-a",
                    "campaign-batch",
                    fail_on_second,
                    acknowledged_at=BASE_TIME,
                    max_entries=3,
                )

            self.assertEqual(attempted, [1, 2])
            self.assertEqual(
                cursors.get("consumer-a", "campaign-batch").sequence,
                1,
            )

            replayed: list[int] = []
            resumed = service.deliver_batch(
                "consumer-a",
                "campaign-batch",
                lambda entry: replayed.append(entry.event.sequence),
                acknowledged_at=BASE_TIME,
                max_entries=3,
            )
            self.assertEqual(replayed, [2, 3])
            self.assertEqual(resumed.cursor.sequence, 3)
            self.assertTrue(resumed.completed)

    def test_consumers_keep_independent_durable_progress(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            service, cursors = self._service(Path(directory), count=2)

            service.deliver_batch(
                "consumer-a",
                "campaign-batch",
                lambda entry: None,
                acknowledged_at=BASE_TIME,
                max_entries=1,
            )
            service.deliver_batch(
                "consumer-b",
                "campaign-batch",
                lambda entry: None,
                acknowledged_at=BASE_TIME,
                max_entries=2,
            )

            self.assertEqual(
                cursors.get("consumer-a", "campaign-batch").sequence,
                1,
            )
            self.assertEqual(
                cursors.get("consumer-b", "campaign-batch").sequence,
                2,
            )

    def test_one_flight_covers_the_whole_batch_and_releases_afterward(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            service, _ = self._service(Path(directory), count=1)
            entered = threading.Event()
            release = threading.Event()
            failures: list[BaseException] = []

            def blocking_handler(entry) -> None:
                entered.set()
                if not release.wait(timeout=5):
                    raise AssertionError("test did not release the blocking handler")

            def run_first() -> None:
                try:
                    service.deliver_batch(
                        "consumer-a",
                        "campaign-batch",
                        blocking_handler,
                        acknowledged_at=BASE_TIME,
                        max_entries=1,
                    )
                except BaseException as exc:  # pragma: no cover - surfaced below
                    failures.append(exc)

            thread = threading.Thread(target=run_first)
            thread.start()
            self.assertTrue(entered.wait(timeout=5))
            with self.assertRaises(CampaignTimelineDeliveryBusyError):
                service.deliver_batch(
                    "consumer-a",
                    "campaign-batch",
                    lambda entry: None,
                    acknowledged_at=BASE_TIME,
                    max_entries=1,
                )
            release.set()
            thread.join(timeout=5)
            self.assertFalse(thread.is_alive())
            self.assertEqual(failures, [])

            empty = service.deliver_batch(
                "consumer-a",
                "campaign-batch",
                lambda entry: None,
                acknowledged_at=BASE_TIME,
                max_entries=1,
            )
            self.assertEqual(empty.delivered_count, 0)
            self.assertTrue(empty.completed)

    def test_empty_and_invalid_batch_requests_fail_predictably(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            service, _ = self._service(Path(directory), count=0)
            empty = service.deliver_batch(
                "consumer-a",
                "campaign-batch",
                lambda entry: None,
                acknowledged_at=BASE_TIME,
            )
            self.assertEqual(empty.entries, ())
            self.assertIsNone(empty.cursor)
            self.assertEqual(empty.remaining, 0)
            self.assertTrue(empty.completed)

            for value in (0, -1, 1001, True, 1.5):
                with self.subTest(max_entries=value):
                    with self.assertRaises(CampaignValidationError):
                        service.deliver_batch(
                            "consumer-a",
                            "campaign-batch",
                            lambda entry: None,
                            acknowledged_at=BASE_TIME,
                            max_entries=value,
                        )
