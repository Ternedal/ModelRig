#!/usr/bin/env python3
"""A4-14 default-off worker-mounted operator read API contracts."""

from __future__ import annotations

import ast
import json
import os
import sys
import tempfile
import threading
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "worker"))

from app.agent4 import (  # noqa: E402
    CampaignEvidenceReference,
    CampaignSpec,
    CampaignStatus,
    CampaignValidationError,
    compose_agent4_runtime,
)
from app.agent4.handoff import (  # noqa: E402
    CampaignDispatchAcknowledgement,
    CampaignDispatchOutcome,
    CampaignDispatchRequest,
    CampaignSignalAcknowledgement,
    CampaignSignalRequest,
    DispatchOutcomeKind,
)
from app.agent4.operator_api import (  # noqa: E402
    OPERATOR_API_SCHEMA,
    OPERATOR_MEDIA_TYPE,
    build_agent4_operator_router,
)
from app.agent4.operator_read_context import (  # noqa: E402
    compose_agent4_operator_read_context,
)
from app.agent4.production_mount import mount_agent4_operator  # noqa: E402

BASE_TIME = datetime(2026, 8, 1, 13, 0, tzinfo=timezone.utc)
PREFIX = "/experimental/agent4/operator"


class _Clock:
    def now(self) -> datetime:
        return BASE_TIME


class _Executor:
    def __init__(self) -> None:
        self.dispatched: list[CampaignDispatchRequest] = []
        self.signals: list[CampaignSignalRequest] = []
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
        self.signals.append(request)
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
        clock=_Clock(),
        resource_lease_ttl=timedelta(minutes=15),
    )


def _cursor(value: dict[str, object]) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _real_routes(app: FastAPI) -> list[object]:
    """Walk FastAPI 0.141's included-router containers without flattening."""

    routes: list[object] = []
    for route in app.routes:
        if type(route).__name__ == "_IncludedRouter":
            original = getattr(route, "original_router", None)
            routes.extend(getattr(original, "routes", ()) if original else ())
        else:
            routes.append(route)
    return routes


def _operator_routes(app: FastAPI) -> list[object]:
    return [
        route
        for route in _real_routes(app)
        if str(getattr(route, "path", "")).startswith(PREFIX)
    ]


