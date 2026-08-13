#!/usr/bin/env python3
"""A4-25c contracts for caller-driven Agent 4 snapshot publication."""

from __future__ import annotations

import sys
import tempfile
import unittest
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "worker"))

from app.agent4.composition import compose_agent4_runtime  # noqa: E402
from app.agent4.domain import (  # noqa: E402
    CampaignRecord,
    CampaignSpec,
    CampaignState,
)
from app.agent4.snapshot_publisher import (  # noqa: E402
    Agent4OperatorSnapshotPublisher,
    OperatorSnapshotPublicationBlockedError,
    OperatorSnapshotPublicationConflictError,
    OperatorSnapshotPublicationIntegrityError,
)
from app.agent4.snapshot_store import JsonOperatorSnapshotStore  # noqa: E402
from app.agent4.timeline import CampaignTimelineVerification  # noqa: E402
from app.agent4.timeline_evidence import CampaignEvidenceVerification  # noqa: E402

UTC = timezone.utc
BASE_TIME = datetime(2026, 8, 10, 18, 0, tzinfo=UTC)


def _record(campaign_id: str, revision: int = 0) -> CampaignRecord:
    return CampaignRecord(
        spec=CampaignSpec(
            campaign_id=campaign_id,
            name=f"Campaign {campaign_id}",
            workflow="agent3.write-pilot",
            created_at=BASE_TIME,
        ),
        state=CampaignState(
            campaign_id=campaign_id,
            revision=revision,
            updated_at=BASE_TIME + timedelta(seconds=revision),
        ),
    )


@dataclass(frozen=True, slots=True)
class _Event:
    event_id: str
    sequence: int


@dataclass(frozen=True, slots=True)
class _TimelineEntry:
    event: _Event
    entry_hash: str


@dataclass(frozen=True, slots=True)
class _EvidenceRecord:
    sequence: int
    record_hash: str
    timeline_head_hash: str
    related_event_id: str | None = None


class _Clock:
    def __init__(self, now: datetime = BASE_TIME) -> None:
        self.value = now

    def now(self) -> datetime:
        return self.value


class _Repository:
    def __init__(self, records: tuple[CampaignRecord, ...] = ()) -> None:
        self.records = records
        self.pending: tuple[object, ...] = ()
        self.list_calls = 0
        self.list_overrides: dict[int, tuple[CampaignRecord, ...]] = {}
        self.get_overrides: dict[str, CampaignRecord | None] = {}

    def list(self) -> tuple[CampaignRecord, ...]:
        self.list_calls += 1
        return self.list_overrides.get(self.list_calls, self.records)

    def get(self, campaign_id: str) -> CampaignRecord | None:
        if campaign_id in self.get_overrides:
            return self.get_overrides[campaign_id]
        return next(
            (
                record
                for record in self.records
                if record.spec.campaign_id == campaign_id
            ),
            None,
        )

    def pending_projections(self, campaign_id: str | None = None) -> tuple[object, ...]:
        return self.pending


class _TimelineStore:
    def __init__(self) -> None:
        self.entries: dict[str, tuple[_TimelineEntry, ...]] = {}
        self.verify_calls = 0
        self.verify_overrides: dict[int, CampaignTimelineVerification] = {}

    def list(self, campaign_id: str) -> tuple[_TimelineEntry, ...]:
        return self.entries.get(campaign_id, ())

    def verify(self, campaign_id: str) -> CampaignTimelineVerification:
        self.verify_calls += 1
        override = self.verify_overrides.get(self.verify_calls)
        if override is not None:
            return override
        entries = self.list(campaign_id)
        return CampaignTimelineVerification(
            campaign_id=campaign_id,
            entry_count=len(entries),
            evidence_count=0,
            head_hash=entries[-1].entry_hash if entries else None,
        )


class _EvidenceStore:
    def __init__(self) -> None:
        self.records: dict[str, tuple[_EvidenceRecord, ...]] = {}
        self.verify_calls = 0
        self.verify_overrides: dict[int, CampaignEvidenceVerification] = {}

    def list(self, campaign_id: str) -> tuple[_EvidenceRecord, ...]:
        return self.records.get(campaign_id, ())

    def verify(self, campaign_id: str) -> CampaignEvidenceVerification:
        self.verify_calls += 1
        override = self.verify_overrides.get(self.verify_calls)
        if override is not None:
            return override
        records = self.list(campaign_id)
        return CampaignEvidenceVerification(
            campaign_id=campaign_id,
            record_count=len(records),
            head_hash=records[-1].record_hash if records else None,
            latest_timeline_head_hash=(
                records[-1].timeline_head_hash if records else None
            ),
        )


class _NullExecutor:
    def dispatch(self, request):  # pragma: no cover - never called
        raise AssertionError("dispatch must stay dormant")

    def signal(self, request):  # pragma: no cover - never called
        raise AssertionError("signal must stay dormant")

    def query_outcome(self, dispatch_id):  # pragma: no cover - never called
        raise AssertionError("outcome lookup must stay dormant")


