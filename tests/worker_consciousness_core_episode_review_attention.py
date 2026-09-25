#!/usr/bin/env python3
"""C30-S read-only episode review operator-attention tests."""
from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "worker") not in sys.path:
    sys.path.insert(0, str(ROOT / "worker"))

from app.consciousness_core import (  # noqa: E402
    DEFAULT_EPISODE_REVIEW_ATTENTION_POLICY,
    EpisodeReviewAttentionPolicy,
    EpisodeReviewObservabilitySnapshot,
    EpisodeReviewStatusSnapshot,
    evaluate_episode_review_attention,
)
from app.consciousness_core.episode_review_api import (  # noqa: E402
    CONSCIOUSNESS_EPISODE_REVIEW_FLAG,
    CONSCIOUSNESS_EPISODE_REVIEW_PREFIX,
    build_consciousness_episode_review_router,
)


def metrics(**overrides):
    values = dict(
        schema="kaliv-consciousness-core/episode-review-observability/v1",
        publication_not_applicable=0,
        publication_mailbox_unavailable=0,
        publication_no_review=0,
        publication_enqueued=0,
        publication_duplicate=0,
        publication_capacity_reached=0,
        publication_mailbox_closed=0,
        publication_replay_ledger_full=0,
        claims_succeeded=0,
        abandons_succeeded=0,
        approvals_succeeded=0,
        rejections_succeeded=0,
        request_ids_stored=False,
        request_refs_stored=False,
        claim_ids_stored=False,
        closure_evidence_stored=False,
        timestamps_stored=False,
        event_history_stored=False,
        raw_text_stored=False,
        raw_chain_of_thought_stored=False,
        durable=False,
        memory4_called=False,
        model_calls=0,
        production_activation=False,
    )
    values.update(overrides)
    return EpisodeReviewObservabilitySnapshot(**values)


def status(**overrides):
    values = dict(
        schema="kaliv-consciousness-core/episode-review-status/v1",
        state="OFF",
        runtime_enabled=False,
        transport_enabled=False,
        runtime_present=False,
        service_present=False,
        mailbox_present=False,
        mailbox_capacity=None,
        pending_count=0,
        claimed_count=0,
        mailbox_full=False,
        runtime_closed=None,
        mailbox_closed=None,
        last_publication_status=None,
        observability_present=False,
        observability=None,
        request_refs_included=False,
        claim_ids_included=False,
        closure_evidence_included=False,
        raw_text_included=False,
        raw_chain_of_thought_included=False,
        memory4_called=False,
        model_calls=0,
        production_activation=False,
    )
    values.update(overrides)
    return EpisodeReviewStatusSnapshot(**values)


