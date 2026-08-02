#!/usr/bin/env python3
"""Regression contract for ADR-A4-008 resource-barrier placement."""

from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from app.agent4.campaign_queue import CampaignQueue
from app.agent4.domain import (
    CampaignRecord,
    CampaignSpec,
    CampaignState,
    CampaignStatus,
)
from app.agent4.event_bus import InMemoryCampaignEventBus
from app.agent4.handoff import (
    CampaignDispatchAcknowledgement,
    CampaignDispatchOutcome,
    CampaignDispatchRequest,
    CampaignSignalAcknowledgement,
    CampaignSignalRequest,
)
from app.agent4.handoff_runtime import (
    RESOURCE_RECONCILIATION_BLOCKED_MESSAGE,
    CampaignResourceReconciliationBlockedError,
    ResourceAwareCampaignHandoffSchedulerService,
)
from app.agent4.repository import JsonCampaignRepository
from app.agent4.resources import InMemoryResourceLeaseManager


NOW = datetime(2026, 8, 2, 15, 0, tzinfo=timezone.utc)
TTL = timedelta(minutes=5)


class FixedClock:
    def now(self) -> datetime:
        return NOW


class RecordingExecutor:
    def __init__(self) -> None:
        self.dispatches: list[CampaignDispatchRequest] = []

    def dispatch(
        self,
        request: CampaignDispatchRequest,
    ) -> CampaignDispatchAcknowledgement:
        self.dispatches.append(request)
        return CampaignDispatchAcknowledgement(
            dispatch_id=request.dispatch_id,
            runtime_reference="runtime:unexpected",
            evidence_pointer="evidence:unexpected",
        )

    def signal(
        self,
        request: CampaignSignalRequest,
    ) -> CampaignSignalAcknowledgement:
        raise AssertionError(f"unexpected signal {request.signal_id}")

    def query_outcome(self, dispatch_id: str) -> CampaignDispatchOutcome:
        raise AssertionError(f"unexpected outcome query {dispatch_id}")


class BarrierPlacementTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.repository = JsonCampaignRepository(self.root / "campaigns")
        self.queue = CampaignQueue()
        self.executor = RecordingExecutor()
        self.leases = InMemoryResourceLeaseManager({"gpu": 1})
        self.service = ResourceAwareCampaignHandoffSchedulerService(
            repository=self.repository,
            executor=self.executor,
            events=InMemoryCampaignEventBus(),
            clock=FixedClock(),
            queue=self.queue,
            resource_leases=self.leases,
            resource_resolver=lambda spec: spec.parameters.get("resources", {}),
            resource_lease_ttl=TTL,
        )

    def tearDown(self) -> None:
        self.temp.cleanup()

    @staticmethod
    def spec(campaign_id: str, *, resources: dict[str, int]) -> CampaignSpec:
        return CampaignSpec(
            campaign_id=campaign_id,
            name=campaign_id,
            workflow="agent3.write-pilot",
            created_at=NOW,
            max_attempts=3,
            parameters={"resources": resources},
        )

    def test_existing_marker_blocks_before_any_lease_acquire_attempt(self) -> None:
        marker_spec = self.spec("marker", resources={})
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
        self.service.submit(self.spec("candidate", resources={"gpu": 1}))
        before = self.repository.get("candidate")

        with patch.object(
            self.leases,
            "try_acquire",
            wraps=self.leases.try_acquire,
        ) as acquire_spy:
            with self.assertRaisesRegex(
                CampaignResourceReconciliationBlockedError,
                RESOURCE_RECONCILIATION_BLOCKED_MESSAGE,
            ):
                self.service.dispatch_ready()

        acquire_spy.assert_not_called()
        self.assertEqual(self.service.queued_count, 1)
        self.assertEqual(self.repository.get("candidate"), before)
        self.assertIsNone(self.leases.for_campaign("candidate", now=NOW))
        self.assertEqual(self.executor.dispatches, [])


if __name__ == "__main__":
    unittest.main()
