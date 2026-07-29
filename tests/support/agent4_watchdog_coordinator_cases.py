"""Imported watchdog-coordinator cases executed by workflow_agent4_foundation."""

from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.agent4 import (
    CampaignHealthObservation,
    CampaignRecord,
    CampaignSpec,
    CampaignState,
    CampaignStatus,
    CampaignWatchdogCoordinator,
    JsonCampaignRepository,
    WatchdogAction,
    WatchdogCompositionError,
    WatchdogExecutionError,
)

BASE_TIME = datetime(2026, 7, 29, 15, 0, tzinfo=timezone.utc)


class Agent4WatchdogCoordinatorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.repository = JsonCampaignRepository(Path(self.temp.name))
        self.record = CampaignRecord(
            spec=CampaignSpec(
                campaign_id="campaign-watchdog",
                name="Watchdog campaign",
                workflow="agent3.write-pilot",
                created_at=BASE_TIME - timedelta(minutes=5),
            ),
            state=CampaignState(
                campaign_id="campaign-watchdog",
                status=CampaignStatus.RUNNING,
                attempt=1,
                updated_at=BASE_TIME - timedelta(minutes=2),
            ),
        )
        self.repository.save(self.record)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def observation(self, **changes):
        values = dict(
            campaign_id="campaign-watchdog",
            status=CampaignStatus.RUNNING,
            observed_at=BASE_TIME,
            runtime_started_at=BASE_TIME - timedelta(minutes=4),
            heartbeat_at=BASE_TIME - timedelta(seconds=10),
            progress_at=BASE_TIME - timedelta(minutes=1),
            resource_lease_expires_at=BASE_TIME + timedelta(minutes=5),
        )
        values.update(changes)
        return CampaignHealthObservation(**values)

    def test_healthy_observation_does_not_require_handlers(self) -> None:
        result = CampaignWatchdogCoordinator(
            repository=self.repository
        ).execute(self.observation())
        self.assertFalse(result.executed)
        self.assertEqual(result.decision.action, WatchdogAction.NONE)

    def test_each_action_routes_only_to_its_configured_handler(self) -> None:
        calls: list[tuple[str, str]] = []
        handlers = {
            action: (
                lambda record, observation, decision, action=action:
                calls.append((action.value, record.spec.campaign_id)) or action.value
            )
            for action in WatchdogAction
            if action is not WatchdogAction.NONE
        }
        coordinator = CampaignWatchdogCoordinator(
            repository=self.repository, handlers=handlers
        )
        cases = (
            (
                dict(resource_lease_expires_at=BASE_TIME + timedelta(seconds=5)),
                WatchdogAction.RENEW_RESOURCES,
            ),
            (
                dict(progress_at=BASE_TIME - timedelta(minutes=15)),
                WatchdogAction.REQUEST_CHECKPOINT,
            ),
            (dict(consecutive_failures=3), WatchdogAction.REQUEST_PAUSE),
            (
                dict(heartbeat_at=BASE_TIME - timedelta(minutes=2)),
                WatchdogAction.FAIL_CLOSED,
            ),
        )
        for changes, expected in cases:
            with self.subTest(action=expected):
                result = coordinator.execute(self.observation(**changes))
                self.assertTrue(result.executed)
                self.assertEqual(result.decision.action, expected)
                self.assertEqual(result.handler_result, expected.value)
        self.assertEqual(
            [action for action, _ in calls],
            [case[1].value for case in cases],
        )

    def test_stale_status_or_timestamp_cannot_execute(self) -> None:
        coordinator = CampaignWatchdogCoordinator(
            repository=self.repository,
            handlers={WatchdogAction.FAIL_CLOSED: lambda *args: None},
        )
        with self.assertRaises(Exception):
            coordinator.execute(
                self.observation(status=CampaignStatus.PAUSING, heartbeat_at=None)
            )
        with self.assertRaises(Exception):
            coordinator.execute(
                self.observation(observed_at=BASE_TIME - timedelta(minutes=3))
            )

    def test_missing_handler_is_a_composition_error(self) -> None:
        coordinator = CampaignWatchdogCoordinator(repository=self.repository)
        with self.assertRaises(WatchdogCompositionError):
            coordinator.execute(
                self.observation(heartbeat_at=BASE_TIME - timedelta(minutes=2))
            )

    def test_handler_failure_is_wrapped_without_fallback_action(self) -> None:
        def fail(*args):
            raise RuntimeError("pause adapter unavailable")

        coordinator = CampaignWatchdogCoordinator(
            repository=self.repository,
            handlers={WatchdogAction.REQUEST_PAUSE: fail},
        )
        with self.assertRaises(WatchdogExecutionError) as raised:
            coordinator.execute(self.observation(consecutive_failures=3))
        self.assertIn("pause adapter unavailable", str(raised.exception))

    def test_unknown_campaign_fails_before_policy_execution(self) -> None:
        coordinator = CampaignWatchdogCoordinator(repository=self.repository)
        with self.assertRaises(Exception):
            coordinator.evaluate(
                self.observation(campaign_id="missing-campaign")
            )
