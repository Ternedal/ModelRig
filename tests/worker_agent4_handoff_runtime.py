#!/usr/bin/env python3
"""ADR-A4-008 Slice 3 behavioral and crash-boundary contracts."""

from __future__ import annotations

import tempfile
import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from app.agent4.campaign_queue import CampaignQueue
from app.agent4.domain import (
    CampaignRecord,
    CampaignSpec,
    CampaignState,
    CampaignStatus,
    CampaignValidationError,
)
from app.agent4.event_bus import InMemoryCampaignEventBus
from app.agent4.handoff import (
    CampaignDispatchAcknowledgement,
    CampaignDispatchOutcome,
    CampaignDispatchRequest,
    CampaignSignalAcknowledgement,
    CampaignSignalRequest,
    DispatchOutcomeKind,
)
from app.agent4.handoff_persistence import CampaignHandoffPhase
from app.agent4.handoff_runtime import (
    RESOURCE_RECONCILIATION_BLOCKED_MESSAGE,
    CampaignHandoffRecoveryService,
    CampaignHandoffSchedulerService,
    CampaignHandoffUncertainError,
    CampaignResourceReconciliationBlockedError,
    HandoffRecoveryAction,
    ResourceAwareCampaignHandoffSchedulerService,
    ResourceReconciliationResolutionReason,
)
from app.agent4.repository import CampaignRepositoryError, JsonCampaignRepository
from app.agent4.resources import InMemoryResourceLeaseManager
from app.agent4.service import CampaignConflictError


NOW = datetime(2026, 8, 2, 13, 0, tzinfo=timezone.utc)
TTL = timedelta(minutes=5)


class MutableClock:
    def __init__(self, value: datetime = NOW) -> None:
        self.value = value

    def now(self) -> datetime:
        return self.value


class RecordingHandoffExecutor:
    def __init__(self) -> None:
        self.dispatches: list[CampaignDispatchRequest] = []
        self.signals: list[CampaignSignalRequest] = []
        self.queries: list[str] = []
        self.dispatch_error: Exception | None = None
        self.signal_error: Exception | None = None
        self.outcomes: dict[str, CampaignDispatchOutcome | Exception] = {}

    def dispatch(
        self,
        request: CampaignDispatchRequest,
    ) -> CampaignDispatchAcknowledgement:
        self.dispatches.append(request)
        if self.dispatch_error is not None:
            raise self.dispatch_error
        return CampaignDispatchAcknowledgement(
            dispatch_id=request.dispatch_id,
            runtime_reference=f"runtime:{request.attempt}",
            evidence_pointer=f"evidence:dispatch:{request.attempt}",
        )

    def signal(
        self,
        request: CampaignSignalRequest,
    ) -> CampaignSignalAcknowledgement:
        self.signals.append(request)
        if self.signal_error is not None:
            raise self.signal_error
        return CampaignSignalAcknowledgement(
            signal_id=request.signal_id,
            evidence_pointer=f"evidence:signal:{request.signal_type.value}",
        )

    def query_outcome(self, dispatch_id: str) -> CampaignDispatchOutcome:
        self.queries.append(dispatch_id)
        value = self.outcomes[dispatch_id]
        if isinstance(value, Exception):
            raise value
        return value


