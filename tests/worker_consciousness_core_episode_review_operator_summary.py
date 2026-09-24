#!/usr/bin/env python3
"""C30-T compact episode-review operator summary tests."""
from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "worker") not in sys.path:
    sys.path.insert(0, str(ROOT / "worker"))

from app.consciousness_core import (  # noqa: E402
    EPISODE_REVIEW_RUNTIME_FLAG,
    EpisodeExperienceReviewMailbox,
    EpisodeReviewObservability,
    EpisodeReviewRuntime,
    TrustedEpisodeReviewClaimService,
    build_episode_review_operator_summary,
)
from app.consciousness_core.episode_review_api import (  # noqa: E402
    CONSCIOUSNESS_EPISODE_REVIEW_FLAG,
    CONSCIOUSNESS_EPISODE_REVIEW_PREFIX,
    build_consciousness_episode_review_router,
)


class Env:
    def __enter__(self):
        self.old_runtime = os.environ.get(EPISODE_REVIEW_RUNTIME_FLAG)
        self.old_transport = os.environ.get(
            CONSCIOUSNESS_EPISODE_REVIEW_FLAG
        )
        os.environ.pop(EPISODE_REVIEW_RUNTIME_FLAG, None)
        os.environ.pop(CONSCIOUSNESS_EPISODE_REVIEW_FLAG, None)
        return self

    def __exit__(self, *_args):
        if self.old_runtime is None:
            os.environ.pop(EPISODE_REVIEW_RUNTIME_FLAG, None)
        else:
            os.environ[EPISODE_REVIEW_RUNTIME_FLAG] = self.old_runtime
        if self.old_transport is None:
            os.environ.pop(CONSCIOUSNESS_EPISODE_REVIEW_FLAG, None)
        else:
            os.environ[
                CONSCIOUSNESS_EPISODE_REVIEW_FLAG
            ] = self.old_transport


def runtime_app():
    mailbox = EpisodeExperienceReviewMailbox()
    observability = EpisodeReviewObservability()
    service = TrustedEpisodeReviewClaimService(
        mailbox=mailbox,
        observability=observability,
    )
    runtime = EpisodeReviewRuntime(
        mailbox=mailbox,
        service=service,
        observability=observability,
    )
    app = SimpleNamespace(
        state=SimpleNamespace(
            consciousness_episode_review_runtime=runtime,
            consciousness_episode_review_mailbox=mailbox,
            consciousness_episode_review_service=service,
            consciousness_episode_review_observability=observability,
        )
    )
    return app, runtime, observability


class EpisodeReviewOperatorSummaryTests(unittest.TestCase):
    def test_off_summary_is_compact_and_zeroed(self):
        with Env():
            app = SimpleNamespace(state=SimpleNamespace())

            summary = build_episode_review_operator_summary(app)

            self.assertEqual(summary.state, "OFF")
            self.assertEqual(summary.attention_level, "OK")
            self.assertEqual(summary.attention_signal_count, 0)
            self.assertEqual(summary.pending_count, 0)
            self.assertEqual(summary.claimed_count, 0)
            self.assertEqual(summary.publication_enqueued, 0)
            self.assertEqual(summary.claims_succeeded, 0)
            self.assertFalse(summary.observability_present)

    def test_transport_only_is_visible_without_becoming_alert(self):
        with Env():
            os.environ[CONSCIOUSNESS_EPISODE_REVIEW_FLAG] = "1"
            app = SimpleNamespace(state=SimpleNamespace())

            summary = build_episode_review_operator_summary(app)

            self.assertEqual(summary.state, "TRANSPORT_ONLY")
            self.assertEqual(summary.attention_level, "OK")
            self.assertTrue(summary.transport_enabled)
            self.assertFalse(summary.runtime_enabled)

    def test_summary_combines_aggregate_metrics_and_attention(self):
        with Env():
            os.environ[EPISODE_REVIEW_RUNTIME_FLAG] = "1"
            app, _runtime, observability = runtime_app()
            for _ in range(3):
                observability.record_publication(
                    "CAPACITY_REACHED"
                )
            observability.record_publication("ENQUEUED")
            observability.record_claim()
            observability.record_abandon()
            observability.record_decision("APPROVE")
            observability.record_decision("REJECT")

            summary = build_episode_review_operator_summary(app)

            self.assertEqual(summary.state, "ACTIVE_IDLE")
            self.assertEqual(summary.attention_level, "DEGRADED")
            self.assertIn(
                "REPEATED_CAPACITY_REJECTION",
                summary.attention_signal_codes,
            )
            self.assertEqual(summary.publication_enqueued, 1)
            self.assertEqual(
                summary.publication_capacity_reached,
                3,
            )
            self.assertEqual(summary.claims_succeeded, 1)
            self.assertEqual(summary.abandons_succeeded, 1)
            self.assertEqual(summary.approvals_succeeded, 1)
            self.assertEqual(summary.rejections_succeeded, 1)
            self.assertTrue(summary.observability_present)

    def test_summary_contains_no_individual_review_identity(self):
        with Env():
            os.environ[EPISODE_REVIEW_RUNTIME_FLAG] = "1"
            app, _runtime, observability = runtime_app()
            observability.record_publication("ENQUEUED")

            summary = build_episode_review_operator_summary(app)
            payload = summary.model_dump_json()

            self.assertFalse(
                summary.individual_review_items_included
            )
            self.assertFalse(summary.request_refs_included)
            self.assertFalse(summary.claim_ids_included)
            self.assertFalse(summary.closure_evidence_included)
            self.assertFalse(summary.raw_text_included)
            self.assertFalse(summary.raw_chain_of_thought_included)
            self.assertNotIn("ereq-", payload)
            self.assertNotIn("eclaim-", payload)
            self.assertNotIn(
                "episode-experience-review-request:",
                payload,
            )

    def test_summary_is_read_only_and_takes_no_action(self):
        with Env():
            os.environ[EPISODE_REVIEW_RUNTIME_FLAG] = "1"
            app, runtime, observability = runtime_app()
            before_mailbox = runtime.mailbox.snapshot
            before_metrics = observability.snapshot

            first = build_episode_review_operator_summary(app)
            second = build_episode_review_operator_summary(app)

            self.assertEqual(first, second)
            self.assertEqual(runtime.mailbox.snapshot, before_mailbox)
            self.assertEqual(observability.snapshot, before_metrics)
            self.assertFalse(first.notification_sent)
            self.assertFalse(first.automatic_action_taken)
            self.assertFalse(first.durable_store_write_applied)
            self.assertFalse(first.memory4_called)
            self.assertEqual(first.model_calls, 0)

    def test_private_summary_route_is_loopback_only_and_service_free(self):
        with Env():
            os.environ[CONSCIOUSNESS_EPISODE_REVIEW_FLAG] = "1"

            app = FastAPI()
            app.include_router(
                build_consciousness_episode_review_router(
                    loopback_allowed=lambda _request: True,
                )
            )
            response = TestClient(app).get(
                CONSCIOUSNESS_EPISODE_REVIEW_PREFIX + "/summary"
            )
            self.assertEqual(response.status_code, 200)
            self.assertEqual(
                response.json()["state"],
                "TRANSPORT_ONLY",
            )

            denied = FastAPI()
            denied.include_router(
                build_consciousness_episode_review_router(
                    loopback_allowed=lambda _request: False,
                )
            )
            rejected = TestClient(denied).get(
                CONSCIOUSNESS_EPISODE_REVIEW_PREFIX + "/summary"
            )
            self.assertEqual(rejected.status_code, 403)


if __name__ == "__main__":
    unittest.main()
