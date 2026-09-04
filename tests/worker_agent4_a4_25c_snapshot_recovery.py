#!/usr/bin/env python3
"""A4-25c crash/restart qualification for writer snapshot publication."""

from __future__ import annotations

import sys
import tempfile
import unittest
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "worker"))

from app.agent4.domain import CampaignRecord, CampaignSpec, CampaignState  # noqa: E402
from app.agent4.snapshot_publisher import Agent4OperatorSnapshotPublisher  # noqa: E402
from app.agent4.snapshot_store import (  # noqa: E402
    JsonOperatorSnapshotStore,
    OperatorSnapshotNotFoundError,
)
from app.agent4.timeline import CampaignTimelineVerification  # noqa: E402
from app.agent4.timeline_evidence import CampaignEvidenceVerification  # noqa: E402

UTC = timezone.utc
BASE_TIME = datetime(2026, 8, 10, 18, 30, tzinfo=UTC)


def _record(revision: int) -> CampaignRecord:
    return CampaignRecord(
        spec=CampaignSpec(
            campaign_id="campaign-a",
            name="Campaign A",
            workflow="agent3.write-pilot",
            created_at=BASE_TIME,
        ),
        state=CampaignState(
            campaign_id="campaign-a",
            revision=revision,
            updated_at=BASE_TIME + timedelta(seconds=revision),
        ),
    )


@dataclass(frozen=True, slots=True)
class _Event:
    event_id: str
    sequence: int


@dataclass(frozen=True, slots=True)
class _Entry:
    event: _Event
    entry_hash: str


class _Clock:
    def now(self) -> datetime:
        # Fixed time makes the retried root byte-for-byte/content-id deterministic.
        return BASE_TIME + timedelta(minutes=1)


class _Repository:
    def __init__(self) -> None:
        self.record = _record(0)

    def list(self) -> tuple[CampaignRecord, ...]:
        return (self.record,)

    def get(self, campaign_id: str) -> CampaignRecord | None:
        return self.record if campaign_id == "campaign-a" else None

    def pending_projections(self, campaign_id: str | None = None) -> tuple[object, ...]:
        return ()


class _Timeline:
    def __init__(self) -> None:
        self.entries = (
            _Entry(_Event("event-1", 1), "a" * 64),
        )

    def list(self, campaign_id: str) -> tuple[_Entry, ...]:
        return self.entries if campaign_id == "campaign-a" else ()

    def verify(self, campaign_id: str) -> CampaignTimelineVerification:
        entries = self.list(campaign_id)
        return CampaignTimelineVerification(
            campaign_id=campaign_id,
            entry_count=len(entries),
            evidence_count=0,
            head_hash=entries[-1].entry_hash if entries else None,
        )


class _Evidence:
    def list(self, campaign_id: str) -> tuple[object, ...]:
        return ()

    def verify(self, campaign_id: str) -> CampaignEvidenceVerification:
        return CampaignEvidenceVerification(
            campaign_id=campaign_id,
            record_count=0,
            head_hash=None,
            latest_timeline_head_hash=None,
        )


class SnapshotPublisherRecoveryTests(unittest.TestCase):
    def test_precommit_crash_restart_reuses_orphan_root_and_commits_same_id(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository = _Repository()
            timeline = _Timeline()
            evidence = _Evidence()
            clock = _Clock()
            stable_store = JsonOperatorSnapshotStore(directory, clock=clock.now)
            stable_publisher = Agent4OperatorSnapshotPublisher(
                repository=repository,
                timeline=timeline,
                evidence=evidence,
                snapshots=stable_store,
                clock=clock,
            )
            first = stable_publisher.publish()

            repository.record = _record(1)
            timeline.entries = (
                _Entry(_Event("event-1", 1), "a" * 64),
                _Entry(_Event("event-2", 2), "b" * 64),
            )

            def fail(point: str) -> None:
                if point == "before_current_replace":
                    raise RuntimeError("injected A4-25c pre-commit crash")

            crashing_store = JsonOperatorSnapshotStore(
                directory,
                clock=clock.now,
                failure_injector=fail,
            )
            crashing_publisher = Agent4OperatorSnapshotPublisher(
                repository=repository,
                timeline=timeline,
                evidence=evidence,
                snapshots=crashing_store,
                clock=clock,
            )

            with self.assertRaisesRegex(RuntimeError, "pre-commit crash"):
                crashing_publisher.publish()

            self.assertEqual(stable_store.load_current(), first)
            root_ids = {
                path.stem for path in (Path(directory) / "roots").glob("*.json")
            }
            self.assertEqual(len(root_ids), 2)
            orphan_id = next(root_id for root_id in root_ids if root_id != first.snapshot_id)
            with self.assertRaises(OperatorSnapshotNotFoundError):
                stable_store.load_root(orphan_id, now=clock.now())

            restarted_store = JsonOperatorSnapshotStore(directory, clock=clock.now)
            restarted_publisher = Agent4OperatorSnapshotPublisher(
                repository=repository,
                timeline=timeline,
                evidence=evidence,
                snapshots=restarted_store,
                clock=clock,
            )
            recovered = restarted_publisher.publish()

            self.assertEqual(recovered.snapshot_id, orphan_id)
            self.assertEqual(recovered.root_sequence, 2)
            self.assertEqual(recovered.parent_snapshot_id, first.snapshot_id)
            self.assertEqual(restarted_store.load_current(), recovered)


if __name__ == "__main__":
    unittest.main()
