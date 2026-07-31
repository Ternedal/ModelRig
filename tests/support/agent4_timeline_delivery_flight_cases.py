"""A4-06 shared process-local delivery single-flight contract cases."""

from __future__ import annotations

import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from pathlib import Path
from threading import Barrier, Event

from app.agent4 import (
    CampaignEventKind,
    CampaignTimelineDeliveryBusyError,
    CampaignTimelineDeliveryFlight,
    CampaignTimelineDeliveryFlightConflictError,
    CampaignTimelineDeliveryService,
    CampaignValidationError,
    InMemoryCampaignTimelineDeliverySingleFlight,
    JsonCampaignTimelineCursorStore,
    JsonCampaignTimelineStore,
    SingleFlightCampaignTimelineDeliveryService,
    TimelineCampaignEventRecorder,
    TimelineCursorStoreError,
)

from agent4_timeline_cases import BASE_TIME


class Agent4TimelineDeliveryFlightTests(unittest.TestCase):
    def _flight_timeline(
        self,
        root: Path,
        *,
        campaign_id: str = "campaign-flight",
        count: int = 2,
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

    def _flight_service(
        self,
        root: Path,
        timeline: JsonCampaignTimelineStore,
        flights: InMemoryCampaignTimelineDeliverySingleFlight,
    ) -> SingleFlightCampaignTimelineDeliveryService:
        delivery = CampaignTimelineDeliveryService(
            timeline=timeline,
            cursors=JsonCampaignTimelineCursorStore(root / "cursors"),
        )
        return SingleFlightCampaignTimelineDeliveryService(delivery, flights)

    def test_shared_guard_rejects_same_key_before_second_handler(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            timeline = self._flight_timeline(root)
            flights = InMemoryCampaignTimelineDeliverySingleFlight()
            first = self._flight_service(root, timeline, flights)
            second = self._flight_service(root, timeline, flights)
            entered = Event()
            release = Event()
            second_handler_calls: list[int] = []

            def blocking_handler(entry) -> None:
                entered.set()
                if not release.wait(timeout=5):
                    raise AssertionError("test did not release the first delivery")

            with ThreadPoolExecutor(max_workers=2) as pool:
                pending = pool.submit(
                    first.deliver_next,
                    "consumer-a",
                    "campaign-flight",
                    blocking_handler,
                    acknowledged_at=BASE_TIME,
                )
                self.assertTrue(entered.wait(timeout=5))
                with self.assertRaises(CampaignTimelineDeliveryBusyError):
                    second.deliver_next(
                        "consumer-a",
                        "campaign-flight",
                        lambda entry: second_handler_calls.append(
                            entry.event.sequence
                        ),
                        acknowledged_at=BASE_TIME + timedelta(seconds=1),
                    )
                release.set()
                result = pending.result(timeout=5)

            self.assertTrue(result.delivered)
            self.assertEqual(result.entry.event.sequence, 1)
            self.assertEqual(second_handler_calls, [])
            self.assertFalse(flights.is_active("consumer-a", "campaign-flight"))

    def test_different_consumers_may_deliver_concurrently(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            timeline = self._flight_timeline(root, count=1)
            flights = InMemoryCampaignTimelineDeliverySingleFlight()
            first = self._flight_service(root, timeline, flights)
            second = self._flight_service(root, timeline, flights)
            barrier = Barrier(2)
            observed: list[str] = []

            def handler(consumer_id: str):
                def accept(_entry) -> None:
                    observed.append(consumer_id)
                    barrier.wait(timeout=5)

                return accept

            with ThreadPoolExecutor(max_workers=2) as pool:
                results = list(
                    pool.map(
                        lambda args: args[0].deliver_next(
                            args[1],
                            "campaign-flight",
                            handler(args[1]),
                            acknowledged_at=BASE_TIME,
                        ),
                        ((first, "consumer-a"), (second, "consumer-b")),
                    )
                )

            self.assertTrue(all(result.delivered for result in results))
            self.assertEqual(sorted(observed), ["consumer-a", "consumer-b"])
            self.assertEqual(flights.snapshot(), ())

    def test_guard_releases_after_handler_failure(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            timeline = self._flight_timeline(root, count=1)
            flights = InMemoryCampaignTimelineDeliverySingleFlight()
            service = self._flight_service(root, timeline, flights)

            def fail(_entry) -> None:
                raise RuntimeError("injected handler failure")

            with self.assertRaisesRegex(RuntimeError, "injected handler failure"):
                service.deliver_next(
                    "consumer-a",
                    "campaign-flight",
                    fail,
                    acknowledged_at=BASE_TIME,
                )
            self.assertFalse(flights.is_active("consumer-a", "campaign-flight"))

            delivered: list[int] = []
            result = service.deliver_next(
                "consumer-a",
                "campaign-flight",
                lambda entry: delivered.append(entry.event.sequence),
                acknowledged_at=BASE_TIME + timedelta(seconds=1),
            )
            self.assertTrue(result.delivered)
            self.assertEqual(delivered, [1])

    def test_guard_releases_after_cursor_failure(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            timeline = self._flight_timeline(root, count=1)
            durable = JsonCampaignTimelineCursorStore(root / "cursors")

            class FailingCursorStore:
                def get(self, consumer_id: str, campaign_id: str):
                    return durable.get(consumer_id, campaign_id)

                def save(self, cursor, *, expected_sequence):
                    raise TimelineCursorStoreError("injected cursor failure")

            flights = InMemoryCampaignTimelineDeliverySingleFlight()
            service = SingleFlightCampaignTimelineDeliveryService(
                CampaignTimelineDeliveryService(
                    timeline=timeline,
                    cursors=FailingCursorStore(),
                ),
                flights,
            )
            with self.assertRaises(TimelineCursorStoreError):
                service.deliver_next(
                    "consumer-a",
                    "campaign-flight",
                    lambda _entry: None,
                    acknowledged_at=BASE_TIME,
                )
            self.assertFalse(flights.is_active("consumer-a", "campaign-flight"))

    def test_tokens_reject_stale_and_foreign_release(self) -> None:
        flights = InMemoryCampaignTimelineDeliverySingleFlight()
        current = flights.acquire("consumer-a", "campaign-a")
        foreign = CampaignTimelineDeliveryFlight(
            consumer_id="consumer-a",
            campaign_id="campaign-a",
            token=current.token + 1,
        )
        with self.assertRaises(CampaignTimelineDeliveryFlightConflictError):
            flights.release(foreign)
        self.assertTrue(flights.is_active("consumer-a", "campaign-a"))
        flights.release(current)
        with self.assertRaises(CampaignTimelineDeliveryFlightConflictError):
            flights.release(current)

    def test_validation_and_wrapper_delegation_are_explicit(self) -> None:
        flights = InMemoryCampaignTimelineDeliverySingleFlight()
        with self.assertRaises(CampaignValidationError):
            flights.acquire("", "campaign-a")
        with self.assertRaises(TypeError):
            flights.run("consumer-a", "campaign-a", None)  # type: ignore[arg-type]

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            timeline = self._flight_timeline(root, count=1)
            service = self._flight_service(root, timeline, flights)
            self.assertEqual(
                service.pending_count("consumer-a", "campaign-flight"),
                1,
            )
