#!/usr/bin/env python3
"""C27-E deterministic checkpoint-pressure policy tests.

Run:
    PYTHONPATH=worker python3 tests/worker_consciousness_core_checkpoint_pressure.py
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "worker") not in sys.path:
    sys.path.insert(0, str(ROOT / "worker"))

from app.consciousness_core.checkpoint_pressure import (  # noqa: E402
    CheckpointPressurePolicy,
    DEFAULT_CHECKPOINT_PRESSURE_POLICY,
    checkpoint_pressure_policy_ref,
    evaluate_checkpoint_pressure,
)
from app.consciousness_core.self_state import (  # noqa: E402
    SelfAffect,
    SelfBootstrapAuthority,
    advance_self_state,
    bootstrap_self_state,
)
from app.consciousness_core.self_state_ledger import (  # noqa: E402
    RuntimeSelfStateLedger,
)


class CheckpointPressureTests(unittest.TestCase):
    def initial(self):
        authority = SelfBootstrapAuthority(
            schema="kaliv-consciousness-core/self-bootstrap-authority/v1",
            self_id="self-" + "a" * 32,
            person_id="person-" + "b" * 32,
            person_revision="person-r0007",
            authority="operator_review",
            authority_ref="operator:test:c27e",
            source_refs=["registry:test:c27e"],
            production_activation=False,
        )
        state = bootstrap_self_state(
            authority,
            personality_state_ref="personality-state:c27e",
            world_state_ref="world-state:c27e:0",
            workspace_ref="workspace:c27e:0",
            affect=SelfAffect(
                labels=["focused"],
                valence=0.0,
                arousal=0.2,
                confidence=1.0,
                source_refs=["affect:c27e"],
            ),
        )
        return state

    def ledger(self):
        durable = self.initial()
        bootstrap = advance_self_state(
            durable,
            world_state_ref="world-state:c27e:bootstrap",
            workspace_ref="workspace:c27e:bootstrap",
        )
        return RuntimeSelfStateLedger(
            anchor_state=durable,
            initial_state=bootstrap,
            initial_source_ref="session-bootstrap:test:c27e",
        )

    def append(
        self,
        ledger,
        *,
        kind="world_evidence",
        count=1,
    ):
        current = ledger.current_state
        for index in range(count):
            current = advance_self_state(
                current,
                workspace_ref=f"workspace:c27e:{current.revision + 1}",
            )
            ledger.append(
                state=current,
                kind=kind,
                source_ref=f"transition:c27e:{kind}:{index}:{current.revision}",
            )
        return ledger

    def test_none_plan_is_idle_and_side_effect_free(self):
        first = evaluate_checkpoint_pressure(plan=None)
        second = evaluate_checkpoint_pressure(plan=None)
        self.assertEqual(first, second)
        self.assertEqual(first.decision, "IDLE")
        self.assertEqual(first.reason, "no_pending_transitions")
        self.assertEqual(first.pending_transition_count, 0)
        self.assertEqual(first.remaining_transition_capacity, 128)
        self.assertIsNone(first.final_state_ref)
        self.assertEqual(first.transition_kinds, [])
        self.assertFalse(first.self_state_store_write_applied)
        self.assertEqual(first.model_calls, 0)
        self.assertFalse(first.execution_authority)
        self.assertFalse(first.scheduling_authority)
        self.assertFalse(first.durable_memory_write_authority)

    def test_bootstrap_only_is_hold_below_default_threshold(self):
        ledger = self.ledger()
        decision = evaluate_checkpoint_pressure(plan=ledger.plan())
        self.assertEqual(decision.decision, "HOLD")
        self.assertEqual(decision.reason, "below_threshold")
        self.assertEqual(decision.pending_transition_count, 1)
        self.assertEqual(decision.transition_kinds, ["session_bootstrap"])
        self.assertEqual(decision.remaining_transition_capacity, 127)

    def test_post_cycle_reduction_requests_checkpoint_immediately(self):
        ledger = self.ledger()
        self.append(
            ledger,
            kind="supervisor_orientation",
            count=1,
        )
        self.append(
            ledger,
            kind="post_cycle_reduction",
            count=1,
        )
        decision = evaluate_checkpoint_pressure(plan=ledger.plan())
        self.assertEqual(decision.decision, "CHECKPOINT")
        self.assertEqual(decision.reason, "completed_cognitive_cycle")
        self.assertEqual(decision.pending_transition_count, 3)
        self.assertIn("post_cycle_reduction", decision.transition_kinds)

    def test_transition_threshold_requests_checkpoint_without_cognitive_cycle(self):
        ledger = self.ledger()
        self.append(
            ledger,
            kind="world_evidence",
            count=7,
        )
        decision = evaluate_checkpoint_pressure(plan=ledger.plan())
        self.assertEqual(decision.pending_transition_count, 8)
        self.assertEqual(decision.decision, "CHECKPOINT")
        self.assertEqual(decision.reason, "transition_threshold")
        self.assertNotIn("post_cycle_reduction", decision.transition_kinds)

    def test_capacity_reserve_has_highest_priority(self):
        ledger = self.ledger()
        self.append(
            ledger,
            kind="world_evidence",
            count=126,
        )
        self.assertEqual(ledger.plan().transition_count, 127)
        decision = evaluate_checkpoint_pressure(plan=ledger.plan())
        self.assertEqual(decision.decision, "REQUIRED")
        self.assertEqual(decision.reason, "capacity_reserve_exhausted")
        self.assertEqual(decision.remaining_transition_capacity, 1)

    def test_custom_policy_can_batch_completed_cycles(self):
        ledger = self.ledger()
        self.append(
            ledger,
            kind="supervisor_orientation",
            count=1,
        )
        self.append(
            ledger,
            kind="post_cycle_reduction",
            count=1,
        )
        policy = CheckpointPressurePolicy(
            schema="kaliv-consciousness-core/checkpoint-pressure-policy/v1",
            checkpoint_transition_count=8,
            reserve_transition_slots=2,
            checkpoint_after_post_cycle=False,
            production_activation=False,
        )
        decision = evaluate_checkpoint_pressure(
            plan=ledger.plan(),
            policy=policy,
        )
        self.assertEqual(decision.decision, "HOLD")
        self.assertEqual(decision.reason, "below_threshold")

    def test_policy_and_decision_are_deterministic(self):
        ledger = self.ledger()
        plan = ledger.plan()
        first = evaluate_checkpoint_pressure(plan=plan)
        second = evaluate_checkpoint_pressure(plan=plan)
        self.assertEqual(first, second)
        self.assertTrue(first.decision_id.startswith("ckptpress-"))
        self.assertEqual(
            checkpoint_pressure_policy_ref(
                DEFAULT_CHECKPOINT_PRESSURE_POLICY
            ),
            checkpoint_pressure_policy_ref(
                DEFAULT_CHECKPOINT_PRESSURE_POLICY
            ),
        )

    def test_policy_validation_rejects_unusable_threshold_reserve_pair(self):
        with self.assertRaises(ValueError):
            CheckpointPressurePolicy(
                schema=(
                    "kaliv-consciousness-core/"
                    "checkpoint-pressure-policy/v1"
                ),
                checkpoint_transition_count=128,
                reserve_transition_slots=2,
                checkpoint_after_post_cycle=True,
                production_activation=False,
            )


if __name__ == "__main__":
    unittest.main()
