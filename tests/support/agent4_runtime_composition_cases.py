"""A4-09 explicit B-reference runtime composition contract cases."""

from __future__ import annotations

import gc
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.agent4 import (
    Agent4RuntimeContext,
    CampaignEventKind,
    CampaignHealthObservation,
    CampaignSpec,
    CampaignStatus,
    CampaignValidationError,
    FailureDescriptor,
    compose_agent4_runtime,
)


BASE_TIME = datetime(2026, 7, 31, 9, 0, tzinfo=timezone.utc)


class _CompositionClock:
    def __init__(self, value: datetime = BASE_TIME) -> None:
        self.value = value

    def now(self) -> datetime:
        return self.value


class _CompositionExecutor:
    def __init__(self) -> None:
        self.dispatched: list[tuple[str, int]] = []
        self.signals: list[tuple[str, str]] = []

    def dispatch(self, spec, state) -> str:
        self.dispatched.append((spec.campaign_id, state.attempt))
        return f"runtime:{spec.campaign_id}:{state.attempt}"

    def signal(self, campaign_id: str, command: str) -> None:
        self.signals.append((campaign_id, command))


class Agent4RuntimeCompositionTests(unittest.TestCase):
    def _compose(
        self,
        root: Path | str,
        *,
        clock: _CompositionClock | None = None,
        executor: _CompositionExecutor | None = None,
    ) -> tuple[
        Agent4RuntimeContext,
        _CompositionClock,
        _CompositionExecutor,
    ]:
        runtime_clock = clock if clock is not None else _CompositionClock()
        runtime_executor = (
            executor if executor is not None else _CompositionExecutor()
        )
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
    def _spec(
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

    def test_composition_is_dormant_and_shares_one_object_graph(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "runtime"
            context, _, executor = self._compose(root)

            self.assertFalse(root.exists())
            self.assertEqual(context.paths.root, root)
            self.assertEqual(context.paths.campaigns, root / "campaigns")
            self.assertEqual(context.paths.checkpoints, root / "checkpoints")
            self.assertEqual(context.paths.timeline, root / "timeline")
            self.assertEqual(
                context.paths.delivery_cursors,
                root / "delivery-cursors",
            )
            self.assertEqual(context.repository.list(), ())
            self.assertEqual(context.timeline.list("unknown"), ())
            self.assertIsNone(
                context.delivery_cursor_store.get("consumer", "unknown")
            )
            self.assertEqual(context.scheduler.queued_count, 0)
            self.assertEqual(executor.dispatched, [])
            self.assertIs(context.scheduler._repository, context.repository)
            self.assertIs(context.scheduler._events, context.event_recorder)
            self.assertIs(context.scheduler._queue, context.queue)
            self.assertIs(context.checkpoints._events, context.event_recorder)
            self.assertIs(context.failures._events, context.event_recorder)
            self.assertIs(
                context.health_fail_closed._events,
                context.event_recorder,
            )
            self.assertIs(context.reconciliation._repository, context.repository)
            self.assertIs(context.reconciliation._timeline, context.timeline)
            self.assertIs(context.projections._repository, context.repository)
            self.assertIs(context.projections._reconciler, context.reconciliation)
            self.assertIs(context.delivery._timeline, context.timeline)
            self.assertIs(
                context.delivery._cursors,
                context.delivery_cursor_store,
            )
            self.assertIs(
                context.guarded_delivery._flights,
                context.delivery_flights,
            )
            self.assertIs(context.batches._delivery, context.delivery)
            self.assertIs(context.batches._flights, context.delivery_flights)
            self.assertIs(context.query._timeline, context.timeline)

    def test_lifecycle_checkpoint_query_and_batch_share_timeline(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            context, clock, executor = self._compose(
                Path(directory) / "runtime"
            )
            context.scheduler.submit(self._spec())
            dispatched = context.scheduler.dispatch_ready()

            self.assertIsNotNone(dispatched)
            assert dispatched is not None
            self.assertEqual(
                dispatched.runtime_reference,
                "runtime:campaign-composed:1",
            )
            self.assertEqual(executor.dispatched, [("campaign-composed", 1)])
            context.checkpoints.checkpoint(
                "campaign-composed",
                "checkpoint-1",
                {"progress": 50},
            )

            entries = context.timeline.list("campaign-composed")
            self.assertEqual(
                [entry.event.kind for entry in entries],
                [
                    CampaignEventKind.CREATED,
                    CampaignEventKind.STARTED,
                    CampaignEventKind.CHECKPOINTED,
                ],
            )
            page = context.query.page("campaign-composed", limit=10)
            self.assertEqual(page.entries, entries)

            delivered: list[int] = []
            batch = context.batches.deliver_batch(
                "operator-a",
                "campaign-composed",
                lambda entry: delivered.append(entry.event.sequence),
                acknowledged_at=clock.now(),
                max_entries=10,
            )
            self.assertEqual(delivered, [1, 2, 3])
            self.assertEqual(batch.delivered_count, 3)
            self.assertTrue(batch.completed)
            self.assertEqual(batch.cursor.sequence, 3)

    def test_failure_handling_reuses_queue_timeline_and_resource_release(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            context, clock, _ = self._compose(Path(directory) / "runtime")
            context.scheduler.submit(self._spec(max_attempts=2))
            context.scheduler.dispatch_ready()

            result = context.failures.handle_failure(
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
                context.resources.for_campaign(
                    "campaign-composed",
                    now=clock.now(),
                )
            )
            latest = context.timeline.latest("campaign-composed")
            self.assertIsNotNone(latest)
            assert latest is not None
            self.assertEqual(
                latest.event.kind,
                CampaignEventKind.RETRY_SCHEDULED,
            )

    def test_restart_requires_explicit_recovery_and_continues_sequence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "runtime"
            first, _, _ = self._compose(root)
            first.scheduler.submit(
                self._spec(
                    campaign_id="campaign-restart",
                    scheduled_for=BASE_TIME + timedelta(hours=1),
                )
            )
            del first
            gc.collect()

            second, _, _ = self._compose(root)
            self.assertEqual(second.scheduler.queued_count, 0)
            before = second.timeline.latest("campaign-restart")
            self.assertIsNotNone(before)
            assert before is not None
            self.assertEqual(before.event.sequence, 2)

            report = second.recover()

            self.assertEqual(report.scanned, 1)
            self.assertEqual(report.requeued, 1)
            self.assertEqual(second.scheduler.queued_count, 1)
            after = second.timeline.latest("campaign-restart")
            self.assertIsNotNone(after)
            assert after is not None
            self.assertEqual(after.event.sequence, 3)

    def test_second_live_writer_context_for_same_root_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "runtime"
            first, _, _ = self._compose(root)

            with self.assertRaises(CampaignValidationError):
                self._compose(root / ".." / "runtime")

            self.assertFalse(root.exists())
            self.assertIsNotNone(first.repository)

    def test_health_intervention_is_built_and_executed_explicitly(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            context, clock, _ = self._compose(Path(directory) / "runtime")
            context.scheduler.submit(self._spec())
            context.scheduler.dispatch_ready()
            coordinator = context.health_intervention()

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
                context.resources.for_campaign(
                    "campaign-composed",
                    now=clock.now(),
                )
            )
            latest = context.timeline.latest("campaign-composed")
            self.assertIsNotNone(latest)
            assert latest is not None
            self.assertEqual(latest.event.kind, CampaignEventKind.FAILED)

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
                    executor=_CompositionExecutor(),
                    resource_capacities={"gpu": 1},
                    resource_resolver=None,
                )
            self.assertFalse(root.exists())
