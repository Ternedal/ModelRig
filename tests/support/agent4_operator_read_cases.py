"""A4-10 bounded B-reference operator read-model contract cases."""

from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.agent4 import (
    MAX_OPERATOR_CAMPAIGNS,
    Agent4OperatorReadService,
    CampaignEvidenceReference,
    CampaignEventKind,
    CampaignNotFoundError,
    CampaignSpec,
    CampaignStatus,
    CampaignTimelineQueryCursor,
    CampaignTimelineQueryCursorError,
    CampaignValidationError,
    compose_agent4_runtime,
)
from app.agent4.handoff import (
    CampaignDispatchAcknowledgement,
    CampaignDispatchOutcome,
    CampaignDispatchRequest,
    CampaignSignalAcknowledgement,
    CampaignSignalRequest,
    DispatchOutcomeKind,
)


BASE_TIME = datetime(2026, 7, 31, 10, 0, tzinfo=timezone.utc)


class _OperatorClock:
    def __init__(self, value: datetime = BASE_TIME) -> None:
        self.value = value

    def now(self) -> datetime:
        return self.value


class _OperatorExecutor:
    def __init__(self) -> None:
        self.dispatched: list[CampaignDispatchRequest] = []
        self.outcomes: dict[str, CampaignDispatchOutcome] = {}

    def dispatch(
        self,
        request: CampaignDispatchRequest,
    ) -> CampaignDispatchAcknowledgement:
        self.dispatched.append(request)
        acknowledgement = CampaignDispatchAcknowledgement(
            dispatch_id=request.dispatch_id,
            runtime_reference=f"runtime:{request.campaign_id}:{request.attempt}",
            evidence_pointer=f"evidence:{request.dispatch_id}",
        )
        self.outcomes[request.dispatch_id] = CampaignDispatchOutcome(
            dispatch_id=request.dispatch_id,
            kind=DispatchOutcomeKind.RUNNING,
            runtime_reference=acknowledgement.runtime_reference,
            evidence_pointer=acknowledgement.evidence_pointer,
        )
        return acknowledgement

    def signal(
        self,
        request: CampaignSignalRequest,
    ) -> CampaignSignalAcknowledgement:
        return CampaignSignalAcknowledgement(
            signal_id=request.signal_id,
            evidence_pointer=f"evidence:{request.signal_id}",
        )

    def query_outcome(self, dispatch_id: str) -> CampaignDispatchOutcome:
        return self.outcomes.get(
            dispatch_id,
            CampaignDispatchOutcome(
                dispatch_id=dispatch_id,
                kind=DispatchOutcomeKind.UNKNOWN,
            ),
        )


