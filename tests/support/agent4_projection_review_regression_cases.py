"""Regression coverage for actionable review findings on A4-11."""

from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.agent4 import (
    CampaignEventKind,
    CampaignHealthObservation,
    CampaignProjectionError,
    CampaignProjectionReconciler,
    CampaignQueue,
    CampaignRecord,
    CampaignRecoveryService,
    CampaignSchedulerService,
    CampaignSpec,
    CampaignState,
    CampaignStateProjectionService,
    CampaignStatus,
    HealthDecision,
    HealthInterventionAction,
    HealthLevel,
    InMemoryCampaignEventBus,
    JsonCampaignRepository,
    JsonCampaignTimelineStore,
)
from app.agent4.projected_services import ProjectedCampaignHealthFailClosedService


BASE_TIME = datetime(2026, 7, 31, 14, 0, tzinfo=timezone.utc)


class MutableClock:
    def __init__(self, value: datetime = BASE_TIME) -> None:
        self.value = value

    def now(self) -> datetime:
        return self.value


class SequenceClock:
    def __init__(self, *values: datetime) -> None:
        self._values = list(values)

    def now(self) -> datetime:
        if not self._values:
            raise AssertionError("clock sequence exhausted")
        return self._values.pop(0)


class RecordingExecutor:
    def __init__(self) -> None:
        self.signals: list[tuple[str, str]] = []

    def dispatch(self, spec, state) -> str:
        return "agent3:review-regression"

    def signal(self, campaign_id: str, command: str) -> None:
        self.signals.append((campaign_id, command))


class PersistThenFailProjection:
    """Model a durable state+intent write followed by reconciliation failure."""

    def __init__(self, repository: JsonCampaignRepository) -> None:
        self._repository = repository

    def persist(self, record, projections):
        self._repository.save(record)
        raise CampaignProjectionError("timeline unavailable")


class FailBeforePersistProjection:
    """Model a repository failure before the terminal record becomes durable."""

    def persist(self, record, projections):
        raise OSError("campaign repository is unwritable")


class Agent4ProjectionReviewRegressionTests(unittest.TestCase):
    def test_cancel_signal_runs_when_audit_reconciliation_fails(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository = JsonCampaignRepository(Path(directory) / "campaigns")
            executor = RecordingExecutor()
            clock = MutableClock()
            service = CampaignSchedulerService(
                repository=repository,
                executor=executor,
                events=InMemoryCampaignEventBus(),
                clock=clock,
            )
            spec = CampaignSpec(
                campaign_id="cancel-review",
                name="Cancel review",
                workflow="agent3.write-pilot",
                created_at=BASE_TIME,
            )
            service.submit(spec)
            service.dispatch_ready()
            service._projections = PersistThenFailProjection(repository)

            with self.assertRaises(CampaignProjectionError):
                service.request_cancel(spec.campaign_id)

            self.assertEqual(executor.signals, [(spec.campaign_id, "cancel")])
            self.assertEqual(
                repository.get(spec.campaign_id).state.status,
                CampaignStatus.CANCELLING,
            )

    def test_health_failure_keeps_resources_when_failed_state_is_not_durable(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository = JsonCampaignRepository(Path(directory) / "campaigns")
            record = CampaignRecord(
                spec=CampaignSpec(
                    campaign_id="health-review",
                    name="Health review",
                    workflow="agent3.write-pilot",
                    created_at=BASE_TIME - timedelta(minutes=5),
                ),
                state=CampaignState(
                    campaign_id="health-review",
                    status=CampaignStatus.RUNNING,
                    attempt=1,
                    updated_at=BASE_TIME - timedelta(minutes=2),
                ),
            )
            repository.save(record)
            releases: list[str] = []
            service = ProjectedCampaignHealthFailClosedService(
                repository=repository,
                events=InMemoryCampaignEventBus(),
                clock=MutableClock(),
                release_resources=releases.append,
                projections=FailBeforePersistProjection(),
            )
            observation = CampaignHealthObservation(
                campaign_id=record.spec.campaign_id,
                status=CampaignStatus.RUNNING,
                observed_at=BASE_TIME - timedelta(seconds=1),
                runtime_started_at=BASE_TIME - timedelta(minutes=4),
                heartbeat_at=BASE_TIME - timedelta(minutes=3),
            )
            decision = HealthDecision(
                level=HealthLevel.UNRESPONSIVE,
                action=HealthInterventionAction.FAIL_CLOSED,
                reason="runtime heartbeat is stale",
            )

            with self.assertRaises(OSError):
                service.fail_closed(record, observation, decision)

            self.assertEqual(releases, [])
            self.assertEqual(repository.get(record.spec.campaign_id), record)

    def test_recovery_events_use_invocation_time_and_unique_identity(self) -> None:
        first = BASE_TIME
        second = BASE_TIME + timedelta(minutes=10)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repository = JsonCampaignRepository(root / "campaigns")
            timeline = JsonCampaignTimelineStore(root / "timeline")
            record = CampaignRecord(
                spec=CampaignSpec(
                    campaign_id="recovery-review",
                    name="Recovery review",
                    workflow="agent3.write-pilot",
                    created_at=BASE_TIME - timedelta(hours=1),
                ),
                state=CampaignState(
                    campaign_id="recovery-review",
                    status=CampaignStatus.PAUSED,
                    attempt=1,
                    updated_at=BASE_TIME - timedelta(minutes=30),
                ),
            )
            repository.save(record)
            projections = CampaignStateProjectionService(
                repository=repository,
                reconciler=CampaignProjectionReconciler(
                    repository=repository,
                    timeline=timeline,
                ),
            )
            recovery = CampaignRecoveryService(
                repository=repository,
                queue=CampaignQueue(),
                events=InMemoryCampaignEventBus(),
                clock=SequenceClock(
                    first,
                    first + timedelta(seconds=1),
                    second,
                    second + timedelta(seconds=1),
                ),
                projections=projections,
            )

            recovery.recover()
            recovery.recover()

            events = [
                entry.event
                for entry in timeline.list(record.spec.campaign_id)
                if entry.event.kind is CampaignEventKind.RECOVERED
            ]
            self.assertEqual([event.occurred_at for event in events], [first, second])
            self.assertEqual(len({event.event_id for event in events}), 2)
