#!/usr/bin/env python3
"""Checkpoint envelope, store and lifecycle integration coverage."""

from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from app.agent4 import (
    CampaignCheckpoint,
    CampaignCheckpointService,
    CampaignEventKind,
    CampaignRecord,
    CampaignSpec,
    CampaignState,
    CampaignStatus,
    CheckpointConflictError,
    CheckpointLifecycleError,
    CheckpointStoreError,
    InMemoryCampaignEventBus,
    JsonCampaignRepository,
    JsonCheckpointStore,
)


NOW = datetime(2026, 7, 29, 19, 0, tzinfo=timezone.utc)


class FixedClock:
    def now(self) -> datetime:
        return NOW


class NoopExecutor:
    def dispatch(self, spec, state) -> str:
        return "runtime:1"

    def signal(self, campaign_id: str, command: str) -> None:
        return None


class FailingSecondSaveRepository:
    def __init__(self, delegate: JsonCampaignRepository) -> None:
        self.delegate = delegate
        self.saves = 0

    def save(self, record: CampaignRecord) -> None:
        self.saves += 1
        if self.saves == 2:
            raise OSError("campaign state write failed")
        self.delegate.save(record)

    def get(self, campaign_id: str):
        return self.delegate.get(campaign_id)

    def list(self):
        return self.delegate.list()

    def delete(self, campaign_id: str) -> bool:
        return self.delegate.delete(campaign_id)


class CampaignCheckpointTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        root = Path(self.directory.name)
        self.repository = JsonCampaignRepository(root / "campaigns")
        self.checkpoints = JsonCheckpointStore(root / "checkpoints")
        self.events = InMemoryCampaignEventBus()

    def tearDown(self) -> None:
        self.directory.cleanup()

    def checkpoint(self, checkpoint_id: str = "cp-1", revision: int = 3):
        return CampaignCheckpoint(
            checkpoint_id=checkpoint_id,
            campaign_id="campaign-1",
            campaign_revision=revision,
            created_at=NOW,
            payload={"cursor": 7, "nested": {"items": ["a", "b"]}},
        )

    def running_record(self) -> CampaignRecord:
        return CampaignRecord(
            spec=CampaignSpec(
                campaign_id="campaign-1",
                name="Campaign",
                workflow="agent3.write-pilot",
                created_at=NOW,
            ),
            state=CampaignState(
                campaign_id="campaign-1",
                status=CampaignStatus.RUNNING,
                revision=1,
                attempt=1,
                updated_at=NOW,
            ),
        )

    def service(self, repository=None) -> CampaignCheckpointService:
        return CampaignCheckpointService(
            repository=repository or self.repository,
            checkpoints=self.checkpoints,
            events=self.events,
            clock=FixedClock(),
        )

    def test_checkpoint_round_trips_with_checksum_and_immutable_payload(self) -> None:
        checkpoint = self.checkpoint()
        self.checkpoints.save(checkpoint)

        restored = self.checkpoints.get("campaign-1", "cp-1")

        self.assertEqual(restored, checkpoint)
        self.assertTrue(checkpoint.to_dict()["checksum"].startswith("sha256:"))
        with self.assertRaises(TypeError):
            restored.payload["cursor"] = 8  # type: ignore[index]
        self.assertFalse(any(self.checkpoints.root.glob("*.tmp")))

    def test_checkpoint_identity_is_immutable(self) -> None:
        checkpoint = self.checkpoint()
        self.checkpoints.save(checkpoint)
        with self.assertRaises(CheckpointConflictError):
            self.checkpoints.save(checkpoint)

    def test_tampering_fails_checksum_validation(self) -> None:
        self.checkpoints.save(self.checkpoint())
        path = next(self.checkpoints.root.glob("*.checkpoint.json"))
        raw = json.loads(path.read_text(encoding="utf-8"))
        raw["payload"]["cursor"] = 99
        path.write_text(json.dumps(raw), encoding="utf-8")

        with self.assertRaises(CheckpointStoreError):
            self.checkpoints.get("campaign-1", "cp-1")

    def test_latest_uses_revision_then_creation_order(self) -> None:
        self.checkpoints.save(self.checkpoint("cp-1", 1))
        self.checkpoints.save(self.checkpoint("cp-2", 2))

        self.assertEqual(
            [item.checkpoint_id for item in self.checkpoints.list("campaign-1")],
            ["cp-1", "cp-2"],
        )
        self.assertEqual(self.checkpoints.latest("campaign-1").checkpoint_id, "cp-2")

    def test_service_checkpoint_updates_durable_pointer_and_event(self) -> None:
        self.repository.save(self.running_record())
        service = self.service()

        updated = service.checkpoint("campaign-1", "cp-1", {"cursor": 8})
        restored = service.load("campaign-1")

        self.assertEqual(updated.state.revision, 2)
        self.assertEqual(updated.state.checkpoint_id, "cp-1")
        self.assertEqual(restored.campaign_revision, 2)
        self.assertEqual(restored.payload["cursor"], 8)
        self.assertEqual(
            self.events.history("campaign-1")[-1].kind,
            CampaignEventKind.CHECKPOINTED,
        )

    def test_checkpoint_rejects_missing_campaign_or_inactive_state(self) -> None:
        with self.assertRaises(CheckpointLifecycleError):
            self.service().checkpoint("missing", "cp-1", {})

        queued = CampaignRecord(
            spec=CampaignSpec(
                campaign_id="queued",
                name="Queued",
                workflow="agent3.write-pilot",
                created_at=NOW,
            ),
            state=CampaignState(campaign_id="queued", updated_at=NOW),
        )
        self.repository.save(queued)
        with self.assertRaises(CheckpointLifecycleError):
            self.service().checkpoint("queued", "cp-1", {})

    def test_failed_campaign_pointer_write_compensates_checkpoint(self) -> None:
        failing = FailingSecondSaveRepository(self.repository)
        failing.save(self.running_record())
        service = self.service(repository=failing)

        with self.assertRaises(OSError):
            service.checkpoint("campaign-1", "cp-1", {"cursor": 8})

        self.assertIsNone(self.checkpoints.get("campaign-1", "cp-1"))
        self.assertIsNone(self.repository.get("campaign-1").state.checkpoint_id)


if __name__ == "__main__":
    unittest.main()
