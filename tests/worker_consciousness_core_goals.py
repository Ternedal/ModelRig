#!/usr/bin/env python3
"""C9-A persistent goal / intention lifecycle tests for Consciousness Core.

Run:
    PYTHONPATH=worker python3 tests/worker_consciousness_core_goals.py
"""
from __future__ import annotations

import copy
import inspect
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "worker") not in sys.path:
    sys.path.insert(0, str(ROOT / "worker"))

from app.consciousness_core import (  # noqa: E402
    Agent3IntentHandoff,
    GoalAdmissionEvidence,
    GoalCandidate,
    GoalContractError,
    GoalRecord,
    IntentionRecord,
    admit_goal,
    build_agent3_handoff,
    select_intention,
    select_next_goal,
    transition_goal,
)


SELF_ID = "self-" + "1" * 32
PERSON_REVISION = "person-r0007"
CYCLE = "cycle-" + "2" * 32


class ConsciousnessCoreGoalTests(unittest.TestCase):
    def candidate(
        self,
        *,
        suffix: str = "3",
        source_kind: str = "thought_engine",
        kind: str = "PROJECT_GOAL",
        suggested_priority: float = 0.9,
    ) -> GoalCandidate:
        return GoalCandidate(
            schema="kaliv-consciousness-core/goal-candidate/v1",
            candidate_id="gcand-" + suffix * 32,
            self_id=SELF_ID,
            person_revision=PERSON_REVISION,
            kind=kind,
            statement="Finish the current ModelRig workstream safely.",
            source_kind=source_kind,
            source_refs=["thought-proposal:proposal-1"],
            suggested_priority=suggested_priority,
            confidence=0.8,
            parent_goal_ref=None,
            constraints=["preserve existing authority boundaries"],
            success_conditions=["validated implementation evidence exists"],
            production_activation=False,
        )

    def admission(
        self,
        candidate: GoalCandidate,
        *,
        authority: str = "operator_review",
        priority: float = 0.7,
        sequence: int = 10,
    ) -> GoalAdmissionEvidence:
        return GoalAdmissionEvidence(
            schema="kaliv-consciousness-core/goal-admission-evidence/v1",
            candidate_id=candidate.candidate_id,
            authority=authority,
            source_refs=["operator-review:1"],
            admitted_priority=priority,
            admitted_sequence=sequence,
            production_activation=False,
        )

    def active_goal(
        self,
        *,
        suffix: str = "3",
        priority: float = 0.7,
        sequence: int = 10,
    ) -> GoalRecord:
        candidate = self.candidate(suffix=suffix)
        return admit_goal(
            candidate,
            self.admission(
                candidate,
                priority=priority,
                sequence=sequence,
            ),
        )

    def test_thought_engine_candidate_requires_independent_admission(self) -> None:
        candidate = self.candidate()
        fields = set(GoalCandidate.model_fields)
        self.assertNotIn("active", fields)
        self.assertNotIn("status", fields)
        self.assertNotIn("execute", fields)

        goal = admit_goal(candidate, self.admission(candidate))
        self.assertEqual(goal.status, "active")
        self.assertEqual(goal.admission_authority, "operator_review")
        self.assertIn("operator-review:1", goal.source_refs)

    def test_admission_must_bind_exact_candidate(self) -> None:
        candidate = self.candidate()
        other = self.admission(candidate).model_copy(
            update={"candidate_id": "gcand-" + "9" * 32}
        )
        with self.assertRaises(GoalContractError):
            admit_goal(candidate, other)

    def test_admitted_priority_is_policy_owned_not_model_suggestion(self) -> None:
        candidate = self.candidate(suggested_priority=0.99)
        goal = admit_goal(
            candidate,
            self.admission(candidate, priority=0.35),
        )
        self.assertAlmostEqual(goal.priority, 0.35)
        self.assertNotEqual(goal.priority, candidate.suggested_priority)

    def test_model_assertion_alone_cannot_complete_goal(self) -> None:
        goal = self.active_goal()
        with self.assertRaises(GoalContractError):
            transition_goal(
                goal,
                new_status="completed",
                sequence=20,
                evidence_refs=["thought-proposal:claimed-success"],
            )

        completed = transition_goal(
            goal,
            new_status="completed",
            sequence=20,
            evidence_refs=["tool-result:verified-success"],
        )
        self.assertEqual(completed.status, "completed")
        self.assertIn("tool-result:verified-success", completed.transition_evidence_refs)

    def test_terminal_goal_cannot_reactivate(self) -> None:
        goal = transition_goal(
            self.active_goal(),
            new_status="completed",
            sequence=20,
            evidence_refs=["tool-result:verified-success"],
        )
        with self.assertRaises(GoalContractError):
            transition_goal(
                goal,
                new_status="active",
                sequence=21,
                evidence_refs=["operator:retry"],
            )

    def test_transition_sequence_cannot_move_backwards(self) -> None:
        goal = self.active_goal(sequence=10)
        with self.assertRaises(GoalContractError):
            transition_goal(
                goal,
                new_status="paused",
                sequence=9,
                evidence_refs=["user:pause"],
            )

    def test_goal_arbitration_is_deterministic_and_expiry_aware(self) -> None:
        low = self.active_goal(suffix="3", priority=0.4, sequence=10)
        high = self.active_goal(suffix="4", priority=0.9, sequence=11)
        chosen = select_next_goal([low, high], current_sequence=12)
        self.assertEqual(chosen, high)

        expired_high = high.model_copy(update={"expiry_sequence": 11})
        chosen_after_expiry = select_next_goal(
            [low, expired_high],
            current_sequence=12,
        )
        self.assertEqual(chosen_after_expiry, low)

    def test_paused_or_blocked_goal_is_not_selected(self) -> None:
        goal = self.active_goal()
        paused = transition_goal(
            goal,
            new_status="paused",
            sequence=11,
            evidence_refs=["user:pause"],
        )
        self.assertIsNone(select_next_goal([paused], current_sequence=12))

    def test_intention_requires_active_goal(self) -> None:
        goal = self.active_goal()
        intention = select_intention(
            goal,
            cycle_id=CYCLE,
            statement="Inspect current CI state.",
            rationale_refs=["goal-state:current"],
            predicted_outcome_refs=["prediction:ci-status"],
            required_authority="agent3",
        )
        self.assertIsInstance(intention, IntentionRecord)
        self.assertEqual(intention.status, "selected")
        self.assertEqual(intention.required_authority, "agent3")

        paused = transition_goal(
            goal,
            new_status="paused",
            sequence=11,
            evidence_refs=["user:pause"],
        )
        with self.assertRaises(GoalContractError):
            select_intention(
                paused,
                cycle_id=CYCLE,
                statement="Should not select.",
                rationale_refs=["goal-state:paused"],
                predicted_outcome_refs=[],
                required_authority="none",
            )

    def test_agent3_handoff_is_proposal_only(self) -> None:
        intention = select_intention(
            self.active_goal(),
            cycle_id=CYCLE,
            statement="Inspect repository state.",
            rationale_refs=["goal-state:current"],
            predicted_outcome_refs=["prediction:read-only"],
            required_authority="agent3",
        )
        handoff = build_agent3_handoff(intention)
        self.assertIsInstance(handoff, Agent3IntentHandoff)
        self.assertFalse(handoff.execution_started)
        self.assertEqual(handoff.required_authority, "agent3")
        fields = set(Agent3IntentHandoff.model_fields)
        self.assertNotIn("tools", fields)
        self.assertNotIn("plan", fields)
        self.assertNotIn("confirmation", fields)

    def test_non_agent3_intention_cannot_build_agent3_handoff(self) -> None:
        intention = select_intention(
            self.active_goal(),
            cycle_id=CYCLE,
            statement="Speak a response.",
            rationale_refs=["goal-state:current"],
            predicted_outcome_refs=[],
            required_authority="voicerig",
        )
        with self.assertRaises(GoalContractError):
            build_agent3_handoff(intention)

    def test_curiosity_goal_grants_no_execution_or_scheduler_authority(self) -> None:
        candidate = self.candidate(
            kind="CURIOSITY_GOAL",
            source_kind="thought_engine",
        )
        goal = admit_goal(
            candidate,
            self.admission(candidate, authority="maintenance_policy"),
        )
        self.assertEqual(goal.status, "active")
        fields = set(GoalRecord.model_fields)
        self.assertNotIn("actions", fields)
        self.assertNotIn("tools", fields)
        self.assertNotIn("schedule", fields)
        self.assertNotIn("run_id", fields)

    def test_goal_roundtrip_survives_restart_without_model_identity(self) -> None:
        goal = self.active_goal()
        restored = GoalRecord.model_validate_json(goal.model_dump_json())
        self.assertEqual(restored, goal)
        fields = set(GoalRecord.model_fields)
        self.assertNotIn("model", fields)
        self.assertNotIn("provider", fields)
        self.assertNotIn("engine_instance_id", fields)

    def test_arbitration_has_no_model_or_profile_input(self) -> None:
        signature = inspect.signature(select_next_goal)
        self.assertNotIn("model", signature.parameters)
        self.assertNotIn("provider", signature.parameters)
        self.assertNotIn("cognitive_profile", signature.parameters)

    def test_c9a_has_no_scheduler_executor_or_database_import(self) -> None:
        source = (
            ROOT / "worker" / "app" / "consciousness_core" / "goals.py"
        ).read_text(encoding="utf-8")
        for forbidden in (
            "import sqlite3",
            "schedule_service",
            "ScheduleStore",
            "Agent3Orchestrator",
            "ToolGate",
            "run_tool",
            "create_task(",
        ):
            self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main(verbosity=2)
