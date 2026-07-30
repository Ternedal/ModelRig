#!/usr/bin/env python3
"""Lifecycle coverage for the caller-driven Agent 4 scheduler service."""

from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.agent4 import (
    CampaignConflictError,
    CampaignEventKind,
    CampaignNotFoundError,
    CampaignSchedulerService,
    CampaignSpec,
    CampaignStatus,
    InMemoryCampaignEventBus,
    JsonCampaignRepository,
)


BASE_TIME = datetime(2026, 7, 29, 16, 0, tzinfo=timezone.utc)


class MutableClock:
    def __init__(self, value: datetime = BASE_TIME) -> None:
        self.value = value

    def now(self) -> datetime:
        return self.value


class RecordingExecutor:
    def __init__(self) -> None:
        self.dispatches: list[tuple[str, int]] = []
        self.signals: list[tuple[str, str]] = []
        self.dispatch_error: Exception | None = None
        self.signal_error: Exception | None = None
        self.runtime_reference = "agent3:run-1"

    def dispatch(self, spec, state) -> str:
        self.dispatches.append((spec.campaign_id, state.attempt))
        if self.dispatch_error is not None:
            raise self.dispatch_error
        return self.runtime_reference

    def signal(self, campaign_id: str, command: str) -> None:
        self.signals.append((campaign_id, command))
        if self.signal_error is not None:
            raise self.signal_error


