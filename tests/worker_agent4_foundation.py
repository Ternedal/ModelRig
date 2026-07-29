#!/usr/bin/env python3
"""Unit coverage for the dormant Agent 4 campaign foundation."""

from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.agent4 import (
    CampaignEvent,
    CampaignEventKind,
    CampaignEventOrderError,
    CampaignPriority,
    CampaignQueue,
    CampaignRecord,
    CampaignRepositoryError,
    CampaignSpec,
    CampaignState,
    CampaignStatus,
    CampaignTransitionError,
    CampaignValidationError,
    DuplicateCampaignError,
    InMemoryCampaignEventBus,
    JsonCampaignRepository,
    transition_campaign,
)


UTC = timezone.utc
BASE_TIME = datetime(2026, 7, 29, 12, 0, tzinfo=UTC)


def _spec(
    campaign_id: str,
    *,
    priority: CampaignPriority = CampaignPriority.NORMAL,
    ready_offset: int = 0,
) -> CampaignSpec:
    return CampaignSpec(
        campaign_id=campaign_id,
        name=f"Campaign {campaign_id}",
        workflow="agent3.write-pilot",
        created_at=BASE_TIME,
        scheduled_for=BASE_TIME + timedelta(seconds=ready_offset),
        priority=priority,
        max_attempts=3,
        parameters={"targets": ["desktop", "android"], "dry_run": True},
        metadata={"owner": "operator"},
    )


class CampaignDomainTests(unittest.TestCase):
    def test_spec_is_normalized_immutable_and_round_trips(self) -> None:
        parameters = {"nested": {"items": [1, 2]}}
        spec = CampaignSpec(
            campaign_id=" campaign-1 ",
            name=" Pilot ",
            workflow=" agent3.write-pilot ",
            created_at=BASE_TIME,
            parameters=parameters,
        )
        parameters["nested"]["items"].append(3)

        self.assertEqual(spec.campaign_id, "campaign-1")
        self.assertEqual(spec.name, "Pilot")
        self.assertEqual(spec.parameters["nested"]["items"], (1, 2))
        with self.assertRaises(TypeError):
            spec.parameters["new"] = "blocked"  # type: ignore[index]
        self.assertEqual(CampaignSpec.from_dict(spec.to_dict()), spec)

    def test_invalid_timestamps_and_payloads_fail_closed(self) -> None:
        with self.assertRaises(CampaignValidationError):
            CampaignSpec(
                campaign_id="campaign-1",
                name="Pilot",
                workflow="workflow",
                created_at=datetime(2026, 7, 29, 12, 0),
            )
        with self.assertRaises(CampaignValidationError):
            CampaignSpec(
                campaign_id="campaign-1",
                name="Pilot",
                workflow="workflow",
                created_at=BASE_TIME,
                parameters={"bad": object()},
            )
        with self.assertRaises(CampaignValidationError):
            CampaignSpec(
                campaign_id="campaign-1",
                name="Pilot",
                workflow="workflow",
                created_at=BASE_TIME,
                parameters={"bad": float("inf")},
            )

    def test_transition_increments_revision_and_attempt(self) -> None:
        queued = CampaignState(campaign_id="campaign-1", updated_at=BASE_TIME)
        running = transition_campaign(
            queued,
            CampaignStatus.RUNNING,
            occurred_at=BASE_TIME + timedelta(seconds=1),
        )
        succeeded = transition_campaign(
            running,
            CampaignStatus.SUCCEEDED,
            occurred_at=BASE_TIME + timedelta(seconds=2),
        )

        self.assertEqual(running.revision, 1)
        self.assertEqual(running.attempt, 1)
        self.assertEqual(succeeded.revision, 2)
        self.assertEqual(succeeded.attempt, 1)
        self.assertTrue(succeeded.status.terminal)

    def test_illegal_and_incomplete_failure_transitions_are_rejected(self) -> None:
        queued = CampaignState(campaign_id="campaign-1", updated_at=BASE_TIME)
        with self.assertRaises(CampaignTransitionError):
            transition_campaign(queued, CampaignStatus.SUCCEEDED)
        running = transition_campaign(queued, CampaignStatus.RUNNING)
        with self.assertRaises(CampaignTransitionError):
            transition_campaign(running, CampaignStatus.FAILED)
        failed = transition_campaign(
            running,
            CampaignStatus.FAILED,
            error="executor stopped",
        )
        self.assertEqual(failed.last_error, "executor stopped")

    def test_record_requires_matching_identity_and_round_trips(self) -> None:
        spec = _spec("campaign-1")
        state = CampaignState(campaign_id="campaign-1", updated_at=BASE_TIME)
        record = CampaignRecord(spec=spec, state=state)
        self.assertEqual(CampaignRecord.from_dict(record.to_dict()), record)
        with self.assertRaises(CampaignValidationError):
            CampaignRecord(
                spec=spec,
                state=CampaignState(campaign_id="campaign-2", updated_at=BASE_TIME),
            )


