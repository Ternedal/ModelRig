#!/usr/bin/env python3
"""A4-07 cross-process timeline lock contract tests."""

from __future__ import annotations

import hashlib
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.agent4 import CampaignEventKind
from app.agent4.timeline import CampaignEvidence, CampaignEvidenceArtifact
from app.agent4.timeline_lock import (
    CampaignTimelineLockTimeout,
    FileCampaignTimelineLockManager,
    ProcessSafeCampaignTimeline,
)


BASE_TIME = datetime(2026, 7, 30, 21, 0, tzinfo=timezone.utc)


class Agent4TimelineLockTests(unittest.TestCase):
    def evidence(self, index: int) -> CampaignEvidence:
        identifier = f"proof-{index}"
        return CampaignEvidence(
            evidence_id=identifier,
            campaign_id="campaign-lock",
            category="concurrency-proof",
            source="test",
            recorded_at=BASE_TIME + timedelta(seconds=index),
            payload={"index": index},
            artifacts=(
                CampaignEvidenceArtifact(
                    uri=f"file:///evidence/{identifier}.json",
                    sha256=hashlib.sha256(identifier.encode("utf-8")).hexdigest(),
                    size_bytes=index,
                    media_type="application/json",
                ),
            ),
        )

    def test_construction_is_dormant_until_first_explicit_operation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "timeline"
            timeline = ProcessSafeCampaignTimeline(root)

            self.assertFalse(root.exists())
            self.assertFalse(timeline.lock_manager.lock_directory.exists())

            timeline.record(
                "campaign-lock",
                CampaignEventKind.CREATED,
                occurred_at=BASE_TIME,
            )

            self.assertTrue(root.is_dir())
            self.assertTrue(timeline.lock_manager.lock_directory.is_dir())

    def test_same_campaign_times_out_and_release_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            first = FileCampaignTimelineLockManager(
                Path(directory) / "timeline",
                timeout_seconds=0.2,
                poll_interval_seconds=0.01,
            )
            second = FileCampaignTimelineLockManager(
                Path(directory) / "timeline",
                timeout_seconds=0.05,
                poll_interval_seconds=0.01,
            )
            lease = first.acquire("campaign-lock")
            try:
                with self.assertRaises(CampaignTimelineLockTimeout):
                    second.acquire("campaign-lock")
            finally:
                lease.release()
                lease.release()

            with second.acquire("campaign-lock") as replacement:
                self.assertFalse(replacement.released)
            self.assertTrue(replacement.released)

    def test_different_campaigns_have_independent_writer_locks(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            manager = FileCampaignTimelineLockManager(Path(directory) / "timeline")
            with manager.acquire("campaign-a") as first:
                with manager.acquire("campaign-b") as second:
                    self.assertNotEqual(first.path, second.path)
                    self.assertFalse(first.released)
                    self.assertFalse(second.released)

    def test_two_store_instances_serialize_same_campaign_appends(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "timeline"
            stores = (
                ProcessSafeCampaignTimeline(root),
                ProcessSafeCampaignTimeline(root),
            )

            def append(index: int) -> int:
                entry = stores[index % 2].append_evidence(self.evidence(index))
                return entry.timeline_sequence

            with ThreadPoolExecutor(max_workers=8) as executor:
                sequences = sorted(executor.map(append, range(1, 17)))

            self.assertEqual(sequences, list(range(1, 17)))
            self.assertEqual(len(stores[0].verify("campaign-lock")), 16)

    def test_event_is_durable_before_callback_and_handler_failure_releases_lock(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "timeline"
            timeline = ProcessSafeCampaignTimeline(root)
            observed: list[int] = []

            def handler(event) -> None:
                observed.append(timeline.latest_event_sequence(event.campaign_id))
                raise RuntimeError("handler failed")

            timeline.subscribe(handler)
            with self.assertRaisesRegex(RuntimeError, "handler failed"):
                timeline.record(
                    "campaign-lock",
                    CampaignEventKind.CREATED,
                    occurred_at=BASE_TIME,
                )

            self.assertEqual(observed, [1])
            self.assertEqual(timeline.latest_event_sequence("campaign-lock"), 1)

            replacement = ProcessSafeCampaignTimeline(root)
            second = replacement.record(
                "campaign-lock",
                CampaignEventKind.STARTED,
                occurred_at=BASE_TIME + timedelta(seconds=1),
            )
            self.assertEqual(second.sequence, 2)

    def test_invalid_lock_timing_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "timeline"
            for timeout, poll in ((0, 0.01), (True, 0.01), (0.01, 0.02)):
                with self.assertRaises(Exception):
                    FileCampaignTimelineLockManager(
                        root,
                        timeout_seconds=timeout,
                        poll_interval_seconds=poll,
                    )


if __name__ == "__main__":
    unittest.main()
