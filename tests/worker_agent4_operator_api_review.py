#!/usr/bin/env python3
"""Regression coverage for post-merge A4-14 operator API review findings."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "worker"))

from app.agent4.composition import compose_agent4_runtime  # noqa: E402
from app.agent4.domain import CampaignValidationError  # noqa: E402
from app.agent4.handoff import (  # noqa: E402
    CampaignDispatchAcknowledgement,
    CampaignDispatchOutcome,
    CampaignDispatchRequest,
    CampaignSignalAcknowledgement,
    CampaignSignalRequest,
    DispatchOutcomeKind,
)
from app.agent4.operator import Agent4OperatorReadService  # noqa: E402
from app.agent4.operator_api import build_agent4_operator_router  # noqa: E402
from app.agent4.operator_read_context import (  # noqa: E402
    compose_agent4_operator_read_context,
)
from app.agent4.production_mount import mount_agent4_operator  # noqa: E402
from app.agent4.repository import CampaignRepositoryError  # noqa: E402
from app.agent4.timeline import JsonCampaignTimelineStore  # noqa: E402
from app.agent4.timeline_query import CampaignTimelineQueryService  # noqa: E402

PREFIX = "/experimental/agent4/operator"


class _Executor:
    def __init__(self) -> None:
        self.outcomes: dict[str, CampaignDispatchOutcome] = {}

    def dispatch(
        self,
        request: CampaignDispatchRequest,
    ) -> CampaignDispatchAcknowledgement:
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


def _compose(root: Path):
    return compose_agent4_runtime(
        root,
        executor=_Executor(),
        resource_capacities={"gpu": 1},
        resource_resolver=lambda spec: {"gpu": 1},
        resource_lease_ttl=timedelta(minutes=15),
    )


class Agent4OperatorApiReviewTests(unittest.TestCase):
    def test_mount_rejects_parallel_timeline_and_query_services(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            context = compose_agent4_operator_read_context(root / "runtime")
            parallel_timeline = JsonCampaignTimelineStore(root / "parallel-timeline")
            mismatched_contexts = {
                "timeline": replace(
                    context,
                    operator=Agent4OperatorReadService(
                        scheduler=context.scheduler,
                        timeline=parallel_timeline,
                        query=context.query,
                    ),
                ),
                "query": replace(
                    context,
                    operator=Agent4OperatorReadService(
                        scheduler=context.scheduler,
                        timeline=context.timeline,
                        query=CampaignTimelineQueryService(context.timeline),
                    ),
                ),
            }

            for label, mismatched in mismatched_contexts.items():
                with self.subTest(label=label):
                    app = FastAPI()
                    baseline = len(app.router.routes)
                    with patch.dict(
                        os.environ,
                        {"KALIV_AGENT4_OPERATOR_API": "1"},
                        clear=False,
                    ):
                        with self.assertRaises(CampaignValidationError):
                            mount_agent4_operator(app, mismatched)
                    self.assertEqual(len(app.router.routes), baseline)
                    self.assertFalse(
                        getattr(app.state, "agent4_operator_mounted", False)
                    )

    def test_campaign_repository_failures_are_sanitized_for_every_get_route(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            context = _compose(Path(directory) / "runtime")
            app = FastAPI()
            # Repository fault injection needs the mutable full runtime. Exercise
            # the transport adapter directly; production_mount accepts only the
            # narrow read-only context after A4-25a.
            app.include_router(
                build_agent4_operator_router(
                    context.operator,
                    context.evidence_operator,
                )
            )
            client = TestClient(app)
            internal_message = "corrupt envelope at private filesystem path"

            with patch.object(
                context.repository,
                "list",
                side_effect=CampaignRepositoryError(internal_message),
            ):
                response = client.get(f"{PREFIX}/campaigns")
            self.assertEqual(response.status_code, 503)
            self.assertEqual(
                response.json()["detail"],
                "agent4 operator read unavailable",
            )
            self.assertNotIn(internal_message, response.text)

            paths = (
                f"{PREFIX}/campaigns/review-fixture",
                f"{PREFIX}/campaigns/review-fixture/timeline",
                f"{PREFIX}/campaigns/review-fixture/evidence",
                f"{PREFIX}/campaigns/review-fixture/evidence/verification",
                f"{PREFIX}/campaigns/review-fixture/evidence/item",
            )
            for path in paths:
                with self.subTest(path=path):
                    with patch.object(
                        context.repository,
                        "get",
                        side_effect=CampaignRepositoryError(internal_message),
                    ):
                        response = client.get(path)
                    self.assertEqual(response.status_code, 503)
                    self.assertEqual(
                        response.json()["detail"],
                        "agent4 operator read unavailable",
                    )
                    self.assertNotIn(internal_message, response.text)


if __name__ == "__main__":
    unittest.main()
