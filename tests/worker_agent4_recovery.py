#!/usr/bin/env python3
"""Startup recovery and durable retry-scheduling coverage for Agent 4."""

from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.agent4 import (
    CampaignConflictError,
    CampaignEventKind,
    CampaignQueue,
    CampaignRecord,
    CampaignRecoveryService,
    CampaignRetryPlanner,
    CampaignRetrySchedulingService,
    CampaignSchedulerService,
    CampaignSpec,
    CampaignState,
    CampaignStatus,
    FailureDescriptor,
    InMemoryCampaignEventBus,
    JsonCampaignRepository,
    RecoveryAction,
    RetryPolicy,
)

NOW = datetime(2026, 7, 29, 18, 0, tzinfo=timezone.utc)
CAMPAIGN_ID = "campaign-retry-scheduling"


class MutableClock:
    def __init__(self) -> None:
        self.value = NOW

    def now(self) -> datetime:
        return self.value


class Executor:
    def dispatch(self, spec, state) -> str:
        return f"runtime:{state.attempt}"

    def signal(self, campaign_id: str, command: str) -> None:
        return None


class Agent4RecoveryAndRetryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.repository = JsonCampaignRepository(Path(self.temp.name))
        self.queue = CampaignQueue()
        self.events = InMemoryCampaignEventBus()
        self.clock = MutableClock()
        self.recovery = CampaignRecoveryService(
            repository=self.repository,
            queue=self.queue,
            events=self.events,
            clock=self.clock,
        )
        self.released: list[str] = []
        self.retry = CampaignRetrySchedulingService(
            repository=self.repository,
            queue=self.queue,
            events=self.events,
            clock=self.clock,
            planner=CampaignRetryPlanner(
                policy=RetryPolicy(initial_delay=timedelta(seconds=10))
            ),
            release_resources=lambda campaign_id: (
                self.released.append(campaign_id) or True
            ),
        )

    def tearDown(self) -> None:
        self.temp.cleanup()

    def record(
        self,
        status: CampaignStatus,
        *,
        campaign_id: str = CAMPAIGN_ID,
        attempt: int | None = None,
        max_attempts: int = 3,
    ) -> CampaignRecord:
        if attempt is None:
            attempt = 0 if status in {CampaignStatus.QUEUED, CampaignStatus.SCHEDULED} else 1
        scheduled_for = NOW + timedelta(hours=1) if status is CampaignStatus.SCHEDULED else None
        spec = CampaignSpec(
            campaign_id=campaign_id,
            name=campaign_id,
            workflow="agent3.write-pilot",
            created_at=NOW,
            scheduled_for=scheduled_for,
            max_attempts=max_attempts,
        )
        record = CampaignRecord(
            spec=spec,
            state=CampaignState(
                campaign_id=campaign_id,
                status=status,
                attempt=attempt,
                updated_at=NOW,
                last_error="previous failure" if status is CampaignStatus.FAILED else None,
            ),
        )
        self.repository.save(record)
        return record

    @staticmethod
    def failure(error_type: str = "TimeoutError") -> FailureDescriptor:
        return FailureDescriptor(
            error_type=error_type,
            message="runtime stopped",
            phase="execution",
        )

    def test_recovery_rehydrates_queued_and_scheduled_records(self) -> None:
        self.record(CampaignStatus.QUEUED, campaign_id="queued")
        self.record(CampaignStatus.SCHEDULED, campaign_id="scheduled")

        report = self.recovery.recover()

        self.assertEqual(report.scanned, 2)
        self.assertEqual(report.requeued, 2)
        self.assertEqual({spec.campaign_id for spec in self.queue.snapshot()}, {"queued", "scheduled"})
        self.assertEqual(self.events.history("queued")[0].kind, CampaignEventKind.RECOVERED)

    def test_recovery_is_idempotent_for_existing_queue_entry(self) -> None:
        record = self.record(CampaignStatus.QUEUED)
        self.queue.enqueue(record.spec)

        report = self.recovery.recover()

        self.assertEqual(report.count(RecoveryAction.ALREADY_QUEUED), 1)
        self.assertEqual(len(self.queue), 1)
        self.assertEqual(self.events.history(CAMPAIGN_ID), ())

    def test_paused_record_is_retained_but_not_queued(self) -> None:
        original = self.record(CampaignStatus.PAUSED)

        report = self.recovery.recover()

        self.assertEqual(report.count(RecoveryAction.RETAINED_PAUSED), 1)
        self.assertEqual(self.repository.get(CAMPAIGN_ID), original)
        self.assertNotIn(CAMPAIGN_ID, self.queue)

    def test_interrupted_active_states_fail_closed(self) -> None:
        for status in (
            CampaignStatus.RUNNING,
            CampaignStatus.PAUSING,
            CampaignStatus.CANCELLING,
        ):
            self.record(status, campaign_id=status.value)

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

    def test_terminal_records_are_retained_without_events(self) -> None:
        for status in (
            CampaignStatus.SUCCEEDED,
            CampaignStatus.FAILED,
            CampaignStatus.CANCELLED,
        ):
            self.record(status, campaign_id=status.value)

        report = self.recovery.recover()

        self.assertEqual(report.count(RecoveryAction.RETAINED_TERMINAL), 3)
        for status in (
            CampaignStatus.SUCCEEDED,
            CampaignStatus.FAILED,
            CampaignStatus.CANCELLED,
        ):
            self.assertEqual(self.repository.get(status.value).state.status, status)
            self.assertEqual(self.events.history(status.value), ())

    def test_retryable_failure_becomes_durable_scheduled_work(self) -> None:
        self.record(CampaignStatus.RUNNING)

        result = self.retry.handle_failure(CAMPAIGN_ID, self.failure())

        self.assertTrue(result.scheduled)
        self.assertEqual(result.record.state.status, CampaignStatus.SCHEDULED)
        self.assertEqual(result.record.state.attempt, 1)
        self.assertEqual(result.record.spec.scheduled_for, NOW + timedelta(seconds=10))
        self.assertEqual(self.repository.get(CAMPAIGN_ID), result.record)
        self.assertIn(CAMPAIGN_ID, self.queue)
        self.assertEqual(self.released, [CAMPAIGN_ID])
        self.assertEqual(
            self.events.history(CAMPAIGN_ID)[-1].kind,
            CampaignEventKind.RETRY_SCHEDULED,
        )

    def test_next_explicit_dispatch_consumes_next_attempt(self) -> None:
        self.record(CampaignStatus.RUNNING)
        self.retry.handle_failure(CAMPAIGN_ID, self.failure())
        scheduler = CampaignSchedulerService(
            repository=self.repository,
            queue=self.queue,
            executor=Executor(),
            events=self.events,
            clock=self.clock,
        )
        self.assertIsNone(scheduler.dispatch_ready())
        self.clock.value = NOW + timedelta(seconds=10)

        result = scheduler.dispatch_ready()

        self.assertEqual(result.record.state.status, CampaignStatus.RUNNING)
        self.assertEqual(result.record.state.attempt, 2)

    def test_permanent_and_exhausted_failures_are_terminal(self) -> None:
        for error_type, attempt, max_attempts in (
            ("ValueError", 1, 3),
            ("TimeoutError", 3, 3),
        ):
            with self.subTest(error_type=error_type):
                self.repository.delete(CAMPAIGN_ID)
                self.record(
                    CampaignStatus.RUNNING,
                    attempt=attempt,
                    max_attempts=max_attempts,
                )
                result = self.retry.handle_failure(
                    CAMPAIGN_ID,
                    self.failure(error_type),
                )
                self.assertFalse(result.scheduled)
                self.assertEqual(result.record.state.status, CampaignStatus.FAILED)
                self.assertNotIn(CAMPAIGN_ID, self.queue)

    def test_non_running_state_fails_without_mutation_or_release(self) -> None:
        original = self.record(CampaignStatus.QUEUED)

        with self.assertRaises(CampaignConflictError):
            self.retry.handle_failure(CAMPAIGN_ID, self.failure())

        self.assertEqual(self.repository.get(CAMPAIGN_ID), original)
        self.assertEqual(self.released, [])

    def test_durable_scheduled_retry_is_recoverable_if_queue_entry_is_lost(self) -> None:
        self.record(CampaignStatus.RUNNING)
        result = self.retry.handle_failure(CAMPAIGN_ID, self.failure())
        self.queue.remove(CAMPAIGN_ID)

        report = self.recovery.recover()

        self.assertEqual(report.requeued, 1)
        self.assertIn(CAMPAIGN_ID, self.queue)
        self.assertEqual(self.repository.get(CAMPAIGN_ID), result.record)


if __name__ == "__main__":
    unittest.main()
