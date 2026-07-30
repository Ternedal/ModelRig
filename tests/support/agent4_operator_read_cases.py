#!/usr/bin/env python3
"""A4-08 bounded operator read-model contract tests."""

from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.agent4 import (
    MAX_OPERATOR_CAMPAIGNS,
    MAX_OPERATOR_TIMELINE_ENTRIES,
    Agent4OperatorReadService,
    CampaignEvidence,
    CampaignEventKind,
    CampaignNotFoundError,
    CampaignSpec,
    CampaignStatus,
    CampaignValidationError,
    compose_agent4_runtime,
)


BASE_TIME = datetime(2026, 7, 30, 21, 30, tzinfo=timezone.utc)


class _Clock:
    def __init__(self, value: datetime = BASE_TIME) -> None:
        self.value = value

    def now(self) -> datetime:
        return self.value


class _Executor:
    def __init__(self) -> None:
        self.dispatched: list[str] = []

    def dispatch(self, spec, state) -> str:
        self.dispatched.append(spec.campaign_id)
        return f"runtime:{spec.campaign_id}:{state.attempt}"

    def signal(self, campaign_id: str, command: str) -> None:
        return None


class Agent4OperatorReadTests(unittest.TestCase):
    def compose(self, root: Path):
        clock = _Clock()
        context = compose_agent4_runtime(
            root,
            executor=_Executor(),
            resource_capacities={"gpu": 1},
            resource_resolver=lambda spec: {"gpu": 1},
            clock=clock,
            resource_lease_ttl=timedelta(minutes=15),
        )
        return context, clock

    @staticmethod
    def spec(
        campaign_id: str,
        *,
        created_at: datetime = BASE_TIME,
    ) -> CampaignSpec:
        return CampaignSpec(
            campaign_id=campaign_id,
            name=f"Campaign {campaign_id}",
            workflow="agent3.write-pilot",
            created_at=created_at,
            max_attempts=2,
        )

    def test_operator_is_dormant_and_uses_the_shared_runtime_graph(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "runtime"
            context, _ = self.compose(root)

            self.assertIsInstance(context.operator, Agent4OperatorReadService)
            self.assertIs(context.operator.scheduler, context.scheduler)
            self.assertIs(context.operator.timeline, context.timeline)
            self.assertEqual(context.operator.list_campaigns(), ())
            self.assertFalse(root.exists())

    def test_campaign_overview_reports_verified_timeline_counters(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            context, _ = self.compose(Path(directory) / "runtime")
            context.scheduler.submit(self.spec("campaign-overview"))
            context.scheduler.dispatch_ready()
            context.checkpoints.checkpoint(
                "campaign-overview",
                "checkpoint-1",
                {"progress": 50},
            )
            context.timeline.append_evidence(
                CampaignEvidence(
                    evidence_id="evidence-1",
                    campaign_id="campaign-overview",
                    category="operator-proof",
                    source="agent4-test",
                    recorded_at=BASE_TIME,
                    payload={"verified": True},
                )
            )

            overview = context.operator.campaign("campaign-overview")
            history = context.timeline.history("campaign-overview")

            self.assertEqual(overview.campaign_id, "campaign-overview")
            self.assertEqual(overview.status, CampaignStatus.RUNNING)
            self.assertEqual(overview.timeline_entries, 4)
            self.assertEqual(overview.event_entries, 3)
            self.assertEqual(overview.evidence_entries, 1)
            self.assertEqual(overview.latest_timeline_hash, history[-1].content_hash)

    def test_list_is_bounded_newest_first_and_status_filtered(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            context, _ = self.compose(Path(directory) / "runtime")
            context.scheduler.submit(self.spec("campaign-a"))
            context.scheduler.submit(
                self.spec(
                    "campaign-b",
                    created_at=BASE_TIME + timedelta(seconds=1),
                )
            )
            context.scheduler.dispatch_ready()

            all_campaigns = context.operator.list_campaigns()
            running = context.operator.list_campaigns(statuses=CampaignStatus.RUNNING)
            queued = context.operator.list_campaigns(statuses="queued")
            limited = context.operator.list_campaigns(limit=1)

            self.assertEqual(
                [item.campaign_id for item in all_campaigns],
                ["campaign-b", "campaign-a"],
            )
            self.assertEqual([item.campaign_id for item in running], ["campaign-a"])
            self.assertEqual([item.campaign_id for item in queued], ["campaign-b"])
            self.assertEqual([item.campaign_id for item in limited], ["campaign-b"])

            for invalid in (0, MAX_OPERATOR_CAMPAIGNS + 1, True):
                with self.assertRaises(CampaignValidationError):
                    context.operator.list_campaigns(limit=invalid)
            with self.assertRaises(CampaignValidationError):
                context.operator.list_campaigns(statuses="unknown")

    def test_timeline_pages_hold_a_stable_snapshot_while_clean_appends_continue(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            context, _ = self.compose(Path(directory) / "runtime")
            context.scheduler.submit(self.spec("campaign-page"))

            first = context.operator.timeline_page("campaign-page", limit=1)
            self.assertEqual(
                [entry.item.kind for entry in first.entries],
                [CampaignEventKind.CREATED],
            )
            self.assertEqual(first.next_sequence, 1)
            self.assertEqual(first.snapshot_sequence, 1)
            self.assertFalse(first.has_more)

            context.scheduler.dispatch_ready()

            stable = context.operator.timeline_page(
                "campaign-page",
                after_sequence=first.next_sequence,
                limit=1,
                snapshot_sequence=first.snapshot_sequence,
            )
            self.assertEqual(stable.entries, ())
            self.assertEqual(stable.next_sequence, 1)
            self.assertFalse(stable.has_more)

            fresh = context.operator.timeline_page(
                "campaign-page",
                after_sequence=first.next_sequence,
                limit=1,
            )
            self.assertEqual(
                [entry.item.kind for entry in fresh.entries],
                [CampaignEventKind.STARTED],
            )
            self.assertEqual(fresh.snapshot_sequence, 2)
            self.assertEqual(fresh.remaining, 0)

    def test_timeline_query_rejects_unknown_and_invalid_bounds(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            context, _ = self.compose(Path(directory) / "runtime")
            context.scheduler.submit(self.spec("campaign-bounds"))

            with self.assertRaises(CampaignNotFoundError):
                context.operator.timeline_page("missing")
            with self.assertRaises(CampaignValidationError):
                context.operator.timeline_page("campaign-bounds", after_sequence=-1)
            with self.assertRaises(CampaignValidationError):
                context.operator.timeline_page(
                    "campaign-bounds",
                    after_sequence=1,
                    snapshot_sequence=0,
                )
            with self.assertRaises(CampaignValidationError):
                context.operator.timeline_page(
                    "campaign-bounds",
                    snapshot_sequence=2,
                )
            for invalid in (0, MAX_OPERATOR_TIMELINE_ENTRIES + 1, True):
                with self.assertRaises(CampaignValidationError):
                    context.operator.timeline_page(
                        "campaign-bounds",
                        limit=invalid,
                    )


if __name__ == "__main__":
    unittest.main()
