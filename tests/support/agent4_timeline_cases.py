"""A4-06 append-only timeline and evidence-reference contract cases."""

from __future__ import annotations

import json
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.agent4 import (
    CampaignEvidenceReference,
    CampaignEvent,
    CampaignEventKind,
    CampaignEventRecorder,
    CampaignTimelineEntry,
    CampaignTimelineStore,
    CampaignValidationError,
    JsonCampaignTimelineStore,
    TimelineConflictError,
    TimelineIntegrityError,
    TimelineCampaignEventRecorder,
    TimelineStoreError,
)

BASE_TIME = datetime(2026, 7, 29, 15, 0, tzinfo=timezone.utc)


def _event(
    sequence: int,
    *,
    event_id: str | None = None,
    campaign_id: str = "campaign-timeline",
) -> CampaignEvent:
    return CampaignEvent(
        event_id=event_id or f"timeline-event-{sequence}",
        campaign_id=campaign_id,
        kind=(
            CampaignEventKind.CREATED
            if sequence == 1
            else CampaignEventKind.STARTED
        ),
        sequence=sequence,
        occurred_at=BASE_TIME + timedelta(seconds=sequence),
        payload={"sequence": sequence},
    )


class Agent4TimelineTests(unittest.TestCase):
    def test_append_round_trip_verify_and_replay(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = JsonCampaignTimelineStore(Path(directory))
            evidence = CampaignEvidenceReference(
                evidence_id="desktop-screenshot",
                media_type="image/png",
                location="evidence/desktop-screenshot.png",
                sha256="a" * 64,
                size_bytes=4096,
                metadata={"source": "controlled-rig"},
            )

            first = store.append(_event(1), evidence=(evidence,))
            second = store.append(_event(2))

            self.assertEqual(store.list("campaign-timeline"), (first, second))
            self.assertEqual(second.previous_hash, first.entry_hash)
            self.assertEqual(store.latest("campaign-timeline"), second)
            verification = store.verify("campaign-timeline")
            self.assertEqual(verification.entry_count, 2)
            self.assertEqual(verification.evidence_count, 1)
            self.assertEqual(verification.head_hash, second.entry_hash)

            replayed = []
            self.assertEqual(
                store.replay("campaign-timeline", replayed.append),
                2,
            )
            self.assertEqual(replayed, [first, second])
            self.assertFalse(any(Path(directory).rglob("*.tmp")))

    def test_append_accepts_identical_retry_but_rejects_gaps_and_conflicts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = JsonCampaignTimelineStore(directory)
            first = store.append(_event(1))
            self.assertEqual(store.append(_event(1)), first)
            with self.assertRaises(TimelineConflictError):
                store.append(_event(3))
            with self.assertRaises(TimelineConflictError):
                store.append(_event(2, event_id="timeline-event-1"))

    def test_content_tampering_breaks_entry_hash_validation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = JsonCampaignTimelineStore(directory)
            store.append(_event(1))
            path = next(Path(directory).rglob("*.timeline.json"))
            payload = json.loads(path.read_text(encoding="utf-8"))
            payload["event"]["payload"]["sequence"] = 999
            path.write_text(json.dumps(payload), encoding="utf-8")

            with self.assertRaises(TimelineIntegrityError):
                store.list("campaign-timeline")

    def test_chain_and_filename_rebinding_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = JsonCampaignTimelineStore(directory)
            store.append(_event(1))
            store.append(_event(2))
            paths = sorted(Path(directory).rglob("*.timeline.json"))
            second_payload = json.loads(paths[1].read_text(encoding="utf-8"))
            second_payload["previous_hash"] = "sha256:" + ("b" * 64)
            paths[1].write_text(
                json.dumps(second_payload, sort_keys=True),
                encoding="utf-8",
            )
            with self.assertRaises(TimelineIntegrityError):
                store.list("campaign-timeline")

        with tempfile.TemporaryDirectory() as directory:
            store = JsonCampaignTimelineStore(directory)
            store.append(_event(1))
            path = next(Path(directory).rglob("*.timeline.json"))
            rebound = path.with_name(
                f"{1:020d}-{'0' * 64}.timeline.json"
            )
            path.rename(rebound)
            with self.assertRaises(TimelineIntegrityError):
                store.list("campaign-timeline")

    def test_corrupt_final_entry_fails_while_orphan_temp_is_ignored(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = JsonCampaignTimelineStore(directory)
            store.append(_event(1))
            campaign_dir = next(Path(directory).iterdir())
            (campaign_dir / ".interrupted.tmp").write_text(
                '{"partial":',
                encoding="utf-8",
            )
            self.assertEqual(len(store.list("campaign-timeline")), 1)

            final_path = next(campaign_dir.glob("*.timeline.json"))
            final_path.write_text('{"partial":', encoding="utf-8")
            with self.assertRaises(TimelineStoreError):
                store.list("campaign-timeline")

    def test_evidence_and_entry_validation_fail_closed(self) -> None:
        with self.assertRaises(CampaignValidationError):
            CampaignEvidenceReference(
                evidence_id="bad",
                media_type="application/json",
                location="evidence.json",
                sha256="A" * 64,
                size_bytes=1,
            )
        with self.assertRaises(CampaignValidationError):
            CampaignEvidenceReference(
                evidence_id="bad",
                media_type="application/json",
                location="evidence.json",
                sha256="a" * 64,
                size_bytes=True,
            )

        reference = CampaignEvidenceReference(
            evidence_id="same",
            media_type="application/json",
            location="evidence.json",
            sha256="a" * 64,
            size_bytes=1,
        )
        with self.assertRaises(CampaignValidationError):
            CampaignTimelineEntry(
                event=_event(1),
                evidence=(reference, reference),
            )
        with self.assertRaises(CampaignValidationError):
            CampaignTimelineEntry(event=_event(2))
        with self.assertRaises(CampaignValidationError):
            CampaignTimelineEntry(
                event=_event(1),
                previous_hash="a" * 64,
            )

    def test_empty_timeline_and_handler_contract_are_explicit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = JsonCampaignTimelineStore(directory)
            self.assertEqual(store.list("unknown"), ())
            self.assertIsNone(store.latest("unknown"))
            verification = store.verify("unknown")
            self.assertEqual(verification.entry_count, 0)
            self.assertIsNone(verification.head_hash)
            with self.assertRaises(TypeError):
                store.replay("unknown", None)  # type: ignore[arg-type]

    def test_timeline_recorder_is_protocol_compatible_and_restart_safe(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = JsonCampaignTimelineStore(directory)
            recorder = TimelineCampaignEventRecorder(store)
            self.assertIsInstance(store, CampaignTimelineStore)
            self.assertIsInstance(recorder, CampaignEventRecorder)

            first = recorder.record(
                " campaign-recorder ",
                CampaignEventKind.CREATED,
                occurred_at=BASE_TIME,
                payload={"phase": "created"},
            )
            second = TimelineCampaignEventRecorder(store).record(
                "campaign-recorder",
                CampaignEventKind.STARTED,
                occurred_at=BASE_TIME + timedelta(seconds=1),
            )

            self.assertEqual(first.event_id, "campaign-recorder:1")
            self.assertEqual(second.event_id, "campaign-recorder:2")
            self.assertEqual(
                [entry.event for entry in store.list("campaign-recorder")],
                [first, second],
            )

    def test_timeline_recorder_can_bind_evidence_explicitly(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = JsonCampaignTimelineStore(directory)
            recorder = TimelineCampaignEventRecorder(store)
            evidence = CampaignEvidenceReference(
                evidence_id="report",
                media_type="application/json",
                location="evidence/report.json",
                sha256="c" * 64,
                size_bytes=512,
            )

            event = recorder.record_with_evidence(
                "campaign-evidence",
                CampaignEventKind.CREATED,
                occurred_at=BASE_TIME,
                payload={"phase": "validation"},
                evidence=(evidence,),
            )

            entry = store.latest("campaign-evidence")
            self.assertIsNotNone(entry)
            self.assertEqual(entry.event, event)
            self.assertEqual(entry.evidence, (evidence,))

    def test_timeline_recorder_serializes_concurrent_callers(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = JsonCampaignTimelineStore(directory)
            recorder = TimelineCampaignEventRecorder(store)

            def record(index: int) -> CampaignEvent:
                return recorder.record(
                    "campaign-concurrent",
                    CampaignEventKind.STARTED,
                    occurred_at=BASE_TIME + timedelta(milliseconds=index),
                    payload={"caller": index},
                )

            with ThreadPoolExecutor(max_workers=8) as pool:
                events = list(pool.map(record, range(16)))

            self.assertEqual(
                sorted(event.sequence for event in events),
                list(range(1, 17)),
            )
            timeline = store.list("campaign-concurrent")
            self.assertEqual(
                [entry.event.sequence for entry in timeline],
                list(range(1, 17)),
            )
            self.assertEqual(
                [entry.event.event_id for entry in timeline],
                [f"campaign-concurrent:{number}" for number in range(1, 17)],
            )

    def test_timeline_recorder_fails_closed_on_corrupt_history(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = JsonCampaignTimelineStore(directory)
            recorder = TimelineCampaignEventRecorder(store)
            recorder.record(
                "campaign-corrupt",
                CampaignEventKind.CREATED,
                occurred_at=BASE_TIME,
            )
            path = next(Path(directory).rglob("*.timeline.json"))
            payload = json.loads(path.read_text(encoding="utf-8"))
            payload["entry_hash"] = "sha256:" + ("0" * 64)
            path.write_text(json.dumps(payload), encoding="utf-8")

            with self.assertRaises(TimelineIntegrityError):
                recorder.record(
                    "campaign-corrupt",
                    CampaignEventKind.STARTED,
                    occurred_at=BASE_TIME + timedelta(seconds=1),
                )

        with self.assertRaises(TypeError):
            TimelineCampaignEventRecorder(object())  # type: ignore[arg-type]
