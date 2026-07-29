#!/usr/bin/env python3
"""Resource lease and concurrency-limit coverage for Agent 4."""

from __future__ import annotations

import threading
import unittest
from datetime import datetime, timedelta, timezone

from app.agent4 import CampaignValidationError
from app.agent4.resources import (
    InMemoryResourceLeaseManager,
    ResourceLeaseConflictError,
    ResourceLeaseNotFoundError,
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


if __name__ == "__main__":
    unittest.main()
