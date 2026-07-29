#!/usr/bin/env python3
"""Composition and retry-policy gates for the dormant Agent 4 foundation."""

from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.agent4 import (
    CampaignEvent,
    CampaignEventKind,
    CampaignQueue,
    CampaignRecord,
    CampaignRetryPlanner,
    CampaignSpec,
    CampaignState,
    CampaignStatus,
    DefaultRetryClassifier,
    FailureDescriptor,
    InMemoryCampaignEventBus,
    JsonCampaignRepository,
    RetryCategory,
    RetryDisposition,
    RetryPolicy,
    transition_campaign,
)


BASE_TIME = datetime(2026, 7, 29, 15, 0, tzinfo=timezone.utc)


class Agent4FoundationWorkflowTests(unittest.TestCase):
    def test_campaign_can_be_queued_started_persisted_and_observed(self) -> None:
        now = BASE_TIME
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


class Agent4RetryPolicyTests(unittest.TestCase):
    def spec(self, *, max_attempts: int = 4) -> CampaignSpec:
        return CampaignSpec(
            campaign_id="campaign-retry",
            name="Retry campaign",
            workflow="agent3.write-pilot",
            created_at=BASE_TIME,
            max_attempts=max_attempts,
        )

    def state(self, *, attempt: int) -> CampaignState:
        return CampaignState(
            campaign_id="campaign-retry",
            status=CampaignStatus.RUNNING,
            attempt=attempt,
            updated_at=BASE_TIME,
        )

    def failure(
        self,
        error_type: str,
        *,
        retry_after: timedelta | None = None,
    ) -> FailureDescriptor:
        return FailureDescriptor(
            error_type=error_type,
            message="operation failed",
            phase="dispatch",
            retry_after=retry_after,
        )

    def test_classifier_uses_exact_error_types_not_message_heuristics(self) -> None:
        classifier = DefaultRetryClassifier()
        self.assertEqual(
            classifier.classify(self.failure("TimeoutError")),
            RetryCategory.TRANSIENT,
        )
        self.assertEqual(
            classifier.classify(self.failure("RateLimitError")),
            RetryCategory.RATE_LIMITED,
        )
        self.assertEqual(
            classifier.classify(self.failure("CampaignResourceBlockedError")),
            RetryCategory.RESOURCE_EXHAUSTED,
        )
        self.assertEqual(
            classifier.classify(
                FailureDescriptor(
                    error_type="ValueError",
                    message="timeout appears only in the message",
                    phase="validation",
                )
            ),
            RetryCategory.PERMANENT,
        )

    def test_backoff_is_deterministic_exponential_and_capped(self) -> None:
        policy = RetryPolicy(
            initial_delay=timedelta(seconds=3),
            multiplier=2,
            max_delay=timedelta(seconds=10),
        )
        self.assertEqual(policy.delay_for_attempt(1), timedelta(seconds=3))
        self.assertEqual(policy.delay_for_attempt(2), timedelta(seconds=6))
        self.assertEqual(policy.delay_for_attempt(3), timedelta(seconds=10))
        self.assertEqual(policy.delay_for_attempt(8), timedelta(seconds=10))

    def test_transient_failure_retries_with_budget_and_ready_time(self) -> None:
        decision = CampaignRetryPlanner(
            policy=RetryPolicy(initial_delay=timedelta(seconds=4))
        ).decide(
            self.spec(max_attempts=4),
            self.state(attempt=2),
            self.failure("ConnectionError"),
            occurred_at=BASE_TIME,
        )
        self.assertTrue(decision.should_retry)
        self.assertEqual(decision.disposition, RetryDisposition.RETRY)
        self.assertEqual(decision.category, RetryCategory.TRANSIENT)
        self.assertEqual(decision.remaining_attempts, 2)
        self.assertEqual(decision.delay, timedelta(seconds=8))
        self.assertEqual(decision.ready_at, BASE_TIME + timedelta(seconds=8))

    def test_retry_after_is_honoured_as_a_minimum_delay(self) -> None:
        decision = CampaignRetryPlanner(
            policy=RetryPolicy(initial_delay=timedelta(seconds=5))
        ).decide(
            self.spec(),
            self.state(attempt=1),
            self.failure("RateLimitError", retry_after=timedelta(seconds=45)),
            occurred_at=BASE_TIME,
        )
        self.assertEqual(decision.delay, timedelta(seconds=45))
        self.assertEqual(decision.ready_at, BASE_TIME + timedelta(seconds=45))

    def test_permanent_cancelled_and_exhausted_failures_are_terminal(self) -> None:
        planner = CampaignRetryPlanner()
        for error_type, category in (
            ("ValueError", RetryCategory.PERMANENT),
            ("CancelledError", RetryCategory.CANCELLED),
        ):
            with self.subTest(error_type=error_type):
                decision = planner.decide(
                    self.spec(),
                    self.state(attempt=1),
                    self.failure(error_type),
                    occurred_at=BASE_TIME,
                )
                self.assertFalse(decision.should_retry)
                self.assertEqual(decision.category, category)
                self.assertIsNone(decision.ready_at)

        exhausted = planner.decide(
            self.spec(max_attempts=3),
            self.state(attempt=3),
            self.failure("TimeoutError"),
            occurred_at=BASE_TIME,
        )
        self.assertEqual(exhausted.disposition, RetryDisposition.TERMINAL)
        self.assertEqual(exhausted.remaining_attempts, 0)
        self.assertEqual(exhausted.reason, "retry budget exhausted")

    def test_invalid_policy_inputs_fail_closed(self) -> None:
        for kwargs in (
            dict(initial_delay=timedelta(seconds=-1)),
            dict(multiplier=0.5),
            dict(
                initial_delay=timedelta(seconds=10),
                max_delay=timedelta(seconds=5),
            ),
        ):
            with self.subTest(kwargs=kwargs):
                with self.assertRaises(Exception):
                    RetryPolicy(**kwargs)

    def test_invalid_decision_inputs_fail_closed(self) -> None:
        planner = CampaignRetryPlanner()
        with self.assertRaises(Exception):
            planner.decide(
                self.spec(),
                self.state(attempt=0),
                self.failure("TimeoutError"),
                occurred_at=BASE_TIME,
            )
        with self.assertRaises(Exception):
            planner.decide(
                self.spec(),
                self.state(attempt=1),
                self.failure("TimeoutError"),
                occurred_at=BASE_TIME.replace(tzinfo=None),
            )


if __name__ == "__main__":
    unittest.main()
