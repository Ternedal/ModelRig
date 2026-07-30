"""A4-08 durable timeline consumer offset contract tests."""

from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.agent4.domain import CampaignEvent, CampaignEventKind, CampaignValidationError
from app.agent4.timeline import CampaignEvidence, GENESIS_HASH, JsonlCampaignTimelineStore
from app.agent4.timeline_consumers import (
    CampaignTimelineConsumerCommitError,
    CampaignTimelineConsumerConflictError,
    CampaignTimelineConsumerHandlerError,
    CampaignTimelineConsumerOffset,
    CampaignTimelineConsumerService,
    CampaignTimelineConsumerStoreError,
    JsonCampaignTimelineConsumerStore,
)
from app.agent4.timeline_replay import (
    CampaignTimelineCursor,
    CampaignTimelineCursorError,
    CampaignTimelineReplayService,
)


BASE_TIME = datetime(2026, 7, 30, 15, 30, tzinfo=timezone.utc)


class FailingOffsetStore(JsonCampaignTimelineConsumerStore):
    def __init__(self, directory: str, *, fail_sequence: int) -> None:
        super().__init__(directory)
        self.fail_sequence = fail_sequence
        self.failures_remaining = 1

    def save(self, offset: CampaignTimelineConsumerOffset) -> None:
        if (
            offset.cursor.timeline_sequence == self.fail_sequence
            and self.failures_remaining > 0
        ):
            self.failures_remaining -= 1
            raise CampaignTimelineConsumerStoreError("simulated offset write failure")
        super().save(offset)