class Agent4OperatorReadTests(unittest.TestCase):
    def _operator_compose(self, root: Path):
        clock = _OperatorClock()
        context = compose_agent4_runtime(
            root,
            executor=_OperatorExecutor(),
            resource_capacities={"gpu": 1},
            resource_resolver=lambda spec: {"gpu": 1},
            clock=clock,
            resource_lease_ttl=timedelta(minutes=15),
        )
        return context, clock

    @staticmethod
    def _operator_spec(
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
            context, _ = self._operator_compose(root)

            self.assertIsInstance(context.operator, Agent4OperatorReadService)
            self.assertIs(context.operator.scheduler, context.scheduler)
            self.assertIs(context.operator.timeline, context.timeline)
            self.assertIs(context.operator.query, context.query)
            self.assertEqual(context.operator.list_campaigns(), ())
            self.assertFalse(root.exists())

    def test_overview_reports_verified_B_timeline_counters(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            context, clock = self._operator_compose(
                Path(directory) / "runtime"
            )
            context.scheduler.submit(
                self._operator_spec("campaign-overview")
            )
            context.scheduler.dispatch_ready()
            context.checkpoints.checkpoint(
                "campaign-overview",
                "checkpoint-1",
                {"progress": 50},
            )
            evidence = CampaignEvidenceReference(
                evidence_id="operator-proof",
                media_type="application/json",
                location="evidence/operator-proof.json",
                sha256="a" * 64,
                size_bytes=128,
            )
            context.event_recorder.record_with_evidence(
                "campaign-overview",
                CampaignEventKind.CHECKPOINTED,
                occurred_at=clock.now(),
                payload={"source": "operator-test"},
                evidence=(evidence,),
            )

            overview = context.operator.campaign("campaign-overview")
            latest = context.timeline.latest("campaign-overview")

            self.assertEqual(overview.campaign_id, "campaign-overview")
            self.assertEqual(overview.status, CampaignStatus.RUNNING)
            self.assertEqual(overview.timeline_entries, 6)
            self.assertEqual(overview.event_entries, 6)
            self.assertEqual(overview.evidence_entries, 1)
            self.assertIsNotNone(latest)
            assert latest is not None
            self.assertEqual(
                overview.latest_timeline_hash,
                latest.entry_hash,
            )

    def test_list_is_newest_first_bounded_and_status_filter_is_correct(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            context, _ = self._operator_compose(
                Path(directory) / "runtime"
            )
            context.scheduler.submit(self._operator_spec("campaign-a"))
            context.scheduler.submit(self._operator_spec("campaign-b"))
            dispatched = context.scheduler.dispatch_ready()
            self.assertIsNotNone(dispatched)
            assert dispatched is not None
            self.assertEqual(dispatched.record.spec.campaign_id, "campaign-a")

            all_campaigns = context.operator.list_campaigns()
            running = context.operator.list_campaigns(
                statuses=CampaignStatus.RUNNING
            )
            queued = context.operator.list_campaigns(statuses="queued")
            limited = context.operator.list_campaigns(limit=1)

            self.assertEqual(
                [item.campaign_id for item in all_campaigns],
                ["campaign-b", "campaign-a"],
            )
            self.assertEqual(
                [item.campaign_id for item in running],
                ["campaign-a"],
            )
            self.assertEqual(
                [item.campaign_id for item in queued],
                ["campaign-b"],
            )
            self.assertEqual(
                [item.campaign_id for item in limited],
                ["campaign-b"],
            )

            for invalid in (0, MAX_OPERATOR_CAMPAIGNS + 1, True):
                with self.assertRaises(CampaignValidationError):
                    context.operator.list_campaigns(limit=invalid)
            with self.assertRaises(CampaignValidationError):
                context.operator.list_campaigns(statuses="unknown")

    def test_timeline_pages_reuse_B_hash_bound_snapshot_cursors(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            context, _ = self._operator_compose(
                Path(directory) / "runtime"
            )
            context.scheduler.submit(self._operator_spec("campaign-page"))

            first = context.operator.timeline_page(
                "campaign-page",
                limit=1,
            )
            self.assertEqual(
                [entry.event.kind for entry in first.entries],
                [CampaignEventKind.CREATED],
            )
            self.assertEqual(first.next_cursor.sequence, 1)
            self.assertEqual(first.head_cursor.sequence, 1)
            self.assertFalse(first.has_more)

            context.scheduler.dispatch_ready()

            stable = context.operator.timeline_page(
                "campaign-page",
                after=first.next_cursor,
                limit=1,
                snapshot_head=first.head_cursor,
            )
            self.assertEqual(stable.entries, ())
            self.assertEqual(stable.next_cursor.sequence, 1)
            self.assertFalse(stable.has_more)

            fresh = context.operator.timeline_page(
                "campaign-page",
                after=first.next_cursor,
                limit=1,
            )
            self.assertEqual(
                [entry.event.kind for entry in fresh.entries],
                [CampaignEventKind.DISPATCH_REQUESTED],
            )
            self.assertEqual(fresh.head_cursor.sequence, 4)
            self.assertTrue(fresh.has_more)

    def test_operator_rejects_unknown_campaigns_and_invalid_query_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            context, _ = self._operator_compose(
                Path(directory) / "runtime"
            )
            context.scheduler.submit(self._operator_spec("campaign-bounds"))

            with self.assertRaises(CampaignNotFoundError):
                context.operator.timeline_page("missing")
            with self.assertRaises(CampaignValidationError):
                context.operator.timeline_page("campaign-bounds", limit=0)
            with self.assertRaises(CampaignTimelineQueryCursorError):
                context.operator.timeline_page(
                    "campaign-bounds",
                    after=CampaignTimelineQueryCursor(
                        campaign_id="other",
                        sequence=0,
                        entry_hash=None,
                    ),
                )
