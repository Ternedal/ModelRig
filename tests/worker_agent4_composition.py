#!/usr/bin/env python3
"""A4-07 explicit runtime composition contract tests."""

from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.agent4 import (
    CampaignEventKind,
    CampaignHealthObservation,
    CampaignSpec,
    CampaignStatus,
    CampaignValidationError,
    FailureDescriptor,
)
from app.agent4.composition import Agent4RuntimeContext, compose_agent4_runtime


BASE_TIME = datetime(2026, 7, 30, 20, 0, tzinfo=timezone.utc)


class _Clock:
    def __init__(self, value: datetime = BASE_TIME) -> None:
        self.value = value

    def now(self) -> datetime:
        return self.value


class _Executor:
    def __init__(self) -> None:
        self.dispatched: list[tuple[str, int]] = []
        self.signals: list[tuple[str, str]] = []

    def dispatch(self, spec, state) -> str:
        self.dispatched.append((spec.campaign_id, state.attempt))
        return f"runtime:{spec.campaign_id}:{state.attempt}"

    def signal(self, campaign_id: str, command: str) -> None:
        self.signals.append((campaign_id, command))


class Agent4RuntimeCompositionTests(unittest.TestCase):
    def compose(
        self,
        root: Path | str,
        *,
        clock: _Clock | None = None,
        executor: _Executor | None = None,
    ) -> tuple[Agent4RuntimeContext, _Clock, _Executor]:
        runtime_clock = clock if clock is not None else _Clock()
        runtime_executor = executor if executor is not None else _Executor()
        context = compose_agent4_runtime(
            root,
            executor=runtime_executor,
            resource_capacities={"gpu": 1, "browser": 2},
            resource_resolver=lambda spec: {"gpu": 1},
            clock=runtime_clock,
            resource_lease_ttl=timedelta(minutes=15),
        )
        return context, runtime_clock, runtime_executor

    @staticmethod
    def spec(
        campaign_id: str = "campaign-composed",
        *,
        scheduled_for: datetime | None = None,
        max_attempts: int = 2,
    ) -> CampaignSpec:
        return CampaignSpec(
            campaign_id=campaign_id,
            name="Composed campaign",
            workflow="agent3.write-pilot",
            created_at=BASE_TIME,
            scheduled_for=scheduled_for,
            max_attempts=max_attempts,
        )

    def test_composition_is_dormant_and_wires_one_shared_object_graph(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "runtime"
            context, _, executor = self.compose(root)

            self.assertFalse(root.exists())
            self.assertEqual(context.paths.root, root)
            self.assertEqual(context.paths.campaigns, root / "campaigns")
            self.assertEqual(context.paths.checkpoints, root / "checkpoints")
            self.assertEqual(context.paths.timeline, root / "timeline")
            self.assertEqual(context.repository.list(), ())
            self.assertEqual(context.timeline.history("unknown"), ())
            self.assertEqual(context.scheduler.queued_count, 0)
            self.assertEqual(executor.dispatched, [])
            self.assertIs(context.scheduler._repository, context.repository)
            self.assertIs(context.scheduler._events, context.events)
            self.assertIs(context.scheduler._queue, context.queue)
            self.assertIs(context.checkpoints._repository, context.repository)
            self.assertIs(context.checkpoints._events, context.events)
            self.assertIs(context.retries._queue, context.queue)
            self.assertIs(context.retries._events, context.events)

    def test_submit_dispatch_and_checkpoint_share_durable_timeline(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            context, clock, executor = self.compose(Path(directory) / "runtime")
            context.scheduler.submit(self.spec())
            dispatched = context.scheduler.dispatch_ready()

            self.assertIsNotNone(dispatched)
            assert dispatched is not None
            self.assertEqual(dispatched.runtime_reference, "runtime:campaign-composed:1")
            self.assertEqual(executor.dispatched, [("campaign-composed", 1)])
            lease = context.resources.for_campaign("campaign-composed", now=clock.now())
            self.assertIsNotNone(lease)

            context.checkpoints.checkpoint(
                "campaign-composed",
                "checkpoint-1",
                {"progress": 50},
            )
            self.assertIsNotNone(
                context.checkpoint_store.get("campaign-composed", "checkpoint-1")
            )
            self.assertEqual(
                [event.kind for event in context.timeline.events("campaign-composed")],
                [
                    CampaignEventKind.CREATED,
                    CampaignEventKind.STARTED,
                    CampaignEventKind.CHECKPOINTED,
                ],
            )

    def test_retry_service_reuses_queue_timeline_and_resource_release(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            context, clock, _ = self.compose(Path(directory) / "runtime")
            context.scheduler.submit(self.spec(max_attempts=2))
            context.scheduler.dispatch_ready()

            result = context.retries.handle_failure(
                "campaign-composed",
                FailureDescriptor(
                    error_type="TimeoutError",
                    message="runtime timed out",
                    phase="runtime",
                ),
            )

            self.assertTrue(result.scheduled)
            self.assertEqual(result.record.state.status, CampaignStatus.SCHEDULED)
            self.assertEqual(context.scheduler.queued_count, 1)
            self.assertIsNone(
                context.resources.for_campaign("campaign-composed", now=clock.now())
            )
            self.assertEqual(
                context.timeline.events("campaign-composed")[-1].kind,
                CampaignEventKind.RETRY_SCHEDULED,
            )

    def test_restart_requires_explicit_recovery_and_preserves_event_sequence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "runtime"
            first, _, _ = self.compose(root)
            first.scheduler.submit(
                self.spec(
                    campaign_id="campaign-restart",
                    scheduled_for=BASE_TIME + timedelta(hours=1),
                )
            )

            second, _, _ = self.compose(root)
            self.assertEqual(second.scheduler.queued_count, 0)
            self.assertEqual(second.events.latest_sequence("campaign-restart"), 2)

            report = second.recover()

            self.assertEqual(report.scanned, 1)
            self.assertEqual(report.requeued, 1)
            self.assertEqual(second.scheduler.queued_count, 1)
            self.assertEqual(second.events.latest_sequence("campaign-restart"), 3)

    def test_watchdog_is_built_explicitly_and_uses_shared_fail_closed_service(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            context, clock, _ = self.compose(Path(directory) / "runtime")
            context.scheduler.submit(self.spec())
            context.scheduler.dispatch_ready()
            coordinator = context.watchdog()

            record = context.repository.get("campaign-composed")
            self.assertIsNotNone(record)
            assert record is not None
            self.assertEqual(record.state.status, CampaignStatus.RUNNING)
            clock.value = BASE_TIME + timedelta(minutes=3)
            result = coordinator.execute(
                CampaignHealthObservation(
                    campaign_id="campaign-composed",
                    status=CampaignStatus.RUNNING,
                    observed_at=clock.value,
                    runtime_started_at=BASE_TIME,
                    heartbeat_at=BASE_TIME,
                )
            )

            self.assertTrue(result.executed)
            failed = context.repository.get("campaign-composed")
            self.assertIsNotNone(failed)
            assert failed is not None
            self.assertEqual(failed.state.status, CampaignStatus.FAILED)
            self.assertIsNone(
                context.resources.for_campaign("campaign-composed", now=clock.now())
            )
            self.assertEqual(
                context.timeline.events("campaign-composed")[-1].kind,
                CampaignEventKind.FAILED,
            )

    def test_invalid_boundaries_fail_before_filesystem_activation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "runtime"
            with self.assertRaises(CampaignValidationError):
                compose_agent4_runtime(
                    root,
                    executor=object(),
                    resource_capacities={"gpu": 1},
                    resource_resolver=lambda spec: {},
                )
            with self.assertRaises(CampaignValidationError):
                compose_agent4_runtime(
                    root,
                    executor=_Executor(),
                    resource_capacities={"gpu": 1},
                    resource_resolver=None,
                )
            self.assertFalse(root.exists())


if __name__ == "__main__":
    unittest.main()
