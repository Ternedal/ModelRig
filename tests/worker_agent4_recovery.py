#!/usr/bin/env python3
"""Startup recovery coverage for Agent 4 durable campaigns."""

from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.agent4 import (
    CampaignEventKind,
    CampaignQueue,
    CampaignRecord,
    CampaignRecoveryService,
    CampaignSpec,
    CampaignState,
    CampaignStatus,
    InMemoryCampaignEventBus,
    JsonCampaignRepository,
    RecoveryAction,
)


BASE_TIME = datetime(2026, 7, 29, 18, 0, tzinfo=timezone.utc)


class FixedClock:
    def __init__(self) -> None:
        self.calls = 0

    def now(self) -> datetime:
        self.calls += 1
        return BASE_TIME + timedelta(microseconds=self.calls)


class CampaignRecoveryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.repository = JsonCampaignRepository(Path(self.directory.name))
        self.queue = CampaignQueue()
        self.events = InMemoryCampaignEventBus()
        self.clock = FixedClock()
        self.recovery = CampaignRecoveryService(
            repository=self.repository,
            queue=self.queue,
            events=self.events,
            clock=self.clock,
        )

    def tearDown(self) -> None:
        self.directory.cleanup()

    def save(self, campaign_id: str, status: CampaignStatus) -> CampaignRecord:
        spec = CampaignSpec(
            campaign_id=campaign_id,
            name=campaign_id,
            workflow="agent3.write-pilot",
            created_at=BASE_TIME,
            scheduled_for=(
                BASE_TIME + timedelta(hours=1)
                if status is CampaignStatus.SCHEDULED
                else None
            ),
        )
        state = CampaignState(
            campaign_id=campaign_id,
            status=status,
            updated_at=BASE_TIME,
            attempt=1 if status not in {CampaignStatus.QUEUED, CampaignStatus.SCHEDULED} else 0,
            last_error="previous failure" if status is CampaignStatus.FAILED else None,
        )
        record = CampaignRecord(spec=spec, state=state)
        self.repository.save(record)
        return record

    def test_queued_and_scheduled_campaigns_are_rehydrated(self) -> None:
        self.save("queued", CampaignStatus.QUEUED)
        self.save("scheduled", CampaignStatus.SCHEDULED)

        report = self.recovery.recover()

        self.assertEqual(report.scanned, 2)
        self.assertEqual(report.requeued, 2)
        self.assertEqual(self.queue.snapshot()[0].campaign_id, "queued")
        self.assertIn("scheduled", self.queue)
        self.assertEqual(
            self.events.history("queued")[0].kind,
            CampaignEventKind.RECOVERED,
        )

    def test_recovery_is_queue_idempotent(self) -> None:
        self.save("queued", CampaignStatus.QUEUED)

        first = self.recovery.recover()
        second = self.recovery.recover()

        self.assertEqual(first.requeued, 1)
        self.assertEqual(second.count(RecoveryAction.ALREADY_QUEUED), 1)
        self.assertEqual(len(self.queue), 1)
        self.assertEqual(len(self.events.history("queued")), 1)

    def test_paused_campaign_remains_paused_and_is_not_queued(self) -> None:
        original = self.save("paused", CampaignStatus.PAUSED)

        report = self.recovery.recover()

        self.assertEqual(report.count(RecoveryAction.RETAINED_PAUSED), 1)
        self.assertEqual(self.repository.get("paused"), original)
        self.assertNotIn("paused", self.queue)
        self.assertEqual(
            self.events.history("paused")[0].payload["action"],
            RecoveryAction.RETAINED_PAUSED.value,
        )

    def test_inflight_states_fail_closed_durably(self) -> None:
        for status in (
            CampaignStatus.RUNNING,
            CampaignStatus.PAUSING,
            CampaignStatus.CANCELLING,
        ):
            self.save(status.value, status)

        report = self.recovery.recover()

        self.assertEqual(report.failed_closed, 3)
        for status in (
            CampaignStatus.RUNNING,
            CampaignStatus.PAUSING,
            CampaignStatus.CANCELLING,
        ):
            record = self.repository.get(status.value)
            self.assertEqual(record.state.status, CampaignStatus.FAILED)
            self.assertIn(status.value, record.state.last_error)
            self.assertEqual(
                [event.kind for event in self.events.history(status.value)],
                [CampaignEventKind.RECOVERED, CampaignEventKind.FAILED],
            )
            self.assertEqual(
                self.events.history(status.value)[-1].payload["phase"],
                "startup_recovery",
            )

    def test_terminal_states_are_retained_without_events(self) -> None:
        for status in (
            CampaignStatus.SUCCEEDED,
            CampaignStatus.FAILED,
            CampaignStatus.CANCELLED,
        ):
            self.save(status.value, status)

        report = self.recovery.recover()

        self.assertEqual(report.count(RecoveryAction.RETAINED_TERMINAL), 3)
        for status in (
            CampaignStatus.SUCCEEDED,
            CampaignStatus.FAILED,
            CampaignStatus.CANCELLED,
        ):
            self.assertEqual(self.repository.get(status.value).state.status, status)
            self.assertEqual(self.events.history(status.value), ())


if __name__ == "__main__":
    unittest.main()
