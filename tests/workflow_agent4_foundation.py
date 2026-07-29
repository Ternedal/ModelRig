#!/usr/bin/env python3
"""Composition gate for the dormant Agent 4 foundation."""

from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from app.agent4 import (
    CampaignEvent,
    CampaignEventKind,
    CampaignQueue,
    CampaignRecord,
    CampaignSpec,
    CampaignState,
    CampaignStatus,
    InMemoryCampaignEventBus,
    JsonCampaignRepository,
    transition_campaign,
)


class Agent4FoundationWorkflowTests(unittest.TestCase):
    def test_campaign_can_be_queued_started_persisted_and_observed(self) -> None:
        now = datetime(2026, 7, 29, 15, 0, tzinfo=timezone.utc)
        spec = CampaignSpec(
            campaign_id="foundation-smoke",
            name="Agent 4 foundation smoke",
            workflow="agent3.write-pilot",
            created_at=now,
        )
        queue = CampaignQueue()
        queue.enqueue(spec)
        selected = queue.pop_ready(now)
        self.assertEqual(selected, spec)

        initial = CampaignState(campaign_id=spec.campaign_id, updated_at=now)
        running = transition_campaign(initial, CampaignStatus.RUNNING, occurred_at=now)
        event = CampaignEvent(
            event_id="foundation-smoke-1",
            campaign_id=spec.campaign_id,
            kind=CampaignEventKind.STARTED,
            sequence=1,
            occurred_at=now,
            payload={"attempt": running.attempt},
        )

        bus = InMemoryCampaignEventBus()
        observed: list[CampaignEvent] = []
        bus.subscribe(observed.append)
        bus.publish(event)

        with tempfile.TemporaryDirectory() as directory:
            repository = JsonCampaignRepository(Path(directory))
            repository.save(CampaignRecord(spec=spec, state=running))
            restored = repository.get(spec.campaign_id)

        self.assertIsNotNone(restored)
        self.assertEqual(restored.spec, spec)
        self.assertEqual(restored.state, running)
        self.assertEqual(observed, [event])

    def test_foundation_remains_dormant_without_explicit_composition(self) -> None:
        queue = CampaignQueue()
        bus = InMemoryCampaignEventBus()

        self.assertEqual(len(queue), 0)
        self.assertEqual(bus.history("unknown"), ())
        self.assertEqual(bus.latest_sequence("unknown"), 0)


if __name__ == "__main__":
    unittest.main()
