"""A4-09 process-local consumer single-flight contract tests."""

from __future__ import annotations

import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Event

from app.agent4.domain import CampaignEvent, CampaignEventKind, CampaignValidationError
from app.agent4.timeline import JsonlCampaignTimelineStore
from app.agent4.timeline_consumer_flights import (
    CampaignTimelineConsumerBusyError,
    CampaignTimelineConsumerFlightConflictError,
    InMemoryCampaignTimelineConsumerSingleFlight,
    SingleFlightCampaignTimelineConsumerService,
)
from app.agent4.timeline_consumers import (
    CampaignTimelineConsumerHandlerError,
    CampaignTimelineConsumerService,
    JsonCampaignTimelineConsumerStore,
)
from app.agent4.timeline_replay import CampaignTimelineReplayService


BASE_TIME = datetime(2026, 7, 30, 16, 0, tzinfo=timezone.utc)


class Agent4TimelineConsumerFlightTests(unittest.TestCase):
    def service(self, root: str):
        timeline = JsonlCampaignTimelineStore(Path(root) / "timeline")
        for sequence in (1, 2, 3):
            timeline.append_event(
                CampaignEvent(
                    event_id=f"campaign-flight:{sequence}",
                    campaign_id="campaign-flight",
                    kind=(
                        CampaignEventKind.STARTED
                        if sequence == 1
                        else CampaignEventKind.CHECKPOINTED
                    ),
                    sequence=sequence,
                    occurred_at=BASE_TIME + timedelta(seconds=sequence),
                    payload={"sequence": sequence},
                )
            )
        offsets = JsonCampaignTimelineConsumerStore(Path(root) / "offsets")
        consumer = CampaignTimelineConsumerService(
            CampaignTimelineReplayService(timeline), offsets
        )
        flights = InMemoryCampaignTimelineConsumerSingleFlight()
        return (
            SingleFlightCampaignTimelineConsumerService(consumer, flights),
            flights,
            offsets,
        )

    def test_construction_is_dormant_and_snapshot_is_empty(self) -> None:
        flights = InMemoryCampaignTimelineConsumerSingleFlight()
        self.assertEqual(flights.snapshot(), ())
        self.assertFalse(flights.is_active("campaign-flight", "indexer"))

    def test_same_consumer_overlap_is_rejected_without_second_handler(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            service, flights, _ = self.service(root)
            entered = Event()
            release = Event()
            second_calls: list[int] = []

            def blocking(entry) -> None:
                entered.set()
                self.assertTrue(release.wait(timeout=10))

            with ThreadPoolExecutor(max_workers=2) as executor:
                first = executor.submit(
                    service.consume_batch,
                    "campaign-flight",
                    "indexer",
                    blocking,
                    updated_at=BASE_TIME,
                    max_entries=1,
                )
                self.assertTrue(entered.wait(timeout=10))
                self.assertTrue(flights.is_active("campaign-flight", "indexer"))
                with self.assertRaises(CampaignTimelineConsumerBusyError):
                    service.consume_batch(
                        "campaign-flight",
                        "indexer",
                        lambda entry: second_calls.append(entry.timeline_sequence),
                        updated_at=BASE_TIME,
                    )
                release.set()
                self.assertEqual(first.result(timeout=10).accepted_count, 1)

            self.assertEqual(second_calls, [])
            self.assertFalse(flights.is_active("campaign-flight", "indexer"))

    def test_different_consumers_can_run_concurrently(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            service, flights, _ = self.service(root)
            both_entered = Event()
            release = Event()
            entered: list[str] = []

            def handler(name: str):
                def consume(_entry) -> None:
                    entered.append(name)
                    if len(entered) == 2:
                        both_entered.set()
                    self.assertTrue(release.wait(timeout=10))
                return consume

            with ThreadPoolExecutor(max_workers=2) as executor:
                one = executor.submit(
                    service.consume_batch,
                    "campaign-flight",
                    "indexer",
                    handler("indexer"),
                    updated_at=BASE_TIME,
                    max_entries=1,
                )
                two = executor.submit(
                    service.consume_batch,
                    "campaign-flight",
                    "auditor",
                    handler("auditor"),
                    updated_at=BASE_TIME,
                    max_entries=1,
                )
                self.assertTrue(both_entered.wait(timeout=10))
                self.assertEqual(len(flights.snapshot()), 2)
                release.set()
                one.result(timeout=10)
                two.result(timeout=10)

            self.assertEqual(set(entered), {"indexer", "auditor"})
            self.assertEqual(flights.snapshot(), ())

    def test_handler_failure_releases_flight_and_retry_can_continue(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            service, flights, offsets = self.service(root)
            with self.assertRaises(CampaignTimelineConsumerHandlerError):
                service.consume_batch(
                    "campaign-flight",
                    "indexer",
                    lambda _entry: (_ for _ in ()).throw(RuntimeError("failed")),
                    updated_at=BASE_TIME,
                )
            self.assertFalse(flights.is_active("campaign-flight", "indexer"))
            self.assertIsNone(offsets.get("campaign-flight", "indexer"))

            observed: list[int] = []
            result = service.consume_batch(
                "campaign-flight",
                "indexer",
                lambda entry: observed.append(entry.timeline_sequence),
                updated_at=BASE_TIME + timedelta(seconds=1),
            )
            self.assertEqual(observed, [1, 2, 3])
            self.assertTrue(result.completed)

    def test_sequential_calls_resume_through_same_guard(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            service, flights, _ = self.service(root)
            observed: list[int] = []
            service.consume_batch(
                "campaign-flight",
                "indexer",
                lambda entry: observed.append(entry.timeline_sequence),
                updated_at=BASE_TIME,
                max_entries=2,
            )
            service.consume_batch(
                "campaign-flight",
                "indexer",
                lambda entry: observed.append(entry.timeline_sequence),
                updated_at=BASE_TIME + timedelta(seconds=1),
            )
            self.assertEqual(observed, [1, 2, 3])
            self.assertEqual(flights.snapshot(), ())

    def test_stale_release_and_invalid_inputs_fail_closed(self) -> None:
        flights = InMemoryCampaignTimelineConsumerSingleFlight()
        flight = flights.acquire("campaign-flight", "indexer")
        flights.release(flight)
        with self.assertRaises(CampaignTimelineConsumerFlightConflictError):
            flights.release(flight)
        with self.assertRaises(CampaignValidationError):
            flights.acquire("", "indexer")
        with self.assertRaises(TypeError):
            flights.run("campaign-flight", "indexer", None)  # type: ignore[arg-type]
        self.assertEqual(flights.snapshot(), ())


__all__ = ["Agent4TimelineConsumerFlightTests"]