class Agent4TimelineConsumerTests(unittest.TestCase):
    def event(self, sequence: int, campaign_id: str = "campaign-consumer") -> CampaignEvent:
        return CampaignEvent(
            event_id=f"{campaign_id}:{sequence}",
            campaign_id=campaign_id,
            kind=(
                CampaignEventKind.STARTED
                if sequence == 1
                else CampaignEventKind.CHECKPOINTED
            ),
            sequence=sequence,
            occurred_at=BASE_TIME + timedelta(seconds=sequence),
            payload={"sequence": sequence},
        )

    def evidence(self, evidence_id: str, *, offset: int = 30) -> CampaignEvidence:
        return CampaignEvidence(
            evidence_id=evidence_id,
            campaign_id="campaign-consumer",
            category="operator-proof",
            source="test",
            recorded_at=BASE_TIME + timedelta(seconds=offset),
            payload={"accepted": True, "id": evidence_id},
        )

    def populated(self, timeline_directory: str):
        timeline = JsonlCampaignTimelineStore(timeline_directory)
        timeline.append_event(self.event(1))
        timeline.append_evidence(self.evidence("proof-1"))
        timeline.append_event(self.event(2))
        replay = CampaignTimelineReplayService(timeline)
        return timeline, replay

    def test_store_construction_is_dormant_and_missing_offset_is_none(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "offsets"
            store = JsonCampaignTimelineConsumerStore(root)
            self.assertFalse(root.exists())
            self.assertIsNone(store.get("campaign-consumer", "indexer"))
            self.assertFalse(root.exists())

    def test_offset_round_trip_survives_restart_and_delete_is_explicit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            cursor = CampaignTimelineCursor(
                campaign_id="campaign-consumer",
                timeline_sequence=1,
                content_hash="a" * 64,
            )
            offset = CampaignTimelineConsumerOffset(
                consumer_id="indexer",
                campaign_id="campaign-consumer",
                cursor=cursor,
                updated_at=BASE_TIME,
            )
            JsonCampaignTimelineConsumerStore(directory).save(offset)
            restarted = JsonCampaignTimelineConsumerStore(directory)
            self.assertEqual(restarted.get("campaign-consumer", "indexer"), offset)
            self.assertTrue(restarted.delete("campaign-consumer", "indexer"))
            self.assertFalse(restarted.delete("campaign-consumer", "indexer"))

    def test_store_rejects_regression_and_hash_contradiction(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = JsonCampaignTimelineConsumerStore(directory)
            current = CampaignTimelineConsumerOffset(
                consumer_id="indexer",
                campaign_id="campaign-consumer",
                cursor=CampaignTimelineCursor("campaign-consumer", 2, "b" * 64),
                updated_at=BASE_TIME,
            )
            store.save(current)
            store.save(current)
            with self.assertRaises(CampaignTimelineConsumerConflictError):
                store.save(
                    CampaignTimelineConsumerOffset(
                        "indexer",
                        "campaign-consumer",
                        CampaignTimelineCursor("campaign-consumer", 1, "a" * 64),
                        BASE_TIME + timedelta(seconds=1),
                    )
                )
            with self.assertRaises(CampaignTimelineConsumerConflictError):
                store.save(
                    CampaignTimelineConsumerOffset(
                        "indexer",
                        "campaign-consumer",
                        CampaignTimelineCursor("campaign-consumer", 2, "c" * 64),
                        BASE_TIME + timedelta(seconds=1),
                    )
                )
            self.assertEqual(store.get("campaign-consumer", "indexer"), current)

    def test_consumer_persists_each_success_and_resumes_without_duplicates(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            _, replay = self.populated(str(Path(root) / "timeline"))
            offsets = JsonCampaignTimelineConsumerStore(Path(root) / "offsets")
            service = CampaignTimelineConsumerService(replay, offsets)
            observed: list[int] = []

            first = service.consume_batch(
                "campaign-consumer",
                "indexer",
                lambda entry: observed.append(entry.timeline_sequence),
                updated_at=BASE_TIME,
                max_entries=2,
            )
            self.assertEqual(observed, [1, 2])
            self.assertEqual(first.accepted_count, 2)
            self.assertFalse(first.completed)
            self.assertEqual(first.durable_cursor.timeline_sequence, 2)

            restarted = CampaignTimelineConsumerService(
                replay,
                JsonCampaignTimelineConsumerStore(Path(root) / "offsets"),
            )
            second = restarted.consume_batch(
                "campaign-consumer",
                "indexer",
                lambda entry: observed.append(entry.timeline_sequence),
                updated_at=BASE_TIME + timedelta(minutes=1),
            )
            self.assertEqual(observed, [1, 2, 3])
            self.assertEqual(second.accepted_count, 1)
            self.assertTrue(second.completed)

    def test_consumers_advance_independently(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            _, replay = self.populated(str(Path(root) / "timeline"))
            offsets = JsonCampaignTimelineConsumerStore(Path(root) / "offsets")
            service = CampaignTimelineConsumerService(replay, offsets)
            service.consume_batch(
                "campaign-consumer",
                "indexer",
                lambda _entry: None,
                updated_at=BASE_TIME,
                max_entries=1,
            )
            service.consume_batch(
                "campaign-consumer",
                "auditor",
                lambda _entry: None,
                updated_at=BASE_TIME,
                max_entries=3,
            )
            self.assertEqual(
                offsets.get("campaign-consumer", "indexer").cursor.timeline_sequence, 1
            )
            self.assertEqual(
                offsets.get("campaign-consumer", "auditor").cursor.timeline_sequence, 3
            )

    def test_handler_failure_does_not_advance_failed_entry(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            _, replay = self.populated(str(Path(root) / "timeline"))
            offsets = JsonCampaignTimelineConsumerStore(Path(root) / "offsets")
            service = CampaignTimelineConsumerService(replay, offsets)
            observed: list[int] = []

            def fail_second(entry) -> None:
                if entry.timeline_sequence == 2:
                    raise RuntimeError("consumer rejected entry")
                observed.append(entry.timeline_sequence)

            with self.assertRaises(CampaignTimelineConsumerHandlerError) as raised:
                service.consume_batch(
                    "campaign-consumer",
                    "indexer",
                    fail_second,
                    updated_at=BASE_TIME,
                )
            self.assertEqual(observed, [1])
            self.assertEqual(raised.exception.failed_entry.timeline_sequence, 2)
            self.assertEqual(raised.exception.durable_cursor.timeline_sequence, 1)
            self.assertEqual(
                offsets.get("campaign-consumer", "indexer").cursor.timeline_sequence, 1
            )

            replayed: list[int] = []
            service.consume_batch(
                "campaign-consumer",
                "indexer",
                lambda entry: replayed.append(entry.timeline_sequence),
                updated_at=BASE_TIME + timedelta(seconds=1),
            )
            self.assertEqual(replayed, [2, 3])

    def test_commit_failure_is_at_least_once_and_never_skips(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            _, replay = self.populated(str(Path(root) / "timeline"))
            path = str(Path(root) / "offsets")
            failing = FailingOffsetStore(path, fail_sequence=2)
            service = CampaignTimelineConsumerService(replay, failing)
            accepted: list[int] = []

            with self.assertRaises(CampaignTimelineConsumerCommitError) as raised:
                service.consume_batch(
                    "campaign-consumer",
                    "indexer",
                    lambda entry: accepted.append(entry.timeline_sequence),
                    updated_at=BASE_TIME,
                )
            self.assertEqual(accepted, [1, 2])
            self.assertEqual(raised.exception.accepted_entry.timeline_sequence, 2)
            self.assertEqual(raised.exception.durable_cursor.timeline_sequence, 1)
            self.assertEqual(raised.exception.attempted_cursor.timeline_sequence, 2)

            retried: list[int] = []
            normal = CampaignTimelineConsumerService(
                replay, JsonCampaignTimelineConsumerStore(path)
            )
            normal.consume_batch(
                "campaign-consumer",
                "indexer",
                lambda entry: retried.append(entry.timeline_sequence),
                updated_at=BASE_TIME + timedelta(seconds=1),
            )
            self.assertEqual(retried, [2, 3])

    def test_tampered_or_foreign_durable_cursor_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            _, replay = self.populated(str(Path(root) / "timeline"))
            offsets = JsonCampaignTimelineConsumerStore(Path(root) / "offsets")
            offsets.save(
                CampaignTimelineConsumerOffset(
                    "indexer",
                    "campaign-consumer",
                    CampaignTimelineCursor("campaign-consumer", 1, "f" * 64),
                    BASE_TIME,
                )
            )
            service = CampaignTimelineConsumerService(replay, offsets)
            with self.assertRaises(CampaignTimelineCursorError):
                service.consume_batch(
                    "campaign-consumer",
                    "indexer",
                    lambda _entry: None,
                    updated_at=BASE_TIME,
                )

    def test_invalid_inputs_and_corrupt_offset_fail_without_progress(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            _, replay = self.populated(str(Path(root) / "timeline"))
            offsets_path = Path(root) / "offsets"
            offsets = JsonCampaignTimelineConsumerStore(offsets_path)
            service = CampaignTimelineConsumerService(replay, offsets)
            with self.assertRaises(TypeError):
                service.consume_batch(
                    "campaign-consumer",
                    "indexer",
                    None,  # type: ignore[arg-type]
                    updated_at=BASE_TIME,
                )
            with self.assertRaises(CampaignValidationError):
                service.consume_batch(
                    "campaign-consumer",
                    "indexer",
                    lambda _entry: None,
                    updated_at=BASE_TIME.replace(tzinfo=None),
                )
            with self.assertRaises(CampaignValidationError):
                service.consume_batch(
                    "campaign-consumer",
                    "indexer",
                    lambda _entry: None,
                    updated_at=BASE_TIME,
                    max_entries=0,
                )
            self.assertIsNone(offsets.get("campaign-consumer", "indexer"))

            offsets_path.mkdir(parents=True, exist_ok=True)
            path = offsets._path("campaign-consumer", "indexer")
            path.write_text(json.dumps({"schema": "wrong"}), encoding="utf-8")
            with self.assertRaises(CampaignTimelineConsumerStoreError):
                offsets.get("campaign-consumer", "indexer")


__all__ = ["Agent4TimelineConsumerTests"]
