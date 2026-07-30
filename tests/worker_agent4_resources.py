#!/usr/bin/env python3
"""Resource lease and concurrency-limit coverage for Agent 4."""

from __future__ import annotations

import tempfile
import threading
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.agent4.resources import (
    InMemoryResourceLeaseManager,
    ResourceLeaseConflictError,
    ResourceLeaseNotFoundError,
)
from app.agent4 import (
    CampaignPriority,
    CampaignSpec,
    CampaignStatus,
    CampaignValidationError,
    InMemoryCampaignEventBus,
    JsonCampaignRepository,
)
from app.agent4.resource_admission import (
    CampaignResourceBlockedError,
    ResourceAwareCampaignSchedulerService,
)


NOW = datetime(2026, 7, 29, 20, 0, tzinfo=timezone.utc)
TTL = timedelta(minutes=5)


class ResourceLeaseManagerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.manager = InMemoryResourceLeaseManager({"gpu": 2, "browser": 3})

    def test_acquisition_is_atomic_and_tracks_availability(self) -> None:
        lease = self.manager.try_acquire(
            "campaign-1",
            {"gpu": 1, "browser": 2},
            now=NOW,
            ttl=TTL,
        )

        self.assertIsNotNone(lease)
        snapshot = self.manager.snapshot(now=NOW)
        self.assertEqual(dict(snapshot.used), {"browser": 2, "gpu": 1})
        self.assertEqual(dict(snapshot.available), {"browser": 1, "gpu": 1})
        self.assertEqual(snapshot.leases, (lease,))

    def test_contention_returns_none_without_partial_reservation(self) -> None:
        self.manager.try_acquire("owner", {"gpu": 2}, now=NOW, ttl=TTL)

        blocked = self.manager.try_acquire(
            "blocked",
            {"gpu": 1, "browser": 3},
            now=NOW,
            ttl=TTL,
        )

        self.assertIsNone(blocked)
        snapshot = self.manager.snapshot(now=NOW)
        self.assertEqual(dict(snapshot.used), {"gpu": 2})
        self.assertEqual(dict(snapshot.available), {"browser": 3, "gpu": 0})

    def test_expired_lease_is_reclaimed_before_admission(self) -> None:
        first = self.manager.try_acquire(
            "campaign-1",
            {"gpu": 2},
            now=NOW,
            ttl=timedelta(seconds=10),
        )
        later = NOW + timedelta(seconds=10)

        second = self.manager.try_acquire(
            "campaign-2",
            {"gpu": 2},
            now=later,
            ttl=TTL,
        )

        self.assertIsNotNone(second)
        self.assertIsNone(self.manager.get(first.lease_id, now=later))
        self.assertEqual(self.manager.for_campaign("campaign-2", now=later), second)

    def test_same_request_is_idempotent_but_changed_request_conflicts(self) -> None:
        first = self.manager.try_acquire(
            "campaign-1", {"gpu": 1}, now=NOW, ttl=TTL
        )
        repeated = self.manager.try_acquire(
            "campaign-1", {"gpu": 1}, now=NOW, ttl=TTL
        )
        self.assertIs(repeated, first)

        with self.assertRaises(ResourceLeaseConflictError):
            self.manager.try_acquire(
                "campaign-1",
                {"gpu": 2},
                now=NOW,
                ttl=TTL,
            )

    def test_renew_increments_revision_without_changing_ownership(self) -> None:
        lease = self.manager.try_acquire(
            "campaign-1", {"gpu": 1}, now=NOW, ttl=TTL
        )
        renewed = self.manager.renew(
            lease.lease_id,
            now=NOW + timedelta(minutes=1),
            ttl=TTL,
        )

        self.assertEqual(renewed.revision, 2)
        self.assertEqual(renewed.acquired_at, NOW)
        self.assertEqual(renewed.expires_at, NOW + timedelta(minutes=6))
        self.assertEqual(
            self.manager.for_campaign("campaign-1", now=NOW),
            renewed,
        )

    def test_release_by_lease_or_campaign_is_idempotent(self) -> None:
        lease = self.manager.try_acquire(
            "campaign-1", {"gpu": 1}, now=NOW, ttl=TTL
        )
        self.assertTrue(self.manager.release(lease.lease_id))
        self.assertFalse(self.manager.release(lease.lease_id))

        self.manager.try_acquire("campaign-2", {"gpu": 1}, now=NOW, ttl=TTL)
        self.assertTrue(self.manager.release_campaign("campaign-2"))
        self.assertFalse(self.manager.release_campaign("campaign-2"))

    def test_invalid_and_impossible_requests_fail_closed(self) -> None:
        cases = [
            ({}, CampaignValidationError),
            ({"GPU": 3}, CampaignValidationError),
            ({"unknown": 1}, CampaignValidationError),
            ({"gpu": 0}, CampaignValidationError),
            ({"gpu": True}, CampaignValidationError),
        ]
        for resources, expected in cases:
            with self.subTest(resources=resources):
                with self.assertRaises(expected):
                    self.manager.try_acquire(
                        "campaign-1",
                        resources,
                        now=NOW,
                        ttl=TTL,
                    )
        with self.assertRaises(CampaignValidationError):
            self.manager.try_acquire(
                "campaign-1",
                {"gpu": 1},
                now=NOW.replace(tzinfo=None),
                ttl=TTL,
            )
        with self.assertRaises(CampaignValidationError):
            self.manager.try_acquire(
                "campaign-1",
                {"gpu": 1},
                now=NOW,
                ttl=timedelta(0),
            )

    def test_expired_lease_cannot_be_renewed(self) -> None:
        lease = self.manager.try_acquire(
            "campaign-1",
            {"gpu": 1},
            now=NOW,
            ttl=timedelta(seconds=1),
        )
        with self.assertRaises(ResourceLeaseNotFoundError):
            self.manager.renew(
                lease.lease_id,
                now=NOW + timedelta(seconds=1),
                ttl=TTL,
            )

    def test_concurrent_capacity_one_admits_exactly_one_campaign(self) -> None:
        manager = InMemoryResourceLeaseManager({"gpu": 1})
        barrier = threading.Barrier(16)
        results: list[object] = []
        lock = threading.Lock()

        def acquire(index: int) -> None:
            barrier.wait()
            result = manager.try_acquire(
                f"campaign-{index}",
                {"gpu": 1},
                now=NOW,
                ttl=TTL,
            )
            with lock:
                results.append(result)

        threads = [threading.Thread(target=acquire, args=(i,)) for i in range(16)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        self.assertEqual(sum(result is not None for result in results), 1)
        self.assertEqual(dict(manager.snapshot(now=NOW).used), {"gpu": 1})


class MutableClock:
    def __init__(self) -> None:
        self.value = NOW

    def now(self) -> datetime:
        return self.value


class RecordingExecutor:
    def __init__(self) -> None:
        self.dispatches: list[str] = []
        self.signals: list[tuple[str, str]] = []
        self.dispatch_error: Exception | None = None
        self.signal_error: Exception | None = None

    def dispatch(self, spec, state) -> str:
        self.dispatches.append(spec.campaign_id)
        if self.dispatch_error is not None:
            raise self.dispatch_error
        return f"runtime:{spec.campaign_id}"

    def signal(self, campaign_id: str, command: str) -> None:
        self.signals.append((campaign_id, command))
        if self.signal_error is not None:
            raise self.signal_error


class ResourceAwareSchedulerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.repository = JsonCampaignRepository(Path(self.directory.name))
        self.executor = RecordingExecutor()
        self.events = InMemoryCampaignEventBus()
        self.clock = MutableClock()
        self.leases = InMemoryResourceLeaseManager({"gpu": 1, "browser": 1})
        self.service = ResourceAwareCampaignSchedulerService(
            repository=self.repository,
            executor=self.executor,
            events=self.events,
            clock=self.clock,
            resource_leases=self.leases,
            resource_resolver=lambda spec: spec.parameters.get("resources", {}),
            resource_lease_ttl=TTL,
        )

    def tearDown(self) -> None:
        self.directory.cleanup()

    def spec(
        self,
        campaign_id: str,
        *,
        resources: dict[str, int] | None = None,
        priority: CampaignPriority = CampaignPriority.NORMAL,
    ) -> CampaignSpec:
        return CampaignSpec(
            campaign_id=campaign_id,
            name=campaign_id,
            workflow="agent3.write-pilot",
            created_at=NOW,
            priority=priority,
            parameters={"resources": resources or {}},
        )

    def test_blocked_high_priority_work_does_not_block_admissible_work(self) -> None:
        holder = self.leases.try_acquire(
            "external", {"gpu": 1}, now=NOW, ttl=TTL
        )
        self.service.submit(
            self.spec(
                "high-gpu",
                resources={"gpu": 1},
                priority=CampaignPriority.CRITICAL,
            )
        )
        self.service.submit(
            self.spec("normal-browser", resources={"browser": 1})
        )

        first = self.service.dispatch_ready()

        self.assertEqual(first.record.spec.campaign_id, "normal-browser")
        self.assertEqual(self.service.queued_count, 1)
        self.assertEqual(
            self.service.get("high-gpu").state.status,
            CampaignStatus.QUEUED,
        )
        self.service.complete("normal-browser", succeeded=True)
        self.leases.release(holder.lease_id)
        self.assertEqual(
            self.service.dispatch_ready().record.spec.campaign_id,
            "high-gpu",
        )

    def test_dispatch_holds_lease_and_records_identity(self) -> None:
        self.service.submit(self.spec("campaign-1", resources={"gpu": 1}))

        result = self.service.dispatch_ready()
        lease = self.leases.for_campaign("campaign-1", now=NOW)

        self.assertIsNotNone(lease)
        self.assertEqual(result.resource_lease_id, lease.lease_id)
        started = self.events.history("campaign-1")[-1]
        self.assertEqual(started.payload["resource_lease_id"], lease.lease_id)
        self.assertEqual(dict(started.payload["resources"]), {"gpu": 1})

    def test_dispatch_failure_releases_resources(self) -> None:
        self.executor.dispatch_error = RuntimeError("agent3 unavailable")
        self.service.submit(self.spec("campaign-1", resources={"gpu": 1}))

        result = self.service.dispatch_ready()

        self.assertFalse(result.succeeded)
        self.assertEqual(result.record.state.status, CampaignStatus.FAILED)
        self.assertIsNone(self.leases.for_campaign("campaign-1", now=NOW))

    def test_pause_releases_and_resume_reacquires_without_new_attempt(self) -> None:
        self.service.submit(self.spec("campaign-1", resources={"gpu": 1}))
        running = self.service.dispatch_ready().record
        self.service.request_pause("campaign-1")
        paused = self.service.mark_paused("campaign-1")

        self.assertIsNone(self.leases.for_campaign("campaign-1", now=NOW))
        resumed = self.service.resume("campaign-1")
        self.assertEqual(resumed.state.attempt, running.state.attempt)
        self.assertEqual(paused.state.status, CampaignStatus.PAUSED)
        self.assertIsNotNone(self.leases.for_campaign("campaign-1", now=NOW))

    def test_blocked_resume_stays_paused(self) -> None:
        self.service.submit(self.spec("campaign-1", resources={"gpu": 1}))
        self.service.dispatch_ready()
        self.service.request_pause("campaign-1")
        self.service.mark_paused("campaign-1")
        self.leases.try_acquire("external", {"gpu": 1}, now=NOW, ttl=TTL)

        with self.assertRaises(CampaignResourceBlockedError):
            self.service.resume("campaign-1")

        self.assertEqual(
            self.service.get("campaign-1").state.status,
            CampaignStatus.PAUSED,
        )

    def test_completion_and_cancel_ack_release_resources(self) -> None:
        self.service.submit(self.spec("complete-me", resources={"gpu": 1}))
        self.service.dispatch_ready()
        self.service.complete("complete-me", succeeded=True)
        self.assertIsNone(self.leases.for_campaign("complete-me", now=NOW))

        self.service.submit(self.spec("cancel-me", resources={"gpu": 1}))
        self.service.dispatch_ready()
        self.service.request_cancel("cancel-me")
        self.service.mark_cancelled("cancel-me")
        self.assertIsNone(self.leases.for_campaign("cancel-me", now=NOW))

    def test_renew_extends_active_lease(self) -> None:
        self.service.submit(self.spec("campaign-1", resources={"gpu": 1}))
        self.service.dispatch_ready()
        self.clock.value = NOW + timedelta(minutes=1)

        renewed = self.service.renew_resources("campaign-1")

        self.assertEqual(renewed.revision, 2)
        self.assertEqual(renewed.expires_at, self.clock.value + TTL)


if __name__ == "__main__":
    unittest.main()
