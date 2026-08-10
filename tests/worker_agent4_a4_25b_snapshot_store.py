#!/usr/bin/env python3
"""A4-25b contracts for immutable Agent 4 operator snapshot storage."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "worker"))

from app.agent4.domain import (  # noqa: E402
    CampaignRecord,
    CampaignSpec,
    CampaignState,
)
from app.agent4.snapshot_store import (  # noqa: E402
    JsonOperatorSnapshotStore,
    OperatorCampaignSnapshot,
    OperatorRootSnapshot,
    OperatorSnapshotConflictError,
    OperatorSnapshotIntegrityError,
    OperatorSnapshotNotFoundError,
)

UTC = timezone.utc
BASE_TIME = datetime(2026, 8, 10, 13, 30, tzinfo=UTC)


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


def _campaign_snapshot(
    campaign_id: str,
    *,
    revision: int = 0,
    marker: str = "1",
) -> OperatorCampaignSnapshot:
    evidence_sequence = revision
    return OperatorCampaignSnapshot.create(
        _record(campaign_id, revision),
        timeline_head_sequence=revision + 1,
        timeline_head_sha256=marker * 64,
        evidence_head_sequence=evidence_sequence,
        evidence_head_sha256=("2" * 64 if evidence_sequence else None),
        latest_evidence_timeline_head_sha256=(
            "3" * 64 if evidence_sequence else None
        ),
    )


def _root_snapshot(
    *,
    sequence: int,
    parent: str | None,
    published_at: datetime,
    snapshots: tuple[OperatorCampaignSnapshot, ...],
) -> OperatorRootSnapshot:
    return OperatorRootSnapshot.create(
        root_sequence=sequence,
        parent_snapshot_id=parent,
        published_at=published_at,
        campaigns={
            snapshot.campaign_id: snapshot.snapshot_id for snapshot in snapshots
        },
    )


class OperatorSnapshotDomainTests(unittest.TestCase):
    def test_campaign_snapshot_is_content_addressed_and_round_trips(self) -> None:
        first = _campaign_snapshot("campaign-a")
        second = _campaign_snapshot("campaign-a")

        self.assertEqual(first.snapshot_id, second.snapshot_id)
        self.assertEqual(OperatorCampaignSnapshot.from_dict(first.to_dict()), first)

        mutated = dict(first.to_dict())
        mutated["timeline_head"] = {
            "sequence": 1,
            "sha256": "4" * 64,
        }
        with self.assertRaisesRegex(
            ValueError,
            "snapshot_id does not match content",
        ):
            OperatorCampaignSnapshot.from_dict(mutated)

    def test_empty_evidence_chain_uses_null_heads_not_synthetic_hashes(self) -> None:
        snapshot = _campaign_snapshot("campaign-a", revision=0)
        value = snapshot.to_dict()

        self.assertEqual(value["evidence_head"], {"sequence": 0, "sha256": None})
        self.assertIsNone(value["latest_evidence_timeline_head_sha256"])
        with self.assertRaisesRegex(ValueError, "must be null when sequence is 0"):
            OperatorCampaignSnapshot.create(
                _record("campaign-a"),
                timeline_head_sequence=1,
                timeline_head_sha256="1" * 64,
                evidence_head_sequence=0,
                evidence_head_sha256="2" * 64,
                latest_evidence_timeline_head_sha256=None,
            )

    def test_nonempty_head_requires_real_sha256(self) -> None:
        with self.assertRaisesRegex(ValueError, "evidence_head_sha256"):
            OperatorCampaignSnapshot.create(
                _record("campaign-a", 1),
                timeline_head_sequence=2,
                timeline_head_sha256="1" * 64,
                evidence_head_sequence=1,
                evidence_head_sha256=None,
                latest_evidence_timeline_head_sha256="3" * 64,
            )

    def test_root_id_is_independent_of_campaign_mapping_insertion_order(self) -> None:
        left = _campaign_snapshot("campaign-a", marker="a")
        right = _campaign_snapshot("campaign-b", marker="b")
        first = OperatorRootSnapshot.create(
            root_sequence=1,
            parent_snapshot_id=None,
            published_at=BASE_TIME,
            campaigns={
                left.campaign_id: left.snapshot_id,
                right.campaign_id: right.snapshot_id,
            },
        )
        second = OperatorRootSnapshot.create(
            root_sequence=1,
            parent_snapshot_id=None,
            published_at=BASE_TIME,
            campaigns={
                right.campaign_id: right.snapshot_id,
                left.campaign_id: left.snapshot_id,
            },
        )

        self.assertEqual(first.snapshot_id, second.snapshot_id)
        self.assertEqual(OperatorRootSnapshot.from_dict(first.to_dict()), first)

    def test_root_lineage_shape_fails_closed(self) -> None:
        with self.assertRaisesRegex(ValueError, "genesis root"):
            OperatorRootSnapshot.create(
                root_sequence=1,
                parent_snapshot_id="a" * 64,
                published_at=BASE_TIME,
                campaigns={},
            )
        with self.assertRaisesRegex(ValueError, "non-genesis root"):
            OperatorRootSnapshot.create(
                root_sequence=2,
                parent_snapshot_id=None,
                published_at=BASE_TIME,
                campaigns={},
            )


class JsonOperatorSnapshotStoreTests(unittest.TestCase):
    def test_publish_commits_only_at_current_pointer(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = JsonOperatorSnapshotStore(directory)
            campaign = store.write_campaign_snapshot(
                _campaign_snapshot("campaign-a")
            )
            root = _root_snapshot(
                sequence=1,
                parent=None,
                published_at=BASE_TIME,
                snapshots=(campaign,),
            )

            self.assertIsNone(store.current_snapshot_id())
            store.publish_root(root, expected_parent=None)

            self.assertEqual(store.current_snapshot_id(), root.snapshot_id)
            self.assertEqual(store.load_current(), root)
            self.assertEqual(store.load_root(root.snapshot_id), root)
            self.assertEqual(store.load_campaign(campaign.snapshot_id), campaign)

    def test_crash_before_pointer_replace_keeps_old_root_and_hides_new_root(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = JsonOperatorSnapshotStore(directory)
            first_campaign = store.write_campaign_snapshot(
                _campaign_snapshot("campaign-a", marker="a")
            )
            first_root = _root_snapshot(
                sequence=1,
                parent=None,
                published_at=BASE_TIME,
                snapshots=(first_campaign,),
            )
            store.publish_root(first_root, expected_parent=None)

            second_campaign = store.write_campaign_snapshot(
                _campaign_snapshot("campaign-a", revision=1, marker="b")
            )
            second_root = _root_snapshot(
                sequence=2,
                parent=first_root.snapshot_id,
                published_at=BASE_TIME + timedelta(minutes=1),
                snapshots=(second_campaign,),
            )

            def fail(point: str) -> None:
                if point == "before_current_replace":
                    raise RuntimeError("injected pre-commit crash")

            crashing = JsonOperatorSnapshotStore(
                directory,
                failure_injector=fail,
            )
            with self.assertRaisesRegex(RuntimeError, "pre-commit"):
                crashing.publish_root(
                    second_root,
                    expected_parent=first_root.snapshot_id,
                )

            self.assertEqual(store.current_snapshot_id(), first_root.snapshot_id)
            self.assertEqual(store.load_current(), first_root)
            with self.assertRaises(OperatorSnapshotNotFoundError):
                store.load_root(second_root.snapshot_id)

            removed = store.prune(now=BASE_TIME + timedelta(minutes=2))
            self.assertIn(second_root.snapshot_id, removed)
            with self.assertRaises(OperatorSnapshotNotFoundError):
                store.load_campaign(second_campaign.snapshot_id)

    def test_crash_after_pointer_replace_means_new_root_is_already_committed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = JsonOperatorSnapshotStore(directory)
            first_campaign = store.write_campaign_snapshot(
                _campaign_snapshot("campaign-a", marker="a")
            )
            first_root = _root_snapshot(
                sequence=1,
                parent=None,
                published_at=BASE_TIME,
                snapshots=(first_campaign,),
            )
            store.publish_root(first_root, expected_parent=None)

            second_campaign = store.write_campaign_snapshot(
                _campaign_snapshot("campaign-a", revision=1, marker="b")
            )
            second_root = _root_snapshot(
                sequence=2,
                parent=first_root.snapshot_id,
                published_at=BASE_TIME + timedelta(minutes=1),
                snapshots=(second_campaign,),
            )

            def fail(point: str) -> None:
                if point == "after_current_replace":
                    raise RuntimeError("injected post-commit crash")

            crashing = JsonOperatorSnapshotStore(
                directory,
                failure_injector=fail,
            )
            with self.assertRaisesRegex(RuntimeError, "post-commit"):
                crashing.publish_root(
                    second_root,
                    expected_parent=first_root.snapshot_id,
                )

            self.assertEqual(store.current_snapshot_id(), second_root.snapshot_id)
            self.assertEqual(store.load_current(), second_root)
            self.assertEqual(store.load_root(second_root.snapshot_id), second_root)

    def test_publish_never_runs_retention_cleanup_inside_commit_path(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = JsonOperatorSnapshotStore(directory)
            campaign = store.write_campaign_snapshot(
                _campaign_snapshot("campaign-a", marker="a")
            )
            root = _root_snapshot(
                sequence=1,
                parent=None,
                published_at=BASE_TIME,
                snapshots=(campaign,),
            )

            with patch.object(
                store,
                "prune",
                side_effect=AssertionError("cleanup entered commit path"),
            ) as prune:
                store.publish_root(root, expected_parent=None)

            prune.assert_not_called()
            self.assertEqual(store.current_snapshot_id(), root.snapshot_id)

    def test_retry_after_precommit_crash_can_publish_same_content_addressed_root(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = JsonOperatorSnapshotStore(directory)
            first_campaign = base.write_campaign_snapshot(
                _campaign_snapshot("campaign-a", marker="a")
            )
            first_root = _root_snapshot(
                sequence=1,
                parent=None,
                published_at=BASE_TIME,
                snapshots=(first_campaign,),
            )
            base.publish_root(first_root, expected_parent=None)
            second_campaign = base.write_campaign_snapshot(
                _campaign_snapshot("campaign-a", revision=1, marker="b")
            )
            second_root = _root_snapshot(
                sequence=2,
                parent=first_root.snapshot_id,
                published_at=BASE_TIME + timedelta(minutes=1),
                snapshots=(second_campaign,),
            )

            def fail(point: str) -> None:
                if point == "before_current_replace":
                    raise RuntimeError("injected crash")

            crashing = JsonOperatorSnapshotStore(
                directory,
                failure_injector=fail,
            )
            with self.assertRaises(RuntimeError):
                crashing.publish_root(
                    second_root,
                    expected_parent=first_root.snapshot_id,
                )

            base.publish_root(
                second_root,
                expected_parent=first_root.snapshot_id,
            )
            self.assertEqual(base.current_snapshot_id(), second_root.snapshot_id)

    def test_stale_parent_sequence_and_backwards_time_fail_before_commit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = JsonOperatorSnapshotStore(directory)
            campaign = store.write_campaign_snapshot(
                _campaign_snapshot("campaign-a", marker="a")
            )
            first_root = _root_snapshot(
                sequence=1,
                parent=None,
                published_at=BASE_TIME,
                snapshots=(campaign,),
            )
            store.publish_root(first_root, expected_parent=None)

            wrong_sequence = _root_snapshot(
                sequence=3,
                parent=first_root.snapshot_id,
                published_at=BASE_TIME + timedelta(minutes=1),
                snapshots=(campaign,),
            )
            with self.assertRaisesRegex(OperatorSnapshotConflictError, "sequence"):
                store.publish_root(
                    wrong_sequence,
                    expected_parent=first_root.snapshot_id,
                )

            backwards = _root_snapshot(
                sequence=2,
                parent=first_root.snapshot_id,
                published_at=BASE_TIME - timedelta(seconds=1),
                snapshots=(campaign,),
            )
            with self.assertRaisesRegex(
                OperatorSnapshotConflictError,
                "published_at",
            ):
                store.publish_root(
                    backwards,
                    expected_parent=first_root.snapshot_id,
                )

            second_root = _root_snapshot(
                sequence=2,
                parent=first_root.snapshot_id,
                published_at=BASE_TIME + timedelta(minutes=1),
                snapshots=(campaign,),
            )
            store.publish_root(
                second_root,
                expected_parent=first_root.snapshot_id,
            )

            stale = _root_snapshot(
                sequence=2,
                parent=first_root.snapshot_id,
                published_at=BASE_TIME + timedelta(minutes=2),
                snapshots=(campaign,),
            )
            with self.assertRaisesRegex(
                OperatorSnapshotConflictError,
                "parent is stale",
            ):
                store.publish_root(
                    stale,
                    expected_parent=first_root.snapshot_id,
                )
            self.assertEqual(store.current_snapshot_id(), second_root.snapshot_id)

    def test_root_cannot_reference_snapshot_owned_by_another_campaign(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = JsonOperatorSnapshotStore(directory)
            campaign = store.write_campaign_snapshot(
                _campaign_snapshot("campaign-a", marker="a")
            )
            root = OperatorRootSnapshot.create(
                root_sequence=1,
                parent_snapshot_id=None,
                published_at=BASE_TIME,
                campaigns={"campaign-b": campaign.snapshot_id},
            )
            with self.assertRaisesRegex(
                OperatorSnapshotIntegrityError,
                "identity",
            ):
                store.publish_root(root, expected_parent=None)
            self.assertIsNone(store.current_snapshot_id())

    def test_retention_is_bounded_and_campaign_gc_is_reference_safe(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            clock = lambda: BASE_TIME + timedelta(minutes=10)
            store = JsonOperatorSnapshotStore(
                directory,
                max_roots=2,
                max_age=timedelta(minutes=15),
                clock=clock,
            )

            first_campaign = store.write_campaign_snapshot(
                _campaign_snapshot("campaign-a", marker="a")
            )
            first_root = _root_snapshot(
                sequence=1,
                parent=None,
                published_at=BASE_TIME,
                snapshots=(first_campaign,),
            )
            store.publish_root(first_root, expected_parent=None)

            second_campaign = store.write_campaign_snapshot(
                _campaign_snapshot("campaign-a", revision=1, marker="b")
            )
            second_root = _root_snapshot(
                sequence=2,
                parent=first_root.snapshot_id,
                published_at=BASE_TIME + timedelta(minutes=5),
                snapshots=(second_campaign,),
            )
            store.publish_root(
                second_root,
                expected_parent=first_root.snapshot_id,
            )

            third_campaign = store.write_campaign_snapshot(
                _campaign_snapshot("campaign-a", revision=2, marker="c")
            )
            third_root = _root_snapshot(
                sequence=3,
                parent=second_root.snapshot_id,
                published_at=BASE_TIME + timedelta(minutes=10),
                snapshots=(third_campaign,),
            )
            store.publish_root(
                third_root,
                expected_parent=second_root.snapshot_id,
            )

            self.assertEqual(store.load_root(third_root.snapshot_id), third_root)
            self.assertEqual(store.load_root(second_root.snapshot_id), second_root)
            with self.assertRaises(OperatorSnapshotNotFoundError):
                store.load_root(first_root.snapshot_id)

            # Retention visibility and physical cleanup are deliberately separate.
            self.assertEqual(
                store.load_campaign(first_campaign.snapshot_id),
                first_campaign,
            )
            removed = store.prune()
            self.assertIn(first_root.snapshot_id, removed)
            with self.assertRaises(OperatorSnapshotNotFoundError):
                store.load_campaign(first_campaign.snapshot_id)
            self.assertEqual(
                store.load_campaign(second_campaign.snapshot_id),
                second_campaign,
            )
            self.assertEqual(
                store.load_campaign(third_campaign.snapshot_id),
                third_campaign,
            )

    def test_age_expiry_removes_historical_root_but_never_current_root(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            now = BASE_TIME + timedelta(minutes=30)
            store = JsonOperatorSnapshotStore(
                directory,
                max_roots=256,
                max_age=timedelta(minutes=15),
                clock=lambda: now,
            )
            campaign = store.write_campaign_snapshot(
                _campaign_snapshot("campaign-a", marker="a")
            )
            first_root = _root_snapshot(
                sequence=1,
                parent=None,
                published_at=BASE_TIME,
                snapshots=(campaign,),
            )
            store.publish_root(first_root, expected_parent=None)

            # An idle system must not lose its current authoritative snapshot.
            self.assertEqual(store.load_root(first_root.snapshot_id), first_root)

            second_root = _root_snapshot(
                sequence=2,
                parent=first_root.snapshot_id,
                published_at=now,
                snapshots=(campaign,),
            )
            store.publish_root(
                second_root,
                expected_parent=first_root.snapshot_id,
            )
            with self.assertRaises(OperatorSnapshotNotFoundError):
                store.load_root(first_root.snapshot_id)
            self.assertEqual(store.load_root(second_root.snapshot_id), second_root)

    def test_tamper_and_duplicate_keys_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = JsonOperatorSnapshotStore(directory)
            campaign = store.write_campaign_snapshot(
                _campaign_snapshot("campaign-a", marker="a")
            )
            root = _root_snapshot(
                sequence=1,
                parent=None,
                published_at=BASE_TIME,
                snapshots=(campaign,),
            )
            store.publish_root(root, expected_parent=None)

            campaign_path = (
                Path(directory) / "campaigns" / f"{campaign.snapshot_id}.json"
            )
            value = json.loads(campaign_path.read_text(encoding="utf-8"))
            value["timeline_head"]["sha256"] = "f" * 64
            campaign_path.write_text(
                json.dumps(value, sort_keys=True),
                encoding="utf-8",
            )
            with self.assertRaises(OperatorSnapshotIntegrityError):
                store.load_campaign(campaign.snapshot_id)

        with tempfile.TemporaryDirectory() as directory:
            store = JsonOperatorSnapshotStore(directory)
            campaign = store.write_campaign_snapshot(
                _campaign_snapshot("campaign-a", marker="a")
            )
            root = _root_snapshot(
                sequence=1,
                parent=None,
                published_at=BASE_TIME,
                snapshots=(campaign,),
            )
            store.publish_root(root, expected_parent=None)
            current = Path(directory) / "current.json"
            current.write_text(
                (
                    '{"schema":"modelrig-agent4/operator-snapshot-pointer/v1",'
                    f'"snapshot_id":"{root.snapshot_id}",'
                    f'"snapshot_id":"{root.snapshot_id}"}}'
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(
                OperatorSnapshotIntegrityError,
                "duplicate JSON key",
            ):
                store.current_snapshot_id()


if __name__ == "__main__":
    unittest.main()