class SchedulerServiceHarness:
    def __init__(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.repository = JsonCampaignRepository(Path(self.directory.name))
        self.executor = RecordingExecutor()
        self.events = InMemoryCampaignEventBus()
        self.clock = MutableClock()
        self.service = CampaignSchedulerService(
            repository=self.repository,
            executor=self.executor,
            events=self.events,
            clock=self.clock,
        )

    def close(self) -> None:
        self.directory.cleanup()

    def spec(
        self,
        campaign_id: str = "campaign-1",
        *,
        ready_at: datetime = BASE_TIME,
    ) -> CampaignSpec:
        return CampaignSpec(
            campaign_id=campaign_id,
            name=f"Campaign {campaign_id}",
            workflow="agent3.write-pilot",
            created_at=BASE_TIME,
            scheduled_for=ready_at,
            max_attempts=3,
        )


class CampaignSchedulerServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.harness = SchedulerServiceHarness()

    def tearDown(self) -> None:
        self.harness.close()

    def test_submit_immediate_campaign_persists_and_emits_created(self) -> None:
        record = self.harness.service.submit(self.harness.spec())

        self.assertEqual(record.state.status, CampaignStatus.QUEUED)
        self.assertEqual(self.harness.service.queued_count, 1)
        self.assertEqual(
            [event.kind for event in self.harness.events.history("campaign-1")],
            [CampaignEventKind.CREATED],
        )
        self.assertEqual(self.harness.service.get("campaign-1"), record)

    def test_scheduled_campaign_waits_until_ready(self) -> None:
        ready_at = BASE_TIME + timedelta(minutes=5)
        record = self.harness.service.submit(
            self.harness.spec(ready_at=ready_at)
        )

        self.assertEqual(record.state.status, CampaignStatus.SCHEDULED)
        self.assertIsNone(self.harness.service.dispatch_ready())
        self.harness.clock.value = ready_at
        result = self.harness.service.dispatch_ready()

        self.assertIsNotNone(result)
        self.assertTrue(result.succeeded)
        self.assertEqual(result.record.state.status, CampaignStatus.RUNNING)
        self.assertEqual(result.record.state.attempt, 1)
        self.assertEqual(result.runtime_reference, "agent3:run-1")
        self.assertEqual(self.harness.executor.dispatches, [("campaign-1", 1)])
        self.assertEqual(
            [event.kind for event in self.harness.events.history("campaign-1")],
            [
                CampaignEventKind.CREATED,
                CampaignEventKind.SCHEDULED,
                CampaignEventKind.STARTED,
            ],
        )

    def test_dispatch_exception_becomes_durable_failure(self) -> None:
        self.harness.executor.dispatch_error = RuntimeError("runtime unavailable")
        self.harness.service.submit(self.harness.spec())

        result = self.harness.service.dispatch_ready()

        self.assertIsNotNone(result)
        self.assertFalse(result.succeeded)
        self.assertEqual(result.record.state.status, CampaignStatus.FAILED)
        self.assertIn("runtime unavailable", result.record.state.last_error)
        self.assertEqual(
            self.harness.service.get("campaign-1").state.status,
            CampaignStatus.FAILED,
        )
        self.assertEqual(
            self.harness.events.history("campaign-1")[-1].kind,
            CampaignEventKind.FAILED,
        )

    def test_empty_runtime_reference_fails_closed(self) -> None:
        self.harness.executor.runtime_reference = " "
        self.harness.service.submit(self.harness.spec())

        result = self.harness.service.dispatch_ready()

        self.assertFalse(result.succeeded)
        self.assertEqual(result.record.state.status, CampaignStatus.FAILED)
        self.assertIn("empty runtime reference", result.dispatch_error)

    def test_pause_ack_and_resume_preserve_the_attempt(self) -> None:
        self.harness.service.submit(self.harness.spec())
        self.harness.service.dispatch_ready()

        pausing = self.harness.service.request_pause("campaign-1")
        paused = self.harness.service.mark_paused("campaign-1")
        resumed = self.harness.service.resume("campaign-1")

        self.assertEqual(pausing.state.status, CampaignStatus.PAUSING)
        self.assertEqual(paused.state.status, CampaignStatus.PAUSED)
        self.assertEqual(resumed.state.status, CampaignStatus.RUNNING)
        self.assertEqual(resumed.state.attempt, 1)
        self.assertEqual(self.harness.service.queued_count, 0)
        self.assertEqual(
            self.harness.executor.signals,
            [("campaign-1", "pause"), ("campaign-1", "resume")],
        )
        self.assertEqual(
            [event.kind for event in self.harness.events.history("campaign-1")],
            [
                CampaignEventKind.CREATED,
                CampaignEventKind.STARTED,
                CampaignEventKind.PAUSE_REQUESTED,
                CampaignEventKind.PAUSED,
                CampaignEventKind.RESUMED,
            ],
        )

    def test_pause_signal_failure_becomes_durable_failure(self) -> None:
        self.harness.service.submit(self.harness.spec())
        self.harness.service.dispatch_ready()
        self.harness.executor.signal_error = OSError("signal channel closed")

        result = self.harness.service.request_pause("campaign-1")

        self.assertEqual(result.state.status, CampaignStatus.FAILED)
        self.assertIn("signal channel closed", result.state.last_error)
        self.assertEqual(
            self.harness.events.history("campaign-1")[-1].payload["phase"],
            "pause_signal",
        )

    def test_queued_cancel_is_immediate_and_idempotent(self) -> None:
        self.harness.service.submit(self.harness.spec())

        cancelled = self.harness.service.request_cancel("campaign-1")
        repeated = self.harness.service.request_cancel("campaign-1")

        self.assertEqual(cancelled.state.status, CampaignStatus.CANCELLED)
        self.assertEqual(repeated, cancelled)
        self.assertEqual(self.harness.service.queued_count, 0)
        self.assertEqual(self.harness.executor.signals, [])

    def test_running_cancel_waits_for_ack(self) -> None:
        self.harness.service.submit(self.harness.spec())
        self.harness.service.dispatch_ready()

        cancelling = self.harness.service.request_cancel("campaign-1")
        cancelled = self.harness.service.mark_cancelled("campaign-1")

        self.assertEqual(cancelling.state.status, CampaignStatus.CANCELLING)
        self.assertEqual(cancelled.state.status, CampaignStatus.CANCELLED)
        self.assertEqual(
            self.harness.executor.signals,
            [("campaign-1", "cancel")],
        )

    def test_paused_cancel_releases_the_delegated_runtime(self) -> None:
        self.harness.service.submit(self.harness.spec())
        self.harness.service.dispatch_ready()
        self.harness.service.request_pause("campaign-1")
        self.harness.service.mark_paused("campaign-1")

        cancelling = self.harness.service.request_cancel("campaign-1")
        cancelled = self.harness.service.mark_cancelled("campaign-1")

        self.assertEqual(cancelling.state.status, CampaignStatus.CANCELLING)
        self.assertEqual(cancelled.state.status, CampaignStatus.CANCELLED)
        self.assertEqual(
            self.harness.executor.signals,
            [("campaign-1", "pause"), ("campaign-1", "cancel")],
        )

    def test_complete_records_success_or_failure(self) -> None:
        self.harness.service.submit(self.harness.spec("success"))
        self.harness.service.dispatch_ready()
        succeeded = self.harness.service.complete("success", succeeded=True)

        self.harness.service.submit(self.harness.spec("failure"))
        self.harness.service.dispatch_ready()
        failed = self.harness.service.complete(
            "failure",
            succeeded=False,
            error="validation failed",
        )

        self.assertEqual(succeeded.state.status, CampaignStatus.SUCCEEDED)
        self.assertEqual(failed.state.status, CampaignStatus.FAILED)
        self.assertEqual(failed.state.last_error, "validation failed")

    def test_duplicate_unknown_and_invalid_lifecycle_commands_fail(self) -> None:
        self.harness.service.submit(self.harness.spec())
        with self.assertRaises(CampaignConflictError):
            self.harness.service.submit(self.harness.spec())
        with self.assertRaises(CampaignNotFoundError):
            self.harness.service.request_cancel("missing")
        with self.assertRaises(CampaignConflictError):
            self.harness.service.request_pause("campaign-1")
        with self.assertRaises(CampaignConflictError):
            self.harness.service.mark_paused("campaign-1")


if __name__ == "__main__":
    unittest.main()
