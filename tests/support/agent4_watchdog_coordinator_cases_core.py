"""Watchdog coordinator and concrete-adapter cases imported by the workflow gate."""

from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.agent4 import (
    CampaignCheckpointService,
    CampaignConflictError,
    CampaignHealthObservation,
    CampaignRecord,
    CampaignSpec,
    CampaignState,
    CampaignStatus,
    CampaignWatchdogCoordinator,
    CampaignWatchdogFailClosedService,
    InMemoryCampaignEventBus,
    JsonCampaignRepository,
    JsonCheckpointStore,
    WatchdogAction,
    WatchdogAdapterCompositionError,
    WatchdogCompositionError,
    WatchdogExecutionError,
    WatchdogServiceAdapters,
)

BASE_TIME = datetime(2026, 7, 29, 15, 0, tzinfo=timezone.utc)
ADAPTER_TIME = datetime(2026, 7, 29, 20, 30, tzinfo=timezone.utc)


class _CoordinatorCases:
    def coordinator_set_up(self) -> None:
        self.coordinator_record = CampaignRecord(
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
        self.repository.save(self.coordinator_record)

    def coordinator_observation(self, **changes):
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
        ).execute(self.coordinator_observation())
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
                result = coordinator.execute(self.coordinator_observation(**changes))
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
                self.coordinator_observation(
                    status=CampaignStatus.PAUSING,
                    heartbeat_at=None,
                )
            )
        with self.assertRaises(Exception):
            coordinator.execute(
                self.coordinator_observation(
                    observed_at=BASE_TIME - timedelta(minutes=3)
                )
            )

    def test_missing_handler_is_a_composition_error(self) -> None:
        coordinator = CampaignWatchdogCoordinator(repository=self.repository)
        with self.assertRaises(WatchdogCompositionError):
            coordinator.execute(
                self.coordinator_observation(
                    heartbeat_at=BASE_TIME - timedelta(minutes=2)
                )
            )

    def test_handler_failure_is_wrapped_without_fallback_action(self) -> None:
        def fail(*args):
            raise RuntimeError("pause adapter unavailable")

        coordinator = CampaignWatchdogCoordinator(
            repository=self.repository,
            handlers={WatchdogAction.REQUEST_PAUSE: fail},
        )
        with self.assertRaises(WatchdogExecutionError) as raised:
            coordinator.execute(
                self.coordinator_observation(consecutive_failures=3)
            )
        self.assertIn("pause adapter unavailable", str(raised.exception))

    def test_unknown_campaign_fails_before_policy_execution(self) -> None:
        coordinator = CampaignWatchdogCoordinator(repository=self.repository)
        with self.assertRaises(Exception):
            coordinator.evaluate(
                self.coordinator_observation(campaign_id="missing-campaign")
            )


class _Clock:
    def now(self) -> datetime:
        return ADAPTER_TIME


class _Lifecycle:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def renew_resources(self, campaign_id: str):
        self.calls.append(("renew", campaign_id))
        return "renewed"

    def request_pause(self, campaign_id: str):
        self.calls.append(("pause", campaign_id))
        return "pausing"


