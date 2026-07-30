#!/usr/bin/env python3
"""A4-06 append-only timeline and evidence contract tests."""

from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.agent4 import CampaignEvent, CampaignEventKind
from app.agent4.timeline import (
    CampaignEvidence,
    CampaignEvidenceArtifact,
    CampaignTimelineConflictError,
    CampaignTimelineIntegrityError,
    CampaignTimelineEntryType,
    DurableCampaignEventBus,
    GENESIS_HASH,
    JsonlCampaignTimelineStore,
)


BASE_TIME = datetime(2026, 7, 30, 12, 0, tzinfo=timezone.utc)


class Agent4TimelineTests(unittest.TestCase):
    def event(
        self,
        sequence: int,
        *,
        campaign_id: str = "campaign-timeline",
    ) -> CampaignEvent:
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

    def evidence(
        self,
        evidence_id: str,
        *,
        campaign_id: str = "campaign-timeline",
        offset: int = 10,
    ) -> CampaignEvidence:
        return CampaignEvidence(
            evidence_id=evidence_id,
            campaign_id=campaign_id,
            category="physical-proof",
            source="operator",
            recorded_at=BASE_TIME + timedelta(seconds=offset),
            payload={"result": "observed", "checks": ["hash", "size"]},
            artifacts=(
                CampaignEvidenceArtifact(
                    uri=f"file:///evidence/{evidence_id}.json",
                    sha256=hashlib.sha256(evidence_id.encode("utf-8")).hexdigest(),
                    size_bytes=128,
                    media_type="application/json",
                ),
            ),
        )

    def test_constructor_is_dormant_and_first_append_creates_one_bound_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "timeline"
            store = JsonlCampaignTimelineStore(root)
            self.assertFalse(root.exists())

            entry = store.append_event(self.event(1))

            self.assertTrue(root.is_dir())
            self.assertEqual(entry.timeline_sequence, 1)
            self.assertEqual(entry.previous_hash, GENESIS_HASH)
            self.assertEqual(len(tuple(root.iterdir())), 1)

    def test_events_and_evidence_interleave_with_separate_ordering(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = JsonlCampaignTimelineStore(directory)
            first = store.append_event(self.event(1))
            proof = store.append_evidence(self.evidence("proof-1"))
            second = store.append_event(self.event(2))

            history = store.history("campaign-timeline")
            self.assertEqual(
                [item.timeline_sequence for item in history],
                [1, 2, 3],
            )
            self.assertEqual(
                [item.entry_type for item in history],
                [
                    CampaignTimelineEntryType.EVENT,
                    CampaignTimelineEntryType.EVIDENCE,
                    CampaignTimelineEntryType.EVENT,
                ],
            )
            self.assertEqual(proof.previous_hash, first.content_hash)
            self.assertEqual(second.previous_hash, proof.content_hash)
            self.assertEqual(
                [item.sequence for item in store.events("campaign-timeline")],
                [1, 2],
            )
            self.assertEqual(
                [item.evidence_id for item in store.evidence("campaign-timeline")],
                ["proof-1"],
            )

    def test_restart_replays_history_and_continues_both_sequences(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            first_store = JsonlCampaignTimelineStore(directory)
            first_bus = DurableCampaignEventBus(first_store)
            first_bus.record(
                "campaign-timeline",
                CampaignEventKind.CREATED,
                occurred_at=BASE_TIME,
            )
            first_store.append_evidence(self.evidence("proof-restart"))

            second_store = JsonlCampaignTimelineStore(directory)
            second_bus = DurableCampaignEventBus(second_store)
            event = second_bus.record(
                "campaign-timeline",
                CampaignEventKind.STARTED,
                occurred_at=BASE_TIME + timedelta(minutes=1),
            )

            self.assertEqual(event.sequence, 2)
            self.assertEqual(
                second_store.latest_timeline_sequence("campaign-timeline"),
                3,
            )
            self.assertEqual(second_bus.latest_sequence("campaign-timeline"), 2)

    def test_bus_durably_appends_before_notifying_handlers(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = JsonlCampaignTimelineStore(directory)
            bus = DurableCampaignEventBus(store)
            observed: list[tuple[int, int]] = []

            def handler(event: CampaignEvent) -> None:
                observed.append(
                    (
                        event.sequence,
                        store.latest_timeline_sequence(event.campaign_id),
                    )
                )

            bus.subscribe(handler)
            event = bus.record(
                "campaign-timeline",
                CampaignEventKind.CREATED,
                occurred_at=BASE_TIME,
            )

            self.assertEqual(observed, [(1, 1)])
            self.assertEqual(bus.history("campaign-timeline"), (event,))

    def test_duplicate_ids_and_event_sequence_gaps_fail_without_append(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = JsonlCampaignTimelineStore(directory)
            store.append_event(self.event(1))
            baseline = store.history("campaign-timeline")

            with self.assertRaises(CampaignTimelineConflictError):
                store.append_event(self.event(1))
            with self.assertRaises(CampaignTimelineConflictError):
                store.append_event(self.event(3))
            store.append_evidence(self.evidence("proof-duplicate"))
            with self.assertRaises(CampaignTimelineConflictError):
                store.append_evidence(
                    self.evidence("proof-duplicate", offset=11)
                )

            self.assertEqual(store.history("campaign-timeline")[:1], baseline)
            self.assertEqual(len(store.history("campaign-timeline")), 2)

    def test_hash_chain_tampering_and_truncated_tail_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = JsonlCampaignTimelineStore(directory)
            store.append_event(self.event(1))
            store.append_evidence(self.evidence("proof-tamper"))
            path = next(Path(directory).iterdir())

            lines = path.read_text(encoding="utf-8").splitlines()
            changed = json.loads(lines[0])
            changed["item"]["payload"]["sequence"] = 999
            lines[0] = json.dumps(
                changed,
                sort_keys=True,
                separators=(",", ":"),
            )
            path.write_text("\n".join(lines) + "\n", encoding="utf-8")
            with self.assertRaises(CampaignTimelineIntegrityError):
                store.verify("campaign-timeline")

        with tempfile.TemporaryDirectory() as directory:
            store = JsonlCampaignTimelineStore(directory)
            store.append_event(self.event(1))
            path = next(Path(directory).iterdir())
            path.write_bytes(path.read_bytes()[:-1])
            with self.assertRaises(CampaignTimelineIntegrityError):
                store.history("campaign-timeline")

    def test_filename_binding_rejects_moved_campaign_timeline(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = JsonlCampaignTimelineStore(directory)
            store.append_event(self.event(1, campaign_id="campaign-a"))
            source = next(Path(directory).iterdir())

            other_store = JsonlCampaignTimelineStore(directory)
            target = other_store._path("campaign-b")
            source.replace(target)

            with self.assertRaises(CampaignTimelineIntegrityError):
                other_store.history("campaign-b")

    def test_evidence_is_immutable_json_metadata_not_embedded_binary(self) -> None:
        payload = {"nested": {"values": [1, 2]}}
        evidence = CampaignEvidence(
            evidence_id="proof-json",
            campaign_id="campaign-timeline",
            category="diagnostic",
            source="test",
            recorded_at=BASE_TIME,
            payload=payload,
        )
        payload["nested"]["values"].append(3)
        self.assertEqual(
            evidence.to_dict()["payload"],
            {"nested": {"values": [1, 2]}},
        )

        with self.assertRaises(Exception):
            CampaignEvidence(
                evidence_id="proof-bytes",
                campaign_id="campaign-timeline",
                category="diagnostic",
                source="test",
                recorded_at=BASE_TIME,
                payload={"blob": b"not-embedded"},
            )

    def test_threaded_appends_are_serialized(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = JsonlCampaignTimelineStore(directory)

            def append(index: int) -> int:
                entry = store.append_evidence(
                    self.evidence(f"proof-{index}", offset=index + 1)
                )
                return entry.timeline_sequence

            with ThreadPoolExecutor(max_workers=8) as executor:
                sequences = sorted(executor.map(append, range(16)))

            self.assertEqual(sequences, list(range(1, 17)))
            self.assertEqual(len(store.verify("campaign-timeline")), 16)


if __name__ == "__main__":
    unittest.main()