class Slice3Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.repository = JsonCampaignRepository(self.root / "campaigns")
        self.events = InMemoryCampaignEventBus()
        self.clock = MutableClock()
        self.executor = RecordingHandoffExecutor()
        self.queue = CampaignQueue()

    def tearDown(self) -> None:
        self.temp.cleanup()

    @staticmethod
    def spec(
        campaign_id: str = "campaign-a",
        *,
        resources: dict[str, int] | None = None,
    ) -> CampaignSpec:
        return CampaignSpec(
            campaign_id=campaign_id,
            name=campaign_id,
            workflow="agent3.write-pilot",
            created_at=NOW,
            max_attempts=3,
            parameters={"resources": resources or {}},
        )

    def ordinary(
        self,
        *,
        queue: CampaignQueue | None = None,
    ) -> CampaignHandoffSchedulerService:
        return CampaignHandoffSchedulerService(
            repository=self.repository,
            executor=self.executor,
            events=self.events,
            clock=self.clock,
            queue=queue if queue is not None else self.queue,
        )

    def resource_aware(
        self,
    ) -> tuple[
        ResourceAwareCampaignHandoffSchedulerService,
        InMemoryResourceLeaseManager,
    ]:
        leases = InMemoryResourceLeaseManager({"gpu": 1})
        return (
            ResourceAwareCampaignHandoffSchedulerService(
                repository=self.repository,
                executor=self.executor,
                events=self.events,
                clock=self.clock,
                queue=self.queue,
                resource_leases=leases,
                resource_resolver=lambda spec: spec.parameters.get("resources", {}),
                resource_lease_ttl=TTL,
            ),
            leases,
        )

    def unresolved_dispatch(self) -> tuple[CampaignRecord, str]:
        self.executor.dispatch_error = TimeoutError("transport disconnected")
        service = self.ordinary()
        service.submit(self.spec())
        result = service.dispatch_ready()
        self.assertIsNotNone(result)
        intent = self.repository.pending_handoffs("campaign-a")[0]
        return result.record, intent.intent_id

    def recovery(self, *, queue: CampaignQueue | None = None):
        return CampaignHandoffRecoveryService(
            repository=self.repository,
            queue=queue if queue is not None else CampaignQueue(),
            events=self.events,
            clock=self.clock,
            executor=self.executor,
        ).recover()

    def test_transport_exception_is_requested_and_nonterminal(self) -> None:
        service, leases = self.resource_aware()
        self.executor.dispatch_error = TimeoutError("connection reset")
        service.submit(self.spec(resources={"gpu": 1}))

        result = service.dispatch_ready()

        self.assertFalse(result.succeeded)
        self.assertEqual(result.record.state.status, CampaignStatus.RUNNING)
        self.assertIsNone(result.record.state.last_error)
        self.assertIn("unresolved handoff", result.dispatch_error)
        intent = self.repository.pending_handoffs("campaign-a")[0]
        self.assertEqual(intent.phase, CampaignHandoffPhase.REQUESTED)
        self.assertIsNotNone(leases.for_campaign("campaign-a", now=NOW))

    def test_requested_state_and_intent_share_replace_boundary(self) -> None:
        service = self.ordinary()
        service.submit(self.spec())
        before = self.repository.get("campaign-a")

        with patch("app.agent4.repository.os.replace", side_effect=OSError("crash")):
            with self.assertRaises(CampaignRepositoryError):
                service.dispatch_ready()

        self.assertEqual(self.repository.get("campaign-a"), before)
        self.assertEqual(self.repository.pending_handoffs("campaign-a"), ())
        self.assertEqual(service.queued_count, 1)
        self.assertEqual(self.executor.dispatches, [])

    def test_success_acknowledges_typed_dispatch(self) -> None:
        service = self.ordinary()
        service.submit(self.spec())

        result = service.dispatch_ready()

        self.assertTrue(result.succeeded)
        intent = self.repository.pending_handoffs("campaign-a")[0]
        self.assertEqual(intent.phase, CampaignHandoffPhase.ACKNOWLEDGED)
        kinds = {
            projection.kind.value
            for projection in self.repository.pending_projections("campaign-a")
        }
        self.assertIn("dispatch_requested", kinds)
        self.assertIn("dispatch_confirmed", kinds)

    def test_signal_transport_error_never_becomes_failed(self) -> None:
        service = self.ordinary()
        service.submit(self.spec())
        service.dispatch_ready()
        self.executor.signal_error = ConnectionError("unknown signal outcome")

        with self.assertRaises(CampaignHandoffUncertainError):
            service.request_pause("campaign-a")

        current = self.repository.get("campaign-a")
        self.assertEqual(current.state.status, CampaignStatus.PAUSING)
        self.assertIsNone(current.state.last_error)

    def test_not_dispatched_is_ready_without_auto_redispatch(self) -> None:
        record, dispatch_id = self.unresolved_dispatch()
        self.executor.dispatch_error = None
        self.executor.outcomes[dispatch_id] = CampaignDispatchOutcome(
            dispatch_id=dispatch_id,
            kind=DispatchOutcomeKind.NOT_DISPATCHED,
            evidence_pointer="evidence:tombstone",
            resources_released=True,
        )
        dispatch_count = len(self.executor.dispatches)

        report = self.recovery()

        current = self.repository.get(record.spec.campaign_id)
        self.assertEqual(current.state.status, CampaignStatus.QUEUED)
        self.assertEqual(current.state.attempt, 1)
        self.assertFalse(current.state.resource_reconciliation_required)
        self.assertEqual(len(self.executor.dispatches), dispatch_count)
        self.assertEqual(
            report.decisions[0].action,
            HandoffRecoveryAction.NOT_DISPATCHED_READY,
        )

    def test_new_explicit_attempt_after_negative_gets_new_id(self) -> None:
        _, first_id = self.unresolved_dispatch()
        self.executor.dispatch_error = None
        self.executor.outcomes[first_id] = CampaignDispatchOutcome(
            dispatch_id=first_id,
            kind=DispatchOutcomeKind.NOT_DISPATCHED,
            resources_released=True,
        )
        queue = CampaignQueue()
        self.recovery(queue=queue)

        result = self.ordinary(queue=queue).dispatch_ready()

        self.assertTrue(result.succeeded)
        self.assertEqual(result.record.state.attempt, 2)
        self.assertNotEqual(self.executor.dispatches[-1].dispatch_id, first_id)

    def test_accepted_running_and_unknown_follow_marker_rule(self) -> None:
        for kind in (
            DispatchOutcomeKind.ACCEPTED,
            DispatchOutcomeKind.RUNNING,
            DispatchOutcomeKind.UNKNOWN,
        ):
            with self.subTest(kind=kind):
                if self.repository.get("campaign-a") is not None:
                    self.repository.delete("campaign-a")
                self.queue = CampaignQueue()
                self.executor = RecordingHandoffExecutor()
                _, dispatch_id = self.unresolved_dispatch()
                self.executor.outcomes[dispatch_id] = (
                    CampaignDispatchOutcome(dispatch_id=dispatch_id, kind=kind)
                    if kind is DispatchOutcomeKind.UNKNOWN
                    else CampaignDispatchOutcome(
                        dispatch_id=dispatch_id,
                        kind=kind,
                        runtime_reference="runtime:live",
                    )
                )

                self.recovery()

                current = self.repository.get("campaign-a")
                self.assertTrue(current.state.resource_reconciliation_required)
                intent = self.repository.pending_handoffs("campaign-a")[0]
                if kind is DispatchOutcomeKind.UNKNOWN:
                    self.assertTrue(current.state.execution_intervention_required)
                    self.assertEqual(intent.phase, CampaignHandoffPhase.REQUESTED)
                else:
                    self.assertEqual(intent.phase, CampaignHandoffPhase.ACKNOWLEDGED)

    def test_terminal_attestation_never_auto_clears_existing_marker(self) -> None:
        record, dispatch_id = self.unresolved_dispatch()
        self.repository.save(
            CampaignRecord(
                spec=record.spec,
                state=replace(
                    record.state,
                    resource_reconciliation_required=True,
                ),
            )
        )
        self.executor.outcomes[dispatch_id] = CampaignDispatchOutcome(
            dispatch_id=dispatch_id,
            kind=DispatchOutcomeKind.COMPLETED,
            runtime_reference="runtime:done",
            evidence_pointer="evidence:terminal",
            resources_released=True,
        )

        self.recovery()

        current = self.repository.get("campaign-a")
        self.assertEqual(current.state.status, CampaignStatus.SUCCEEDED)
        self.assertTrue(current.state.resource_reconciliation_required)

    def test_barrier_precedes_queue_lease_state_and_dispatch(self) -> None:
        marker_spec = self.spec("marker")
        self.repository.save(
            CampaignRecord(
                spec=marker_spec,
                state=CampaignState(
                    campaign_id="marker",
                    status=CampaignStatus.RUNNING,
                    revision=1,
                    attempt=1,
                    updated_at=NOW,
                    resource_reconciliation_required=True,
                ),
            )
        )
        service, leases = self.resource_aware()
        service.submit(self.spec("candidate", resources={"gpu": 1}))
        before = self.repository.get("candidate")

        with self.assertRaisesRegex(
            CampaignResourceReconciliationBlockedError,
            RESOURCE_RECONCILIATION_BLOCKED_MESSAGE,
        ):
            service.dispatch_ready()

        self.assertEqual(service.queued_count, 1)
        self.assertEqual(self.repository.get("candidate"), before)
        self.assertIsNone(leases.for_campaign("candidate", now=NOW))
        self.assertEqual(self.executor.dispatches, [])

    def test_marker_after_lease_acquire_releases_and_preserves_candidate(self) -> None:
        service, leases = self.resource_aware()
        service.submit(self.spec("candidate", resources={"gpu": 1}))
        before = self.repository.get("candidate")
        original_try_acquire = service._try_acquire

        def acquire_then_mark(spec, *, now):
            lease = original_try_acquire(spec, now=now)
            self.repository.save(
                CampaignRecord(
                    spec=self.spec("marker"),
                    state=CampaignState(
                        campaign_id="marker",
                        status=CampaignStatus.RUNNING,
                        revision=1,
                        attempt=1,
                        updated_at=NOW,
                        resource_reconciliation_required=True,
                    ),
                )
            )
            return lease

        with patch.object(
            service,
            "_try_acquire",
            side_effect=acquire_then_mark,
        ):
            with self.assertRaisesRegex(
                CampaignResourceReconciliationBlockedError,
                RESOURCE_RECONCILIATION_BLOCKED_MESSAGE,
            ):
                service.dispatch_ready()

        self.assertEqual(service.queued_count, 1)
        self.assertEqual(self.repository.get("candidate"), before)
        self.assertIsNone(leases.for_campaign("candidate", now=NOW))
        self.assertEqual(self.executor.dispatches, [])

    def test_ordinary_scheduler_is_unaffected_by_resource_barrier(self) -> None:
        marker_spec = self.spec("marker")
        self.repository.save(
            CampaignRecord(
                spec=marker_spec,
                state=CampaignState(
                    campaign_id="marker",
                    status=CampaignStatus.RUNNING,
                    revision=1,
                    attempt=1,
                    updated_at=NOW,
                    resource_reconciliation_required=True,
                ),
            )
        )
        service = self.ordinary()
        service.submit(self.spec("ordinary"))

        result = service.dispatch_ready()

        self.assertTrue(result.succeeded)
        self.assertEqual(result.record.spec.campaign_id, "ordinary")

    def test_explicit_resolution_requires_and_clears_one_marker(self) -> None:
        service = self.ordinary()
        service.submit(self.spec())
        with self.assertRaises(CampaignConflictError):
            service.resolve_resource_reconciliation(
                "campaign-a",
                reason=ResourceReconciliationResolutionReason.RESOURCES_RESTORED,
                evidence_pointer="evidence:one",
            )
        current = self.repository.get("campaign-a")
        self.repository.save(
            CampaignRecord(
                spec=current.spec,
                state=replace(
                    current.state,
                    resource_reconciliation_required=True,
                ),
            )
        )
        with self.assertRaises(CampaignValidationError):
            service.resolve_resource_reconciliation(
                "campaign-a",
                reason=ResourceReconciliationResolutionReason.RESOURCES_RESTORED,
                evidence_pointer=" ",
            )

        resolved = service.resolve_resource_reconciliation(
            "campaign-a",
            reason=ResourceReconciliationResolutionReason.CONFLICT_MANUALLY_HANDLED,
            evidence_pointer="evidence:manual:42",
        )
        restarted = JsonCampaignRepository(self.root / "campaigns")

        self.assertFalse(resolved.state.resource_reconciliation_required)
        self.assertFalse(
            restarted.get("campaign-a").state.resource_reconciliation_required
        )
        self.assertEqual(
            restarted.pending_projections("campaign-a")[-1].kind.value,
            "resource_reconciliation_resolved",
        )

    def test_recovery_ack_and_state_are_one_replace(self) -> None:
        before, dispatch_id = self.unresolved_dispatch()
        self.executor.outcomes[dispatch_id] = CampaignDispatchOutcome(
            dispatch_id=dispatch_id,
            kind=DispatchOutcomeKind.RUNNING,
            runtime_reference="runtime:live",
        )

        with patch("app.agent4.repository.os.replace", side_effect=OSError("crash")):
            with self.assertRaises(CampaignRepositoryError):
                self.recovery()

        self.assertEqual(self.repository.get("campaign-a"), before)
        self.assertEqual(
            self.repository.pending_handoffs("campaign-a")[0].phase,
            CampaignHandoffPhase.REQUESTED,
        )


if __name__ == "__main__":
    unittest.main()