class Agent4OperatorApiTests(unittest.TestCase):
    def test_composition_adds_canonical_evidence_reads_without_activation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "runtime"
            before_threads = {(item.ident, item.name) for item in threading.enumerate()}
            context = _compose(root)
            after_threads = {(item.ident, item.name) for item in threading.enumerate()}

            self.assertFalse(root.exists())
            self.assertEqual(context.paths.evidence, root / "evidence")
            self.assertIs(context.evidence_recorder._timeline, context.timeline)
            self.assertIs(context.evidence_recorder._records, context.evidence_records)
            self.assertIs(context.evidence_query.records, context.evidence_records)
            self.assertIs(context.evidence_operator.scheduler, context.scheduler)
            self.assertIs(context.evidence_operator.records, context.evidence_records)
            self.assertIs(context.evidence_operator.query, context.evidence_query)
            self.assertEqual(before_threads, after_threads)

    def test_flag_is_exact_default_off_and_missing_context_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            context = compose_agent4_operator_read_context(
                Path(directory) / "runtime"
            )
            for value in (None, "", "0", "true", "on", " 1 "):
                app = FastAPI()
                environment = {}
                if value is not None:
                    environment["KALIV_AGENT4_OPERATOR_API"] = value
                with patch.dict(os.environ, environment, clear=False):
                    if value is None:
                        os.environ.pop("KALIV_AGENT4_OPERATOR_API", None)
                    self.assertFalse(mount_agent4_operator(app, context))
                self.assertEqual(_operator_routes(app), [])

            app = FastAPI()
            baseline = len(app.routes)
            with patch.dict(
                os.environ,
                {"KALIV_AGENT4_OPERATOR_API": "1"},
                clear=False,
            ):
                with self.assertRaises(CampaignValidationError):
                    mount_agent4_operator(app, None)
            self.assertEqual(len(app.routes), baseline)

    def test_enabled_mount_is_additive_get_only_dormant_and_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "runtime"
            context = compose_agent4_operator_read_context(root)
            app = FastAPI()
            before_threads = {(item.ident, item.name) for item in threading.enumerate()}
            with patch.dict(
                os.environ,
                {"KALIV_AGENT4_OPERATOR_API": "1"},
                clear=False,
            ):
                self.assertTrue(mount_agent4_operator(app, context))
                route_count = len(app.routes)
                self.assertTrue(mount_agent4_operator(app, context))
            after_threads = {(item.ident, item.name) for item in threading.enumerate()}

            routes = _operator_routes(app)
            self.assertEqual(len(app.routes), route_count)
            self.assertEqual(len(routes), 6)
            self.assertTrue(
                all(getattr(route, "methods", set()) == {"GET"} for route in routes)
            )
            self.assertFalse(root.exists())
            self.assertEqual(before_threads, after_threads)
            self.assertIs(app.state.agent4_runtime_context, context)
            self.assertTrue(app.state.agent4_operator_mounted)
            self.assertEqual(
                {
                    path
                    for path in app.openapi()["paths"]
                    if path.startswith(PREFIX)
                },
                {str(getattr(route, "path")) for route in routes},
            )

    def test_api_preserves_canonical_records_evidence_and_cursors(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            context = _compose(Path(directory) / "runtime")
            app = FastAPI()
            # This test intentionally mutates the full runtime to build canonical
            # campaign/timeline/evidence fixtures. Exercise the transport adapter
            # directly; production_mount is restricted to the narrow read context.
            app.include_router(
                build_agent4_operator_router(
                    context.operator,
                    context.evidence_operator,
                )
            )

            campaign_id = "a4-14-read"
            submitted = context.scheduler.submit(
                CampaignSpec(
                    campaign_id=campaign_id,
                    name="A4-14 read fixture",
                    workflow="agent3.write-pilot",
                    created_at=BASE_TIME,
                )
            )
            self.assertIsNotNone(context.scheduler.dispatch_ready())
            latest = context.timeline.latest(campaign_id)
            self.assertIsNotNone(latest)
            assert latest is not None

            first_evidence = context.evidence_recorder.record(
                campaign_id,
                CampaignEvidenceReference(
                    evidence_id="first",
                    media_type="application/json",
                    location="evidence/first.json",
                    sha256="a" * 64,
                    size_bytes=128,
                    metadata={"source": "a4-14-test"},
                ),
                recorded_at=BASE_TIME + timedelta(minutes=1),
                related_event_id=latest.event.event_id,
            )
            second_evidence = context.evidence_recorder.record(
                campaign_id,
                CampaignEvidenceReference(
                    evidence_id="second",
                    media_type="application/json",
                    location="evidence/second.json",
                    sha256="b" * 64,
                    size_bytes=256,
                    metadata={"source": "a4-14-test"},
                ),
                recorded_at=BASE_TIME + timedelta(minutes=2),
            )
            expected_timeline = context.operator.timeline_page(campaign_id, limit=1)
            expected_evidence = context.evidence_operator.evidence_page(
                campaign_id,
                limit=1,
            )
            client = TestClient(app)

            listed = client.get(
                f"{PREFIX}/campaigns",
                params=[("status", CampaignStatus.RUNNING.value), ("limit", "10")],
            )
            self.assertEqual(listed.status_code, 200)
            self.assertTrue(listed.headers["content-type"].startswith(OPERATOR_MEDIA_TYPE))
            self.assertEqual(listed.json()["schema"], OPERATOR_API_SCHEMA)
            self.assertEqual(
                listed.json()["campaigns"][0]["record"],
                context.scheduler.get(campaign_id).to_dict(),
            )

            detail = client.get(f"{PREFIX}/campaigns/{campaign_id}")
            self.assertEqual(
                detail.json()["campaign"]["record"]["spec"],
                submitted.spec.to_dict(),
            )

            timeline = client.get(
                f"{PREFIX}/campaigns/{campaign_id}/timeline",
                params={"limit": "1"},
            ).json()["page"]
            self.assertEqual(
                timeline["entries"],
                [entry.to_dict() for entry in expected_timeline.entries],
            )
            self.assertEqual(timeline["next_cursor"], expected_timeline.next_cursor.to_dict())
            self.assertEqual(timeline["head_cursor"], expected_timeline.head_cursor.to_dict())
            timeline_next = client.get(
                f"{PREFIX}/campaigns/{campaign_id}/timeline",
                params={
                    "after": _cursor(expected_timeline.next_cursor.to_dict()),
                    "snapshot_head": _cursor(expected_timeline.head_cursor.to_dict()),
                    "limit": "10",
                },
            )
            expected_timeline_next = context.operator.timeline_page(
                campaign_id,
                after=expected_timeline.next_cursor,
                snapshot_head=expected_timeline.head_cursor,
                limit=10,
            )
            self.assertEqual(
                timeline_next.json()["page"]["entries"],
                [entry.to_dict() for entry in expected_timeline_next.entries],
            )

            evidence = client.get(
                f"{PREFIX}/campaigns/{campaign_id}/evidence",
                params={"limit": "1"},
            ).json()["page"]
            self.assertEqual(
                evidence["records"],
                [record.to_dict() for record in expected_evidence.records],
            )
            self.assertEqual(evidence["next_cursor"], expected_evidence.next_cursor.to_dict())
            evidence_next = client.get(
                f"{PREFIX}/campaigns/{campaign_id}/evidence",
                params={
                    "after": _cursor(expected_evidence.next_cursor.to_dict()),
                    "snapshot_head": _cursor(expected_evidence.head_cursor.to_dict()),
                    "limit": "10",
                },
            )
            self.assertEqual(
                evidence_next.json()["page"]["records"],
                [second_evidence.to_dict()],
            )
            direct = client.get(f"{PREFIX}/campaigns/{campaign_id}/evidence/first")
            self.assertEqual(direct.json()["evidence"], first_evidence.to_dict())
            verification = client.get(
                f"{PREFIX}/campaigns/{campaign_id}/evidence/verification"
            )
            self.assertEqual(verification.json()["verification"]["record_count"], 2)

            missing = client.get(f"{PREFIX}/campaigns/missing")
            self.assertEqual(missing.status_code, 404)
            self.assertEqual(
                missing.json()["detail"],
                "agent4 operator resource not found",
            )
            invalid = client.get(
                f"{PREFIX}/campaigns/{campaign_id}/timeline",
                params={"after": "not-json"},
            )
            self.assertEqual(invalid.status_code, 422)
            self.assertEqual(
                invalid.json()["detail"],
                "agent4 operator request rejected",
            )
            self.assertNotIn("not-json", invalid.text)
            self.assertEqual(client.post(f"{PREFIX}/campaigns").status_code, 405)

    def test_mount_has_no_lifecycle_write_or_parallel_store_path(self) -> None:
        operator_source = (
            ROOT / "worker" / "app" / "agent4" / "operator_api.py"
        ).read_text(encoding="utf-8")
        mount_source = (
            ROOT / "worker" / "app" / "agent4" / "production_mount.py"
        ).read_text(encoding="utf-8")
        entrypoint_source = (
            ROOT / "worker" / "app" / "entrypoint.py"
        ).read_text(encoding="utf-8")
        main_source = (
            ROOT / "worker" / "app" / "main_impl.py"
        ).read_text(encoding="utf-8")

        banned_calls = {
            "submit",
            "dispatch_ready",
            "pause",
            "resume",
            "cancel",
            "checkpoint",
            "handle_failure",
            "health_intervention",
            "recover",
            "reconcile_projections",
            "signal",
        }
        observed: set[str] = set()
        for source in (operator_source, mount_source):
            for node in ast.walk(ast.parse(source)):
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                    observed.add(node.func.attr)
        self.assertEqual(observed & banned_calls, set())
        self.assertNotIn("compose_agent4_runtime", operator_source + mount_source)
        self.assertNotIn("JsonCampaign", operator_source + mount_source)
        self.assertNotIn("KALIV_WORKER_ALLOW_LAN", operator_source + mount_source)
        self.assertIn("KALIV_WORKER_ALLOW_LAN", main_source)
        self.assertEqual(entrypoint_source.count("mount_agent4_operator("), 1)
        self.assertIn(
            'os.getenv("KALIV_AGENT4_OPERATOR_API", "0") != "1"',
            mount_source,
        )


if __name__ == "__main__":
    unittest.main()