class _AdapterCases:
    def adapter_set_up(self) -> None:
        self.adapter_events = InMemoryCampaignEventBus()
        self.lifecycle = _Lifecycle()
        self.adapter_record = CampaignRecord(
            spec=CampaignSpec(
                campaign_id="campaign-watchdog-adapters",
                name="Watchdog adapters",
                workflow="agent3.write-pilot",
                created_at=ADAPTER_TIME - timedelta(minutes=10),
            ),
            state=CampaignState(
                campaign_id="campaign-watchdog-adapters",
                status=CampaignStatus.RUNNING,
                attempt=1,
                updated_at=ADAPTER_TIME - timedelta(minutes=2),
            ),
        )
        self.repository.save(self.adapter_record)
        self.fail_closed = CampaignWatchdogFailClosedService(
            repository=self.repository,
            events=self.adapter_events,
            clock=_Clock(),
            release_resources=lambda campaign_id: self.lifecycle.calls.append(
                ("release", campaign_id)
            ),
        )
        self.checkpoints = CampaignCheckpointService(
            repository=self.repository,
            checkpoints=JsonCheckpointStore(Path(self.temp.name) / "checkpoints"),
            events=self.adapter_events,
            clock=_Clock(),
        )

    def adapter_observation(self, **changes):
        values = dict(
            campaign_id=self.adapter_record.spec.campaign_id,
            status=self.adapter_record.state.status,
            observed_at=ADAPTER_TIME - timedelta(seconds=1),
            runtime_started_at=ADAPTER_TIME - timedelta(minutes=5),
            heartbeat_at=ADAPTER_TIME - timedelta(seconds=10),
            progress_at=ADAPTER_TIME - timedelta(minutes=1),
            resource_lease_expires_at=ADAPTER_TIME + timedelta(minutes=5),
        )
        values.update(changes)
        return CampaignHealthObservation(**values)

    def adapters(self, *, checkpoint: bool = True) -> WatchdogServiceAdapters:
        return WatchdogServiceAdapters(
            lifecycle=self.lifecycle,
            fail_closed_service=self.fail_closed,
            checkpoints=self.checkpoints if checkpoint else None,
            checkpoint_payload=(
                lambda record, observation, decision: (
                    "watchdog-checkpoint-1",
                    {"reason": decision.reason},
                )
            )
            if checkpoint
            else None,
        )

    def test_adapters_route_renew_and_pause_to_lifecycle_service(self) -> None:
        coordinator = CampaignWatchdogCoordinator(
            repository=self.repository,
            handlers=self.adapters().handlers(),
        )
        renew = coordinator.execute(
            self.adapter_observation(
                resource_lease_expires_at=ADAPTER_TIME + timedelta(seconds=10)
            )
        )
        pause = coordinator.execute(
            self.adapter_observation(consecutive_failures=3)
        )
        self.assertEqual(renew.handler_result, "renewed")
        self.assertEqual(pause.handler_result, "pausing")
        self.assertEqual(
            self.lifecycle.calls,
            [
                ("renew", self.adapter_record.spec.campaign_id),
                ("pause", self.adapter_record.spec.campaign_id),
            ],
        )

    def test_adapter_checkpoint_persists_payload_and_pointer(self) -> None:
        result = CampaignWatchdogCoordinator(
            repository=self.repository,
            handlers=self.adapters().handlers(),
        ).execute(
            self.adapter_observation(
                progress_at=ADAPTER_TIME - timedelta(minutes=20)
            )
        )
        self.assertEqual(
            result.handler_result.state.checkpoint_id,
            "watchdog-checkpoint-1",
        )
        checkpoint = self.checkpoints.load(self.adapter_record.spec.campaign_id)
        self.assertEqual(checkpoint.payload["reason"], result.decision.reason)

    def test_adapter_fail_closed_persists_event_and_releases(self) -> None:
        result = CampaignWatchdogCoordinator(
            repository=self.repository,
            handlers=self.adapters().handlers(),
        ).execute(
            self.adapter_observation(
                heartbeat_at=ADAPTER_TIME - timedelta(minutes=3)
            )
        )
        self.assertEqual(result.handler_result.state.status, CampaignStatus.FAILED)
        self.assertEqual(
            self.adapter_events.history(self.adapter_record.spec.campaign_id)[-1]
            .payload["phase"],
            "watchdog",
        )
        self.assertIn(
            ("release", self.adapter_record.spec.campaign_id),
            self.lifecycle.calls,
        )

    def test_adapter_fail_closed_supports_transitional_states(self) -> None:
        for status in (CampaignStatus.PAUSING, CampaignStatus.CANCELLING):
            with self.subTest(status=status):
                record = CampaignRecord(
                    spec=self.adapter_record.spec,
                    state=CampaignState(
                        campaign_id=self.adapter_record.spec.campaign_id,
                        status=status,
                        attempt=1,
                        updated_at=ADAPTER_TIME - timedelta(minutes=2),
                    ),
                )
                self.repository.save(record)
                result = CampaignWatchdogCoordinator(
                    repository=self.repository,
                    handlers=self.adapters().handlers(),
                ).execute(
                    self.adapter_observation(
                        status=status,
                        heartbeat_at=ADAPTER_TIME - timedelta(minutes=3),
                    )
                )
                self.assertEqual(
                    result.handler_result.state.status,
                    CampaignStatus.FAILED,
                )

    def test_adapter_fail_closed_revalidates_record_after_evaluation(self) -> None:
        observation = self.adapter_observation(
            heartbeat_at=ADAPTER_TIME - timedelta(minutes=3)
        )
        evaluated = CampaignWatchdogCoordinator(
            repository=self.repository,
            handlers=self.adapters().handlers(),
        ).evaluate(observation)
        changed = CampaignRecord(
            spec=self.adapter_record.spec,
            state=CampaignState(
                campaign_id=self.adapter_record.spec.campaign_id,
                status=CampaignStatus.PAUSING,
                attempt=1,
                revision=self.adapter_record.state.revision + 1,
                updated_at=ADAPTER_TIME,
            ),
        )
        self.repository.save(changed)
        with self.assertRaises(CampaignConflictError):
            self.fail_closed.fail_closed(
                evaluated.record,
                observation,
                evaluated.decision,
            )
        self.assertEqual(
            self.repository.get(self.adapter_record.spec.campaign_id),
            changed,
        )

    def test_adapter_checkpoint_dependencies_are_atomic_pair(self) -> None:
        with self.assertRaises(WatchdogAdapterCompositionError):
            WatchdogServiceAdapters(
                lifecycle=self.lifecycle,
                fail_closed_service=self.fail_closed,
                checkpoints=self.checkpoints,
            )
        self.assertNotIn(
            WatchdogAction.REQUEST_CHECKPOINT,
            self.adapters(checkpoint=False).handlers(),
        )


class Agent4WatchdogCoordinatorTests(
    _CoordinatorCases,
    _AdapterCases,
    unittest.TestCase,
):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.repository = JsonCampaignRepository(Path(self.temp.name) / "campaigns")
        self.coordinator_set_up()
        self.adapter_set_up()

    def tearDown(self) -> None:
        self.temp.cleanup()
