#!/usr/bin/env python3
"""A4-19 HTTP contracts for campaign-list snapshot paging."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "worker"))

from app.agent4 import CampaignSpec, compose_agent4_runtime  # noqa: E402
from app.agent4.handoff import (  # noqa: E402
    CampaignDispatchAcknowledgement,
    CampaignDispatchOutcome,
    CampaignDispatchRequest,
    CampaignSignalAcknowledgement,
    CampaignSignalRequest,
    DispatchOutcomeKind,
)
from app.agent4.operator_api import build_agent4_operator_router  # noqa: E402

BASE_TIME = datetime(2026, 8, 9, 11, 0, tzinfo=timezone.utc)
PREFIX = "/experimental/agent4/operator/campaigns"


class _Clock:
    def now(self) -> datetime:
        return BASE_TIME


class _Executor:
    def dispatch(
        self,
        request: CampaignDispatchRequest,
    ) -> CampaignDispatchAcknowledgement:
        return CampaignDispatchAcknowledgement(
            dispatch_id=request.dispatch_id,
            runtime_reference=f"runtime:{request.campaign_id}",
        )

    def signal(
        self,
        request: CampaignSignalRequest,
    ) -> CampaignSignalAcknowledgement:
        return CampaignSignalAcknowledgement(signal_id=request.signal_id)

    def query_outcome(self, dispatch_id: str) -> CampaignDispatchOutcome:
        return CampaignDispatchOutcome(
            dispatch_id=dispatch_id,
            kind=DispatchOutcomeKind.RUNNING,
        )


def _cursor(value: dict[str, object]) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )


class CampaignListApiTests(unittest.TestCase):
    def _client(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        context = compose_agent4_runtime(
            Path(directory.name) / "runtime",
            executor=_Executor(),
            resource_capacities={"operator-read": 1},
            resource_resolver=lambda _spec: {"operator-read": 1},
            clock=_Clock(),
        )
        for index in range(1, 5):
            context.scheduler.submit(
                CampaignSpec(
                    campaign_id=f"campaign-{index}",
                    name=f"Campaign {index}",
                    workflow="agent3.read",
                    created_at=BASE_TIME + timedelta(minutes=index),
                )
            )
        app = FastAPI()
        # This test deliberately needs a mutable full runtime so it can change
        # campaign state between requests. Mount the transport adapter directly;
        # the production mount is reserved for Agent4OperatorReadContext only.
        app.include_router(
            build_agent4_operator_router(
                context.operator,
                context.evidence_operator,
            )
        )
        return context, TestClient(app)

    def test_envelope_is_backward_compatible_and_pages_stably(self) -> None:
        _context, client = self._client()
        first = client.get(PREFIX, params={"limit": "2"})
        self.assertEqual(first.status_code, 200)
        body = first.json()
        self.assertEqual(
            [item["record"]["spec"]["campaign_id"] for item in body["campaigns"]],
            ["campaign-4", "campaign-3"],
        )
        self.assertTrue(body["has_more"])
        self.assertEqual(body["start_cursor"]["position"], 0)
        self.assertEqual(body["next_cursor"]["position"], 2)
        self.assertEqual(body["head_cursor"]["position"], 4)

        second = client.get(
            PREFIX,
            params={
                "after": _cursor(body["next_cursor"]),
                "snapshot_head": _cursor(body["head_cursor"]),
                "limit": "2",
            },
        )
        self.assertEqual(second.status_code, 200)
        second_body = second.json()
        self.assertEqual(
            [item["record"]["spec"]["campaign_id"] for item in second_body["campaigns"]],
            ["campaign-2", "campaign-1"],
        )
        self.assertFalse(second_body["has_more"])
        self.assertEqual(second_body["next_cursor"], body["head_cursor"])

    def test_status_filter_is_bound_into_http_cursor(self) -> None:
        _context, client = self._client()
        first = client.get(
            PREFIX,
            params=[("status", "queued"), ("limit", "1")],
        ).json()
        drift = client.get(
            PREFIX,
            params={
                "after": _cursor(first["next_cursor"]),
                "snapshot_head": _cursor(first["head_cursor"]),
                "status": "running",
                "limit": "1",
            },
        )
        self.assertEqual(drift.status_code, 422)
        self.assertEqual(
            drift.json()["detail"],
            "agent4 operator request rejected",
        )
        self.assertNotIn("queued", drift.text)

    def test_snapshot_change_between_pages_is_redacted_422(self) -> None:
        context, client = self._client()
        first = client.get(PREFIX, params={"limit": "1"}).json()
        context.scheduler.submit(
            CampaignSpec(
                campaign_id="campaign-5",
                name="Campaign 5",
                workflow="agent3.read",
                created_at=BASE_TIME + timedelta(minutes=5),
            )
        )
        stale = client.get(
            PREFIX,
            params={
                "after": _cursor(first["next_cursor"]),
                "snapshot_head": _cursor(first["head_cursor"]),
                "limit": "1",
            },
        )
        self.assertEqual(stale.status_code, 422)
        self.assertEqual(
            stale.json()["detail"],
            "agent4 operator request rejected",
        )
        self.assertNotIn("snapshot", stale.text)
        self.assertNotIn("campaign-5", stale.text)

    def test_repeated_or_malformed_list_cursor_is_rejected(self) -> None:
        _context, client = self._client()
        repeated = client.get(
            PREFIX + "?after=%7B%7D&after=%7B%7D",
        )
        self.assertEqual(repeated.status_code, 422)
        malformed = client.get(PREFIX, params={"after": "not-json"})
        self.assertEqual(malformed.status_code, 422)
        missing_head = client.get(
            PREFIX,
            params={
                "after": _cursor(
                    client.get(PREFIX, params={"limit": "1"}).json()["next_cursor"]
                )
            },
        )
        self.assertEqual(missing_head.status_code, 422)


if __name__ == "__main__":
    unittest.main()
