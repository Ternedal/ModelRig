#!/usr/bin/env python3
"""A4-12 first-class evidence record contract tests."""

from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.agent4 import (
    CampaignEvidenceReference,
    CampaignEvent,
    CampaignEventKind,
    CampaignValidationError,
    JsonCampaignTimelineStore,
)
from app.agent4.timeline_evidence import (
    CampaignEvidenceRecord,
    CampaignEvidenceRecordService,
    EvidenceRecordConflictError,
    EvidenceRecordIntegrityError,
    EvidenceRecordStoreError,
    JsonCampaignEvidenceRecordStore,
)

BASE_TIME = datetime(2026, 8, 1, 8, 0, tzinfo=timezone.utc)


def _event(
    sequence: int,
    *,
    campaign_id: str = "campaign-evidence",
    event_id: str | None = None,
) -> CampaignEvent:
    return CampaignEvent(
        event_id=event_id or f"{campaign_id}:{sequence}",
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


def _evidence(
    evidence_id: str,
    *,
    digest: str = "a" * 64,
) -> CampaignEvidenceReference:
    return CampaignEvidenceReference(
        evidence_id=evidence_id,
        media_type="application/json",
        location=f"evidence/{evidence_id}.json",
        sha256=digest,
        size_bytes=512,
        metadata={"source": "controlled-rig"},
    )


class Agent4EvidenceRecordTests(unittest.TestCase):
    def test_service_records_directly_addressable_chain_bound_to_timeline(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            timeline = JsonCampaignTimelineStore(root / "timeline")
            records = JsonCampaignEvidenceRecordStore(root / "evidence")
            service = CampaignEvidenceRecordService(
                timeline=timeline,
                records=records,
            )

            first_event = timeline.append(_event(1))
            first = service.record(
                "campaign-evidence",
                _evidence("report"),
                recorded_at=BASE_TIME + timedelta(minutes=1),
                related_event_id=first_event.event.event_id,
            )
            second_event = timeline.append(_event(2))
            second = service.record(
                "campaign-evidence",
                _evidence("screenshot", digest="b" * 64),
                recorded_at=BASE_TIME + timedelta(minutes=2),
                related_event_id=second_event.event.event_id,
            )

            self.assertEqual(first.sequence, 1)
            self.assertEqual(first.timeline_head_hash, first_event.entry_hash)
            self.assertEqual(second.sequence, 2)
            self.assertEqual(second.previous_hash, first.record_hash)
            self.assertEqual(second.timeline_head_hash, second_event.entry_hash)
            self.assertEqual(records.get("campaign-evidence", "report"), first)
            self.assertEqual(
                records.list("campaign-evidence"),
                (first, second),
            )
            verification = records.verify("campaign-evidence")
            self.assertEqual(verification.record_count, 2)
            self.assertEqual(verification.head_hash, second.record_hash)
            self.assertEqual(
                verification.latest_timeline_head_hash,
                second_event.entry_hash,
            )
            replayed = []
            self.assertEqual(
                records.replay("campaign-evidence", replayed.append),
                2,
            )
            self.assertEqual(replayed, [first, second])
            self.assertFalse(any(root.rglob("*.tmp")))

    def test_recording_evidence_does_not_modify_event_timeline(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            timeline = JsonCampaignTimelineStore(root / "timeline")
            records = JsonCampaignEvidenceRecordStore(root / "evidence")
            service = CampaignEvidenceRecordService(
                timeline=timeline,
                records=records,
            )
            event = timeline.append(_event(1))

            service.record(
                "campaign-evidence",
                _evidence("receipt"),
                recorded_at=BASE_TIME + timedelta(minutes=1),
                related_event_id=event.event.event_id,
            )

            self.assertEqual(timeline.list("campaign-evidence"), (event,))
            self.assertEqual(timeline.verify("campaign-evidence").entry_count, 1)

    def test_identical_retry_is_idempotent_and_changed_identity_conflicts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            timeline = JsonCampaignTimelineStore(root / "timeline")
            timeline.append(_event(1))
            records = JsonCampaignEvidenceRecordStore(root / "evidence")
            service = CampaignEvidenceRecordService(
                timeline=timeline,
                records=records,
            )
            evidence = _evidence("report")
            recorded_at = BASE_TIME + timedelta(minutes=1)

            first = service.record(
                "campaign-evidence",
                evidence,
                recorded_at=recorded_at,
            )
            self.assertEqual(
                service.record(
                    "campaign-evidence",
                    evidence,
                    recorded_at=recorded_at,
                ),
                first,
            )
            with self.assertRaises(EvidenceRecordConflictError):
                service.record(
                    "campaign-evidence",
                    _evidence("report", digest="c" * 64),
                    recorded_at=recorded_at,
                )
            with self.assertRaises(EvidenceRecordConflictError):
                service.record(
                    "campaign-evidence",
                    evidence,
                    recorded_at=recorded_at + timedelta(seconds=1),
                )

    def test_missing_timeline_or_related_event_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            timeline = JsonCampaignTimelineStore(root / "timeline")
            service = CampaignEvidenceRecordService(
                timeline=timeline,
                records=JsonCampaignEvidenceRecordStore(root / "evidence"),
            )
            with self.assertRaises(EvidenceRecordConflictError):
                service.record(
                    "campaign-evidence",
                    _evidence("report"),
                    recorded_at=BASE_TIME,
                )

            timeline.append(_event(1))
            with self.assertRaises(EvidenceRecordConflictError):
                service.record(
                    "campaign-evidence",
                    _evidence("report"),
                    recorded_at=BASE_TIME + timedelta(minutes=1),
                    related_event_id="campaign-evidence:missing",
                )

    def test_record_validation_is_strict_and_round_trips(self) -> None:
        evidence = _evidence("report")
        record = CampaignEvidenceRecord(
            campaign_id="campaign-evidence",
            sequence=1,
            recorded_at=BASE_TIME,
            evidence=evidence,
            timeline_head_hash="d" * 64,
        )
        self.assertEqual(CampaignEvidenceRecord.from_dict(record.to_dict()), record)

        with self.assertRaises(CampaignValidationError):
            CampaignEvidenceRecord(
                campaign_id="campaign-evidence",
                sequence=0,
                recorded_at=BASE_TIME,
                evidence=evidence,
                timeline_head_hash="d" * 64,
            )
        with self.assertRaises(CampaignValidationError):
            CampaignEvidenceRecord(
                campaign_id="campaign-evidence",
                sequence=1,
                recorded_at=BASE_TIME.replace(tzinfo=None),
                evidence=evidence,
                timeline_head_hash="d" * 64,
            )
        with self.assertRaises(CampaignValidationError):
            CampaignEvidenceRecord(
                campaign_id="campaign-evidence",
                sequence=2,
                recorded_at=BASE_TIME,
                evidence=evidence,
                timeline_head_hash="d" * 64,
            )
        with self.assertRaises(CampaignValidationError):
            CampaignEvidenceRecord(
                campaign_id="campaign-evidence",
                sequence=1,
                recorded_at=BASE_TIME,
                evidence=evidence,
                timeline_head_hash="not-a-digest",
            )

    def test_content_tampering_and_filename_rebinding_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store = JsonCampaignEvidenceRecordStore(root)
            record = CampaignEvidenceRecord(
                campaign_id="campaign-evidence",
                sequence=1,
                recorded_at=BASE_TIME,
                evidence=_evidence("report"),
                timeline_head_hash="d" * 64,
            )
            store.append(record)
            path = next(root.rglob("*.evidence.json"))
            payload = json.loads(path.read_text(encoding="utf-8"))
            payload["evidence"]["size_bytes"] = 999
            path.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaises(EvidenceRecordIntegrityError):
                store.list("campaign-evidence")

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store = JsonCampaignEvidenceRecordStore(root)
            record = CampaignEvidenceRecord(
                campaign_id="campaign-evidence",
                sequence=1,
                recorded_at=BASE_TIME,
                evidence=_evidence("report"),
                timeline_head_hash="d" * 64,
            )
            store.append(record)
            path = next(root.rglob("*.evidence.json"))
            path.rename(path.with_name(f"{1:020d}-{'0' * 64}.evidence.json"))
            with self.assertRaises(EvidenceRecordIntegrityError):
                store.list("campaign-evidence")

    def test_orphan_temp_is_ignored_but_corrupt_final_record_is_not(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store = JsonCampaignEvidenceRecordStore(root)
            record = CampaignEvidenceRecord(
                campaign_id="campaign-evidence",
                sequence=1,
                recorded_at=BASE_TIME,
                evidence=_evidence("report"),
                timeline_head_hash="d" * 64,
            )
            store.append(record)
            campaign_dir = next(root.iterdir())
            (campaign_dir / ".interrupted.tmp").write_text(
                '{"partial":',
                encoding="utf-8",
            )
            self.assertEqual(store.list("campaign-evidence"), (record,))

            final_path = next(campaign_dir.glob("*.evidence.json"))
            final_path.write_text('{"partial":', encoding="utf-8")
            with self.assertRaises(EvidenceRecordStoreError):
                store.list("campaign-evidence")

    def test_construction_is_dormant_and_contracts_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            timeline = JsonCampaignTimelineStore(root / "timeline")
            records = JsonCampaignEvidenceRecordStore(root / "evidence")
            CampaignEvidenceRecordService(timeline=timeline, records=records)
            self.assertEqual(list(root.iterdir()), [])

        with self.assertRaises(TypeError):
            CampaignEvidenceRecordService(
                timeline=object(),  # type: ignore[arg-type]
                records=object(),  # type: ignore[arg-type]
            )
        with self.assertRaises(TypeError):
            JsonCampaignEvidenceRecordStore("unused").append(object())  # type: ignore[arg-type]
        with self.assertRaises(TypeError):
            JsonCampaignEvidenceRecordStore("unused").replay(
                "campaign-evidence",
                None,  # type: ignore[arg-type]
            )


if __name__ == "__main__":
    unittest.main()