class EpisodeReviewAttentionTests(unittest.TestCase):
    def test_off_and_transport_only_are_not_automatic_alerts(self):
        off = evaluate_episode_review_attention(status())
        self.assertEqual(off.level, "OK")
        self.assertEqual(off.signals, [])

        transport_only = evaluate_episode_review_attention(
            status(
                state="TRANSPORT_ONLY",
                transport_enabled=True,
            )
        )
        self.assertEqual(transport_only.level, "OK")
        self.assertEqual(transport_only.signal_count, 0)

    def test_runtime_unavailable_is_degraded(self):
        result = evaluate_episode_review_attention(
            status(
                state="RUNTIME_UNAVAILABLE",
                runtime_enabled=True,
            )
        )

        self.assertEqual(result.level, "DEGRADED")
        self.assertEqual(
            [signal.code for signal in result.signals],
            ["RUNTIME_UNAVAILABLE"],
        )

    def test_mailbox_pressure_and_full_are_distinct(self):
        pressure = evaluate_episode_review_attention(
            status(
                state="ACTIVE_PENDING",
                runtime_enabled=True,
                runtime_present=True,
                service_present=True,
                mailbox_present=True,
                mailbox_capacity=8,
                pending_count=6,
                claimed_count=0,
                mailbox_full=False,
                runtime_closed=False,
                mailbox_closed=False,
            )
        )
        self.assertEqual(pressure.level, "ATTENTION")
        self.assertEqual(
            [signal.code for signal in pressure.signals],
            ["MAILBOX_PRESSURE"],
        )

        full = evaluate_episode_review_attention(
            status(
                state="MAILBOX_FULL",
                runtime_enabled=True,
                runtime_present=True,
                service_present=True,
                mailbox_present=True,
                mailbox_capacity=8,
                pending_count=8,
                claimed_count=0,
                mailbox_full=True,
                runtime_closed=False,
                mailbox_closed=False,
            )
        )
        self.assertEqual(full.level, "DEGRADED")
        self.assertEqual(
            [signal.code for signal in full.signals],
            ["MAILBOX_FULL"],
        )

    def test_aggregate_thresholds_generate_no_identity_data(self):
        aggregate = metrics(
            publication_duplicate=10,
            publication_capacity_reached=3,
            publication_mailbox_closed=1,
            publication_replay_ledger_full=1,
        )
        result = evaluate_episode_review_attention(
            status(
                state="ACTIVE_IDLE",
                runtime_enabled=True,
                runtime_present=True,
                service_present=True,
                mailbox_present=True,
                mailbox_capacity=8,
                pending_count=0,
                claimed_count=0,
                mailbox_full=False,
                runtime_closed=False,
                mailbox_closed=False,
                observability_present=True,
                observability=aggregate,
            )
        )

        self.assertEqual(result.level, "DEGRADED")
        codes = {signal.code for signal in result.signals}
        self.assertEqual(
            codes,
            {
                "REPEATED_CAPACITY_REJECTION",
                "REPLAY_LEDGER_EXHAUSTION",
                "PUBLICATION_TO_CLOSED_MAILBOX",
                "REPEATED_DUPLICATE_PUBLICATION",
            },
        )
        payload = result.model_dump_json()
        self.assertFalse(result.request_refs_included)
        self.assertFalse(result.claim_ids_included)
        self.assertFalse(result.closure_evidence_included)
        self.assertFalse(result.raw_text_included)
        self.assertFalse(result.raw_chain_of_thought_included)
        self.assertNotIn("ereq-", payload)
        self.assertNotIn("eclaim-", payload)
        self.assertNotIn("episode-experience-review-request:", payload)

    def test_claim_pressure_is_attention_only(self):
        policy = EpisodeReviewAttentionPolicy(
            schema=(
                "kaliv-consciousness-core/"
                "episode-review-attention-policy/v1"
            ),
            mailbox_pressure_ratio=1.0,
            claim_pressure_count=24,
            capacity_rejection_threshold=3,
            replay_ledger_full_threshold=1,
            mailbox_closed_publication_threshold=1,
            duplicate_publication_threshold=10,
        )
        result = evaluate_episode_review_attention(
            status(
                state="ACTIVE_CLAIMED",
                runtime_enabled=True,
                runtime_present=True,
                service_present=True,
                mailbox_present=True,
                mailbox_capacity=32,
                pending_count=24,
                claimed_count=24,
                mailbox_full=False,
                runtime_closed=False,
                mailbox_closed=False,
            ),
            policy,
        )

        self.assertEqual(result.level, "ATTENTION")
        self.assertEqual(
            [signal.code for signal in result.signals],
            ["CLAIM_PRESSURE"],
        )

    def test_evaluation_is_pure_and_takes_no_action(self):
        source = status(
            state="RUNTIME_UNAVAILABLE",
            runtime_enabled=True,
        )

        first = evaluate_episode_review_attention(source)
        second = evaluate_episode_review_attention(source)

        self.assertEqual(first, second)
        self.assertEqual(first.notifications_sent, 0)
        self.assertEqual(first.timers_started, 0)
        self.assertEqual(first.scheduler_jobs_created, 0)
        self.assertEqual(first.background_tasks_started, 0)
        self.assertEqual(first.automatic_actions_taken, 0)
        self.assertFalse(first.durable_store_write_applied)
        self.assertFalse(first.memory4_called)
        self.assertEqual(first.model_calls, 0)

    def test_default_policy_contract_is_bounded(self):
        policy = DEFAULT_EPISODE_REVIEW_ATTENTION_POLICY
        self.assertEqual(policy.mailbox_pressure_ratio, 0.75)
        self.assertEqual(policy.claim_pressure_count, 24)
        self.assertEqual(policy.capacity_rejection_threshold, 3)
        self.assertEqual(policy.replay_ledger_full_threshold, 1)
        self.assertEqual(
            policy.mailbox_closed_publication_threshold,
            1,
        )
        self.assertEqual(policy.duplicate_publication_threshold, 10)

    def test_private_attention_route_is_loopback_only_and_service_free(self):
        old = os.environ.get(CONSCIOUSNESS_EPISODE_REVIEW_FLAG)
        try:
            os.environ[CONSCIOUSNESS_EPISODE_REVIEW_FLAG] = "1"
            app = FastAPI()
            app.include_router(
                build_consciousness_episode_review_router(
                    loopback_allowed=lambda _request: True,
                )
            )
            response = TestClient(app).get(
                CONSCIOUSNESS_EPISODE_REVIEW_PREFIX + "/attention"
            )
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["level"], "OK")

            denied = FastAPI()
            denied.include_router(
                build_consciousness_episode_review_router(
                    loopback_allowed=lambda _request: False,
                )
            )
            rejected = TestClient(denied).get(
                CONSCIOUSNESS_EPISODE_REVIEW_PREFIX + "/attention"
            )
            self.assertEqual(rejected.status_code, 403)
        finally:
            if old is None:
                os.environ.pop(CONSCIOUSNESS_EPISODE_REVIEW_FLAG, None)
            else:
                os.environ[CONSCIOUSNESS_EPISODE_REVIEW_FLAG] = old


if __name__ == "__main__":
    unittest.main()