def _publisher(
    directory: str,
    repository: _Repository,
    timeline: _TimelineStore,
    evidence: _EvidenceStore,
    clock: _Clock,
) -> tuple[Agent4OperatorSnapshotPublisher, JsonOperatorSnapshotStore]:
    store = JsonOperatorSnapshotStore(directory, clock=clock.now)
    publisher = Agent4OperatorSnapshotPublisher(
        repository=repository,
        timeline=timeline,
        evidence=evidence,
        snapshots=store,
        clock=clock,
    )
    return publisher, store


class SnapshotPublisherTests(unittest.TestCase):
    def test_bootstrap_publishes_empty_genesis_root(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            clock = _Clock()
            publisher, store = _publisher(
                directory,
                _Repository(),
                _TimelineStore(),
                _EvidenceStore(),
                clock,
            )

            root = publisher.publish()

            self.assertEqual(root.root_sequence, 1)
            self.assertIsNone(root.parent_snapshot_id)
            self.assertEqual(dict(root.campaigns), {})
            self.assertEqual(store.load_current(), root)

    def test_verified_campaign_and_evidence_are_bound_into_one_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            campaign = _record("campaign-a")
            repository = _Repository((campaign,))
            timeline = _TimelineStore()
            timeline.entries["campaign-a"] = (
                _TimelineEntry(_Event("event-1", 1), "a" * 64),
            )
            evidence = _EvidenceStore()
            evidence.records["campaign-a"] = (
                _EvidenceRecord(
                    sequence=1,
                    record_hash="b" * 64,
                    timeline_head_hash="a" * 64,
                    related_event_id="event-1",
                ),
            )
            clock = _Clock()
            publisher, store = _publisher(
                directory, repository, timeline, evidence, clock
            )

            root = publisher.publish()
            snapshot = store.load_campaign(root.campaigns["campaign-a"])

            self.assertEqual(snapshot.campaign, campaign)
            self.assertEqual(snapshot.timeline_head_sequence, 1)
            self.assertEqual(snapshot.timeline_head_sha256, "a" * 64)
            self.assertEqual(snapshot.evidence_head_sequence, 1)
            self.assertEqual(snapshot.evidence_head_sha256, "b" * 64)
            self.assertEqual(
                snapshot.latest_evidence_timeline_head_sha256,
                "a" * 64,
            )

    def test_unchanged_content_reuses_campaign_and_root_authority(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            campaign = _record("campaign-a")
            repository = _Repository((campaign,))
            timeline = _TimelineStore()
            timeline.entries["campaign-a"] = (
                _TimelineEntry(_Event("event-1", 1), "a" * 64),
            )
            evidence = _EvidenceStore()
            clock = _Clock()
            publisher, _ = _publisher(
                directory, repository, timeline, evidence, clock
            )

            first = publisher.publish()
            second = publisher.publish()

            self.assertEqual(second.snapshot_id, first.snapshot_id)
            self.assertEqual(second.root_sequence, 1)
            self.assertEqual(second.campaigns, first.campaigns)

    def test_pending_projection_blocks_before_snapshot_store_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository = _Repository((_record("campaign-a"),))
            repository.pending = (object(),)
            clock = _Clock()
            publisher, store = _publisher(
                directory,
                repository,
                _TimelineStore(),
                _EvidenceStore(),
                clock,
            )

            with self.assertRaises(OperatorSnapshotPublicationBlockedError):
                publisher.publish()

            self.assertIsNone(store.current_snapshot_id())
            self.assertFalse(Path(directory, "current.json").exists())

    def test_repository_revision_change_during_capture_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            first = _record("campaign-a", 0)
            repository = _Repository((first,))
            repository.get_overrides["campaign-a"] = _record("campaign-a", 1)
            clock = _Clock()
            publisher, store = _publisher(
                directory,
                repository,
                _TimelineStore(),
                _EvidenceStore(),
                clock,
            )

            with self.assertRaisesRegex(
                OperatorSnapshotPublicationConflictError,
                "changed while snapshot was captured",
            ):
                publisher.publish()

            self.assertIsNone(store.current_snapshot_id())

    def test_timeline_head_change_during_capture_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository = _Repository((_record("campaign-a"),))
            timeline = _TimelineStore()
            timeline.entries["campaign-a"] = (
                _TimelineEntry(_Event("event-1", 1), "a" * 64),
            )
            timeline.verify_overrides[1] = CampaignTimelineVerification(
                campaign_id="campaign-a",
                entry_count=2,
                evidence_count=0,
                head_hash="c" * 64,
            )
            clock = _Clock()
            publisher, store = _publisher(
                directory, repository, timeline, _EvidenceStore(), clock
            )

            with self.assertRaisesRegex(
                OperatorSnapshotPublicationConflictError,
                "timeline changed",
            ):
                publisher.publish()

            self.assertIsNone(store.current_snapshot_id())

    def test_mutation_after_campaign_blob_write_is_caught_before_root_commit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            first = _record("campaign-a")
            added = _record("campaign-b")
            repository = _Repository((first,))
            # list() call 1 captures, call 2 is the pre-write stability check,
            # call 3 is the post-blob/pre-root stability check.
            repository.list_overrides[3] = (first, added)
            timeline = _TimelineStore()
            timeline.entries["campaign-a"] = (
                _TimelineEntry(_Event("event-1", 1), "a" * 64),
            )
            clock = _Clock()
            publisher, store = _publisher(
                directory, repository, timeline, _EvidenceStore(), clock
            )

            with self.assertRaisesRegex(
                OperatorSnapshotPublicationConflictError,
                "repository changed",
            ):
                publisher.publish()

            self.assertIsNone(store.current_snapshot_id())

    def test_evidence_must_bind_to_a_captured_timeline_prefix(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository = _Repository((_record("campaign-a"),))
            timeline = _TimelineStore()
            timeline.entries["campaign-a"] = (
                _TimelineEntry(_Event("event-1", 1), "a" * 64),
                _TimelineEntry(_Event("event-2", 2), "b" * 64),
            )
            evidence = _EvidenceStore()
            evidence.records["campaign-a"] = (
                _EvidenceRecord(
                    sequence=1,
                    record_hash="c" * 64,
                    timeline_head_hash="a" * 64,
                    related_event_id="event-2",
                ),
            )
            clock = _Clock()
            publisher, store = _publisher(
                directory, repository, timeline, evidence, clock
            )

            with self.assertRaisesRegex(
                OperatorSnapshotPublicationIntegrityError,
                "outside its captured timeline head",
            ):
                publisher.publish()

            self.assertIsNone(store.current_snapshot_id())

    def test_deletion_only_changes_new_root_historical_root_stays_self_contained(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            campaign = _record("campaign-a")
            repository = _Repository((campaign,))
            timeline = _TimelineStore()
            timeline.entries["campaign-a"] = (
                _TimelineEntry(_Event("event-1", 1), "a" * 64),
            )
            evidence = _EvidenceStore()
            clock = _Clock()
            publisher, store = _publisher(
                directory, repository, timeline, evidence, clock
            )

            first = publisher.publish()
            first_campaign_snapshot = first.campaigns["campaign-a"]
            repository.records = ()
            second = publisher.publish()

            self.assertEqual(second.root_sequence, 2)
            self.assertEqual(second.parent_snapshot_id, first.snapshot_id)
            self.assertEqual(dict(second.campaigns), {})
            historical = store.load_root(first.snapshot_id, now=clock.now())
            self.assertEqual(
                historical.campaigns["campaign-a"],
                first_campaign_snapshot,
            )
            self.assertEqual(
                store.load_campaign(first_campaign_snapshot).campaign,
                campaign,
            )

    def test_restart_reuses_authority_then_advances_from_current_parent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            first_record = _record("campaign-a", 0)
            repository = _Repository((first_record,))
            timeline = _TimelineStore()
            timeline.entries["campaign-a"] = (
                _TimelineEntry(_Event("event-1", 1), "a" * 64),
            )
            evidence = _EvidenceStore()
            clock = _Clock()
            first_publisher, _ = _publisher(
                directory, repository, timeline, evidence, clock
            )
            first = first_publisher.publish()

            restarted, restarted_store = _publisher(
                directory, repository, timeline, evidence, clock
            )
            same = restarted.publish()
            self.assertEqual(same.snapshot_id, first.snapshot_id)

            repository.records = (_record("campaign-a", 1),)
            timeline.entries["campaign-a"] = (
                _TimelineEntry(_Event("event-1", 1), "a" * 64),
                _TimelineEntry(_Event("event-2", 2), "b" * 64),
            )
            advanced = restarted.publish()

            self.assertEqual(advanced.root_sequence, 2)
            self.assertEqual(advanced.parent_snapshot_id, first.snapshot_id)
            self.assertEqual(restarted_store.load_current(), advanced)

    def test_retention_is_explicit_afterwork_not_part_of_publish(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            clock = _Clock()
            publisher, store = _publisher(
                directory,
                _Repository(),
                _TimelineStore(),
                _EvidenceStore(),
                clock,
            )

            with patch.object(store, "prune", return_value=()) as prune:
                publisher.publish()
                prune.assert_not_called()
                self.assertEqual(publisher.prune(), ())
                prune.assert_called_once_with(now=clock.now())


class SnapshotPublisherCompositionTests(unittest.TestCase):
    def test_full_runtime_owns_dormant_snapshot_authority_without_boot_side_effects(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "agent4-data"
            clock = _Clock()

            context = compose_agent4_runtime(
                root,
                executor=_NullExecutor(),
                resource_capacities={"cpu": 1},
                resource_resolver=lambda _spec: {"cpu": 1},
                clock=clock,
            )

            self.assertEqual(
                context.paths.operator_snapshots,
                root / "operator-snapshots",
            )
            self.assertEqual(
                context.snapshot_store.root,
                context.paths.operator_snapshots,
            )
            self.assertIs(
                context.snapshot_publisher.snapshots,
                context.snapshot_store,
            )
            self.assertFalse(root.exists())


if __name__ == "__main__":
    unittest.main()