class CampaignQueueTests(unittest.TestCase):
    def test_ready_campaigns_use_priority_then_time_then_insertion(self) -> None:
        queue = CampaignQueue()
        queue.enqueue(_spec("normal-early", ready_offset=-10))
        queue.enqueue(
            _spec(
                "critical-late",
                priority=CampaignPriority.CRITICAL,
                ready_offset=-1,
            )
        )
        queue.enqueue(
            _spec(
                "critical-first",
                priority=CampaignPriority.CRITICAL,
                ready_offset=-5,
            )
        )

        self.assertEqual(queue.pop_ready(BASE_TIME).campaign_id, "critical-first")
        self.assertEqual(queue.pop_ready(BASE_TIME).campaign_id, "critical-late")
        self.assertEqual(queue.pop_ready(BASE_TIME).campaign_id, "normal-early")
        self.assertIsNone(queue.pop_ready(BASE_TIME))

    def test_future_campaign_does_not_block_ready_campaign(self) -> None:
        queue = CampaignQueue()
        queue.enqueue(
            _spec(
                "future-critical",
                priority=CampaignPriority.CRITICAL,
                ready_offset=60,
            )
        )
        queue.enqueue(_spec("ready-normal", ready_offset=0))

        self.assertEqual(queue.pop_ready(BASE_TIME).campaign_id, "ready-normal")
        self.assertIsNone(queue.pop_ready(BASE_TIME))
        self.assertEqual(
            queue.pop_ready(BASE_TIME + timedelta(seconds=60)).campaign_id,
            "future-critical",
        )

    def test_duplicate_remove_and_naive_clock_contract(self) -> None:
        queue = CampaignQueue()
        spec = _spec("campaign-1")
        queue.enqueue(spec)
        with self.assertRaises(DuplicateCampaignError):
            queue.enqueue(spec)
        with self.assertRaises(CampaignValidationError):
            queue.peek_ready(datetime(2026, 7, 29, 12, 0))
        self.assertEqual(queue.remove("campaign-1"), spec)
        self.assertIsNone(queue.remove("campaign-1"))


class CampaignRepositoryTests(unittest.TestCase):
    def test_repository_atomically_round_trips_and_lists_records(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository = JsonCampaignRepository(Path(directory))
            later = CampaignRecord(
                spec=_spec("later"),
                state=CampaignState(campaign_id="later", updated_at=BASE_TIME),
            )
            earlier_spec = CampaignSpec(
                campaign_id="earlier",
                name="Earlier",
                workflow="agent3.write-pilot",
                created_at=BASE_TIME - timedelta(seconds=1),
            )
            earlier = CampaignRecord(
                spec=earlier_spec,
                state=CampaignState(campaign_id="earlier", updated_at=BASE_TIME),
            )

            repository.save(later)
            repository.save(earlier)

            self.assertEqual(repository.get("later"), later)
            self.assertEqual(
                [record.spec.campaign_id for record in repository.list()],
                ["earlier", "later"],
            )
            self.assertFalse(any(Path(directory).glob("*.tmp")))
            self.assertTrue(repository.delete("later"))
            self.assertFalse(repository.delete("later"))
            self.assertIsNone(repository.get("later"))

    def test_repository_rejects_corrupt_or_rebound_data(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository = JsonCampaignRepository(Path(directory))
            record = CampaignRecord(
                spec=_spec("campaign-1"),
                state=CampaignState(campaign_id="campaign-1", updated_at=BASE_TIME),
            )
            repository.save(record)
            path = next(Path(directory).glob("*.campaign.json"))
            payload = json.loads(path.read_text(encoding="utf-8"))
            payload["state"]["campaign_id"] = "campaign-2"
            path.write_text(json.dumps(payload), encoding="utf-8")

            with self.assertRaises(CampaignRepositoryError):
                repository.get("campaign-1")


class CampaignEventBusTests(unittest.TestCase):
    def test_bus_records_ordered_events_and_unsubscribes_idempotently(self) -> None:
        bus = InMemoryCampaignEventBus()
        observed: list[str] = []
        unsubscribe = bus.subscribe(lambda event: observed.append(event.event_id))

        first = CampaignEvent(
            event_id="event-1",
            campaign_id="campaign-1",
            kind=CampaignEventKind.CREATED,
            sequence=1,
            occurred_at=BASE_TIME,
        )
        second = CampaignEvent(
            event_id="event-2",
            campaign_id="campaign-1",
            kind=CampaignEventKind.STARTED,
            sequence=2,
            occurred_at=BASE_TIME,
        )
        bus.publish(first)
        unsubscribe()
        unsubscribe()
        bus.publish(second)

        self.assertEqual(observed, ["event-1"])
        self.assertEqual(bus.history("campaign-1"), (first, second))
        self.assertEqual(bus.latest_sequence("campaign-1"), 2)

    def test_bus_rejects_gaps_and_duplicate_event_ids(self) -> None:
        bus = InMemoryCampaignEventBus()
        first = CampaignEvent(
            event_id="event-1",
            campaign_id="campaign-1",
            kind=CampaignEventKind.CREATED,
            sequence=1,
            occurred_at=BASE_TIME,
        )
        bus.publish(first)
        with self.assertRaises(CampaignEventOrderError):
            bus.publish(first)
        with self.assertRaises(CampaignEventOrderError):
            bus.publish(
                CampaignEvent(
                    event_id="event-3",
                    campaign_id="campaign-1",
                    kind=CampaignEventKind.STARTED,
                    sequence=3,
                    occurred_at=BASE_TIME,
                )
            )


if __name__ == "__main__":
    unittest.main()
