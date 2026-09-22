#!/usr/bin/env python3
"""C25-A bounded autonomous cognition trigger policy tests.

Run:
    PYTHONPATH=worker python3 tests/worker_consciousness_core_autonomous_trigger_policy.py
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "worker") not in sys.path:
    sys.path.insert(0, str(ROOT / "worker"))

from app.consciousness_core.autonomous_trigger_policy import (  # noqa: E402
    DEFAULT_AUTONOMOUS_TRIGGER_POLICY,
    AutomaticCognitionAccounting,
    AutonomousTriggerPolicy,
    AutonomousTriggerPolicyError,
    autonomous_trigger_policy_ref,
    evaluate_autonomous_trigger,
    new_automatic_cognition_accounting,
    record_automatic_cognition,
)
from app.consciousness_core.supervisor import CognitionEvent  # noqa: E402
from app.consciousness_core.temporal import ClockSample  # noqa: E402


class AutonomousTriggerPolicyTests(unittest.TestCase):
    def clock(
        self,
        *,
        monotonic_ms: int = 100_000,
        sample: str = "1",
        epoch: str = "a",
    ) -> ClockSample:
        return ClockSample(
            schema="kaliv-consciousness-core/clock-sample/v1",
            sample_id="clock-" + sample * 32,
            wall_time_unix_ms=1_700_000_000_000 + monotonic_ms,
            timezone_name="Europe/Copenhagen",
            utc_offset_minutes=120,
            local_hour=12,
            monotonic_ms=monotonic_ms,
            runtime_epoch_id="epoch-" + epoch * 32,
            sampled_sequence=monotonic_ms // 1000,
            source_ref="clock:test",
            confidence=1.0,
            production_activation=False,
        )

    def event(
        self,
        kind: str,
        *,
        salience: float = 1.0,
        marker: str = "1",
    ) -> CognitionEvent:
        return CognitionEvent(
            schema="kaliv-consciousness-core/cognition-event/v1",
            event_id="cevt-" + marker * 32,
            kind=kind,
            source_ref=f"event:test:{kind}",
            summary=f"Test {kind}",
            salience=salience,
            observed_sequence=1,
            production_activation=False,
        )

    def policy(self, **updates) -> AutonomousTriggerPolicy:
        values = DEFAULT_AUTONOMOUS_TRIGGER_POLICY.model_dump(mode="json")
        values.update(updates)
        return AutonomousTriggerPolicy.model_validate(values)

    def test_default_policy_ref_is_canonical(self):
        first = autonomous_trigger_policy_ref(DEFAULT_AUTONOMOUS_TRIGGER_POLICY)
        second = autonomous_trigger_policy_ref(
            AutonomousTriggerPolicy.model_validate(
                DEFAULT_AUTONOMOUS_TRIGGER_POLICY.model_dump(mode="json")
            )
        )
        self.assertEqual(first, second)
        self.assertTrue(first.startswith("autonomous-trigger-policy:"))

    def test_user_operator_and_tool_events_are_never_automatic(self):
        clock = self.clock()
        accounting = new_automatic_cognition_accounting(clock)
        for index, kind in enumerate(
            ("user_turn", "operator_signal", "tool_result"),
            start=1,
        ):
            with self.subTest(kind=kind):
                result = evaluate_autonomous_trigger(
                    event=self.event(kind, marker=f"{index:x}"),
                    clock=clock,
                    accounting=accounting,
                )
                self.assertEqual(result.decision, "DENY")
                self.assertEqual(result.reason, "event_kind_denied")
                self.assertIsNone(result.not_before_monotonic_ms)
                self.assertFalse(result.event_consumed)
                self.assertEqual(result.model_calls, 0)

    def test_wake_followup_is_eligible_by_default(self):
        clock = self.clock()
        result = evaluate_autonomous_trigger(
            event=self.event("wake_followup"),
            clock=clock,
            accounting=new_automatic_cognition_accounting(clock),
        )
        self.assertEqual(result.decision, "ELIGIBLE")
        self.assertEqual(result.reason, "eligible")
        self.assertIsNone(result.not_before_monotonic_ms)
        self.assertEqual(
            result.budget_remaining,
            DEFAULT_AUTONOMOUS_TRIGGER_POLICY.max_steps_per_window,
        )

    def test_wake_followup_can_be_disabled_without_enabling_other_events(self):
        clock = self.clock()
        policy = self.policy(wake_followup_enabled=False)
        result = evaluate_autonomous_trigger(
            event=self.event("wake_followup"),
            clock=clock,
            accounting=new_automatic_cognition_accounting(clock),
            policy=policy,
        )
        self.assertEqual(result.decision, "DENY")
        self.assertEqual(result.reason, "event_kind_denied")

    def test_threshold_events_require_configured_salience(self):
        clock = self.clock()
        accounting = new_automatic_cognition_accounting(clock)
        cases = [
            ("world_change", "world_change_min_salience"),
            ("embodiment_change", "embodiment_change_min_salience"),
            ("memory_recall", "memory_recall_min_salience"),
            ("prediction_error", "prediction_error_min_salience"),
        ]
        for index, (kind, field) in enumerate(cases, start=1):
            threshold = getattr(DEFAULT_AUTONOMOUS_TRIGGER_POLICY, field)
            with self.subTest(kind=kind, case="below"):
                denied = evaluate_autonomous_trigger(
                    event=self.event(
                        kind,
                        salience=max(0.0, threshold - 0.01),
                        marker=f"{index:x}",
                    ),
                    clock=clock,
                    accounting=accounting,
                )
                self.assertEqual(denied.decision, "DENY")
                self.assertEqual(denied.reason, "salience_below_threshold")
            with self.subTest(kind=kind, case="exact"):
                eligible = evaluate_autonomous_trigger(
                    event=self.event(
                        kind,
                        salience=threshold,
                        marker=f"{index + 4:x}",
                    ),
                    clock=clock,
                    accounting=accounting,
                )
                self.assertEqual(eligible.decision, "ELIGIBLE")
                self.assertEqual(eligible.reason, "eligible")

    def test_cooldown_defers_without_consuming_or_calling_model(self):
        clock = self.clock(monotonic_ms=140_000, sample="2")
        accounting = AutomaticCognitionAccounting(
            schema="kaliv-consciousness-core/automatic-cognition-accounting/v1",
            runtime_epoch_id=clock.runtime_epoch_id,
            window_started_monotonic_ms=100_000,
            automatic_steps_in_window=1,
            last_automatic_step_monotonic_ms=130_000,
            production_activation=False,
        )
        policy = self.policy(cooldown_ms=30_000)
        result = evaluate_autonomous_trigger(
            event=self.event("world_change", salience=1.0),
            clock=clock,
            accounting=accounting,
            policy=policy,
        )
        self.assertEqual(result.decision, "DEFER")
        self.assertEqual(result.reason, "cooldown_active")
        self.assertEqual(result.not_before_monotonic_ms, 160_000)
        self.assertFalse(result.event_consumed)
        self.assertEqual(result.model_calls, 0)
        self.assertEqual(accounting.automatic_steps_in_window, 1)

    def test_window_budget_defers_until_window_rollover(self):
        policy = self.policy(
            window_ms=100_000,
            max_steps_per_window=2,
            cooldown_ms=0,
        )
        clock = self.clock(monotonic_ms=150_000, sample="3")
        accounting = AutomaticCognitionAccounting(
            schema="kaliv-consciousness-core/automatic-cognition-accounting/v1",
            runtime_epoch_id=clock.runtime_epoch_id,
            window_started_monotonic_ms=100_000,
            automatic_steps_in_window=2,
            last_automatic_step_monotonic_ms=120_000,
            production_activation=False,
        )
        result = evaluate_autonomous_trigger(
            event=self.event("prediction_error", salience=1.0),
            clock=clock,
            accounting=accounting,
            policy=policy,
        )
        self.assertEqual(result.decision, "DEFER")
        self.assertEqual(result.reason, "window_budget_exhausted")
        self.assertEqual(result.not_before_monotonic_ms, 200_000)
        self.assertEqual(result.budget_remaining, 0)

    def test_expired_window_resets_effective_budget_without_mutation(self):
        policy = self.policy(
            window_ms=100_000,
            max_steps_per_window=2,
            cooldown_ms=0,
        )
        clock = self.clock(monotonic_ms=200_000, sample="4")
        accounting = AutomaticCognitionAccounting(
            schema="kaliv-consciousness-core/automatic-cognition-accounting/v1",
            runtime_epoch_id=clock.runtime_epoch_id,
            window_started_monotonic_ms=100_000,
            automatic_steps_in_window=2,
            last_automatic_step_monotonic_ms=120_000,
            production_activation=False,
        )
        result = evaluate_autonomous_trigger(
            event=self.event("world_change", salience=1.0),
            clock=clock,
            accounting=accounting,
            policy=policy,
        )
        self.assertEqual(result.decision, "ELIGIBLE")
        self.assertEqual(result.effective_window_started_monotonic_ms, 200_000)
        self.assertEqual(result.effective_steps_in_window, 0)
        self.assertEqual(result.budget_remaining, 2)
        self.assertEqual(accounting.window_started_monotonic_ms, 100_000)
        self.assertEqual(accounting.automatic_steps_in_window, 2)

    def test_window_rollover_resets_budget_but_preserves_recent_cooldown(self):
        policy = self.policy(
            window_ms=100_000,
            max_steps_per_window=2,
            cooldown_ms=30_000,
        )
        clock = self.clock(monotonic_ms=200_000, sample="d")
        accounting = AutomaticCognitionAccounting(
            schema="kaliv-consciousness-core/automatic-cognition-accounting/v1",
            runtime_epoch_id=clock.runtime_epoch_id,
            window_started_monotonic_ms=100_000,
            automatic_steps_in_window=2,
            last_automatic_step_monotonic_ms=190_000,
            production_activation=False,
        )
        result = evaluate_autonomous_trigger(
            event=self.event("world_change", salience=1.0, marker="d"),
            clock=clock,
            accounting=accounting,
            policy=policy,
        )
        self.assertEqual(result.effective_window_started_monotonic_ms, 200_000)
        self.assertEqual(result.effective_steps_in_window, 0)
        self.assertEqual(result.budget_remaining, 2)
        self.assertEqual(result.decision, "DEFER")
        self.assertEqual(result.reason, "cooldown_active")
        self.assertEqual(result.not_before_monotonic_ms, 220_000)

    def test_runtime_epoch_change_fails_closed(self):
        prior = self.clock(epoch="a")
        current = self.clock(epoch="b", sample="5")
        accounting = new_automatic_cognition_accounting(prior)
        result = evaluate_autonomous_trigger(
            event=self.event("wake_followup"),
            clock=current,
            accounting=accounting,
        )
        self.assertEqual(result.decision, "DENY")
        self.assertEqual(result.reason, "runtime_epoch_changed")
        self.assertIsNone(result.not_before_monotonic_ms)
        with self.assertRaises(AutonomousTriggerPolicyError):
            record_automatic_cognition(
                decision=result,
                clock=current,
            )

    def test_monotonic_regression_is_rejected(self):
        clock = self.clock(monotonic_ms=90_000, sample="6")
        accounting = AutomaticCognitionAccounting(
            schema="kaliv-consciousness-core/automatic-cognition-accounting/v1",
            runtime_epoch_id=clock.runtime_epoch_id,
            window_started_monotonic_ms=100_000,
            automatic_steps_in_window=0,
            last_automatic_step_monotonic_ms=None,
            production_activation=False,
        )
        with self.assertRaises(AutonomousTriggerPolicyError):
            evaluate_autonomous_trigger(
                event=self.event("world_change"),
                clock=clock,
                accounting=accounting,
            )

    def test_record_requires_exact_eligible_decision_clock_and_policy(self):
        clock = self.clock(sample="7")
        policy = self.policy()
        decision = evaluate_autonomous_trigger(
            event=self.event("wake_followup"),
            clock=clock,
            accounting=new_automatic_cognition_accounting(clock),
            policy=policy,
        )
        receipt = record_automatic_cognition(
            decision=decision,
            clock=clock,
            policy=policy,
        )
        self.assertEqual(receipt.previous_steps_in_window, 0)
        self.assertEqual(receipt.next_steps_in_window, 1)
        self.assertEqual(receipt.accounting.automatic_steps_in_window, 1)
        self.assertEqual(
            receipt.accounting.last_automatic_step_monotonic_ms,
            clock.monotonic_ms,
        )
        self.assertEqual(receipt.model_calls_authorized_here, 0)
        self.assertFalse(receipt.scheduling_authority)
        self.assertFalse(receipt.execution_authority)

        other_clock = self.clock(sample="8")
        with self.assertRaises(AutonomousTriggerPolicyError):
            record_automatic_cognition(
                decision=decision,
                clock=other_clock,
                policy=policy,
            )
        different_policy = self.policy(world_change_min_salience=0.81)
        with self.assertRaises(AutonomousTriggerPolicyError):
            record_automatic_cognition(
                decision=decision,
                clock=clock,
                policy=different_policy,
            )

    def test_record_rejects_denied_and_deferred_decisions(self):
        clock = self.clock(sample="9")
        accounting = new_automatic_cognition_accounting(clock)
        denied = evaluate_autonomous_trigger(
            event=self.event("user_turn"),
            clock=clock,
            accounting=accounting,
        )
        with self.assertRaises(AutonomousTriggerPolicyError):
            record_automatic_cognition(decision=denied, clock=clock)

        later = self.clock(monotonic_ms=110_000, sample="a")
        deferred_accounting = AutomaticCognitionAccounting(
            schema="kaliv-consciousness-core/automatic-cognition-accounting/v1",
            runtime_epoch_id=later.runtime_epoch_id,
            window_started_monotonic_ms=100_000,
            automatic_steps_in_window=1,
            last_automatic_step_monotonic_ms=105_000,
            production_activation=False,
        )
        deferred = evaluate_autonomous_trigger(
            event=self.event("wake_followup", marker="b"),
            clock=later,
            accounting=deferred_accounting,
        )
        self.assertEqual(deferred.decision, "DEFER")
        with self.assertRaises(AutonomousTriggerPolicyError):
            record_automatic_cognition(decision=deferred, clock=later)

    def test_same_inputs_produce_same_decision_id(self):
        clock = self.clock(sample="c")
        accounting = new_automatic_cognition_accounting(clock)
        event = self.event("prediction_error", marker="c")
        first = evaluate_autonomous_trigger(
            event=event,
            clock=clock,
            accounting=accounting,
        )
        second = evaluate_autonomous_trigger(
            event=event,
            clock=clock,
            accounting=accounting,
        )
        self.assertEqual(first, second)
        self.assertEqual(first.decision_id, second.decision_id)

    def test_policy_rejects_cooldown_larger_than_window(self):
        values = DEFAULT_AUTONOMOUS_TRIGGER_POLICY.model_dump(mode="json")
        values["window_ms"] = 10_000
        values["cooldown_ms"] = 20_000
        with self.assertRaises(Exception):
            AutonomousTriggerPolicy.model_validate(values)


if __name__ == "__main__":
    unittest.main()
