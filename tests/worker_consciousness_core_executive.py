#!/usr/bin/env python3
"""C16 cognitive executive / proposal adjudication tests.

Run:
    PYTHONPATH=worker python3 tests/worker_consciousness_core_executive.py
"""
from __future__ import annotations

import asyncio
import copy
import json
import sys
import unittest
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "worker") not in sys.path:
    sys.path.insert(0, str(ROOT / "worker"))

from app.consciousness_core import (  # noqa: E402
    CognitiveCycleCoordinator,
    CognitiveExecutiveError,
    CognitiveProfile,
    ConsciousnessCoreRuntime,
    ExecutivePolicy,
    GoalAdmissionEvidence,
    GoalCandidate,
    PersistentSelfState,
    PersonalitySnapshot,
    RuntimeWorldState,
    SelfAffect,
    WorkspaceCandidate,
    WorldObservation,
    adjudicate_cycle,
    admit_goal,
    build_workspace,
    initial_metacognitive_state,
    self_state_ref,
    workspace_ref,
    world_state_ref,
)


FIXTURES = json.loads(
    (ROOT / "contracts" / "consciousness-core" / "fixtures-v1.json").read_text(
        encoding="utf-8"
    )
)


def run(coro):
    return asyncio.run(coro)


class StaticEngine:
    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload

    async def think(self, request, cognitive_profile, *, context=None):
        payload = copy.deepcopy(self.payload)
        payload["request_id"] = request.request_id
        return payload


class CognitiveExecutiveTests(unittest.TestCase):
    def world(self) -> RuntimeWorldState:
        return RuntimeWorldState(
            schema="kaliv-consciousness-core/world-state/v1",
            world_id="world-" + "c" * 32,
            revision=3,
            observations=[
                WorldObservation(
                    observation_id="obs-" + "d" * 32,
                    subject_ref="project:modelrig",
                    proposition="C16 is under isolated evaluation.",
                    confidence=1.0,
                    epistemic_status="observed",
                    source_refs=["github:branch:c16"],
                )
            ],
            production_activation=False,
        )

    def workspace(self):
        return build_workspace(
            cycle_id="cycle-" + "e" * 32,
            max_active=2,
            candidates=[
                WorkspaceCandidate(
                    candidate_id="wc-" + "1" * 32,
                    kind="perception",
                    salience=0.95,
                    summary="The user asked Consciousness Core to continue.",
                    source_ref="event:user-turn",
                ),
                WorkspaceCandidate(
                    candidate_id="wc-" + "2" * 32,
                    kind="goal",
                    salience=0.8,
                    summary="Advance the architecture without crossing authority boundaries.",
                    source_ref="goal:consciousness-core",
                ),
            ],
        )

    def personality(self) -> PersonalitySnapshot:
        return PersonalitySnapshot(
            person_revision="person-r0007",
            personality_revision="personality-r0005",
            personality_state_ref="personality-state:pstate-" + "7" * 32,
            source_refs=["person-profile:person-r0007"],
        )

    def profile(self, suffix: str = "f") -> CognitiveProfile:
        return CognitiveProfile(
            schema="kaliv-consciousness-core/cognitive-profile/v1",
            profile_id="cog-" + suffix * 32,
            engine_instance_id="engine:test:" + suffix,
            provider="mock",
            model="model-" + suffix,
            reasoning_depth=0.9,
            planning_capacity=0.9,
            context_capacity_tokens=8192,
            multimodal_capacity=0.0,
            tool_reasoning=0.0,
            uncertainty_calibration=0.9,
            ephemeral=True,
            identity_authority=False,
            persistent_state_authority=False,
            action_authority=False,
            production_activation=False,
        )

    def state(self, world, workspace, personality) -> PersistentSelfState:
        return PersistentSelfState(
            schema="kaliv-consciousness-core/self-state/v1",
            self_id="self-" + "a" * 32,
            revision=4,
            person_id="person-" + "b" * 32,
            person_revision=personality.person_revision,
            personality_state_ref=personality.personality_state_ref,
            world_state_ref=world_state_ref(world),
            workspace_ref=workspace_ref(workspace),
            active_goal_refs=["goal:consciousness-core"],
            active_intention_refs=[],
            affect=SelfAffect(
                labels=["curious"],
                valence=0.2,
                arousal=0.3,
                confidence=0.9,
                source_refs=["event:user-turn"],
            ),
            known_uncertainties=[],
            last_experience_ref=None,
            production_activation=False,
        )

    def proposal(self) -> dict[str, Any]:
        payload = copy.deepcopy(FIXTURES["thought_proposal"])
        payload["proposal_id"] = "thinkprop-" + "4" * 32
        payload["uncertainty"] = 0.05
        payload["attention_suggestions"] = ["wc-" + "1" * 32]
        payload["hypotheses"] = [
            {"summary": "The next safe step is bounded adjudication.", "confidence": 0.96}
        ]
        payload["candidate_intentions"] = [
            {
                "summary": "Inspect repository evidence through the existing authority.",
                "confidence": 0.95,
                "required_authority": "agent3",
            }
        ]
        payload["predicted_outcomes"] = [
            {
                "summary": "No execution occurs inside the executive.",
                "confidence": 0.97,
            }
        ]
        payload["memory_queries"] = ["Which prior decision established this boundary?"]
        payload["response_intent"] = "Explain the bounded decision clearly."
        payload["body_intent"] = "attentive listening"
        return payload

    def cycle(self, payload: dict[str, Any] | None = None, profile=None):
        world = self.world()
        workspace = self.workspace()
        personality = self.personality()
        state = self.state(world, workspace, personality)
        runtime = ConsciousnessCoreRuntime(StaticEngine(payload or self.proposal()))
        result = run(
            CognitiveCycleCoordinator(runtime).run(
                state=state,
                world=world,
                workspace=workspace,
                personality_snapshot=personality,
                profile=profile or self.profile(),
            )
        )
        return result, workspace, state

    def meta(self, state, **updates):
        meta = initial_metacognitive_state(self_ref=self_state_ref(state))
        if updates:
            meta = meta.model_copy(update=updates)
        return meta

    def active_goal(self, state):
        candidate = GoalCandidate(
            schema="kaliv-consciousness-core/goal-candidate/v1",
            candidate_id="gcand-" + "3" * 32,
            self_id=state.self_id,
            person_revision=state.person_revision,
            kind="PROJECT_GOAL",
            statement="Advance Consciousness Core safely.",
            source_kind="project_state",
            source_refs=["project:modelrig"],
            suggested_priority=0.8,
            confidence=0.9,
            parent_goal_ref=None,
            constraints=["preserve authority boundaries"],
            success_conditions=["C16 tests pass"],
            production_activation=False,
        )
        evidence = GoalAdmissionEvidence(
            schema="kaliv-consciousness-core/goal-admission-evidence/v1",
            candidate_id=candidate.candidate_id,
            authority="existing_project_commitment",
            source_refs=["project:modelrig"],
            admitted_priority=0.8,
            admitted_sequence=1,
            production_activation=False,
        )
        return admit_goal(candidate, evidence)

    def test_accept_clamps_confidence_and_never_selects_or_dispatches_intention(self):
        cycle, workspace, state = self.cycle()
        result = adjudicate_cycle(
            cycle,
            workspace=workspace,
            metacognition=self.meta(state),
            active_goal=self.active_goal(state),
        )

        self.assertEqual(result.receipt.decision, "ACCEPT_COGNITION")
        self.assertGreaterEqual(result.receipt.confidence_clipped_count, 3)
        self.assertEqual(result.hypotheses[0].effective_confidence, 0.75)
        self.assertEqual(result.intentions[0].effective_confidence, 0.75)
        self.assertEqual(result.predictions[0].confidence_before, 0.75)
        self.assertFalse(result.intentions[0].selected)
        self.assertFalse(result.intentions[0].dispatched)
        self.assertFalse(result.intentions[0].execution_authority)
        self.assertFalse(result.receipt.execution_authority)
        self.assertFalse(result.receipt.self_state_mutation_applied)
        self.assertFalse(result.receipt.durable_memory_write_authority)
        self.assertFalse(result.semantic_intents[0].dispatch_authority)

    def test_verify_blocks_action_semantics_but_keeps_evidence_candidates(self):
        cycle, workspace, state = self.cycle()
        result = adjudicate_cycle(
            cycle,
            workspace=workspace,
            metacognition=self.meta(state, verification_required=True),
        )

        self.assertEqual(result.receipt.decision, "VERIFY")
        self.assertTrue(result.hypotheses)
        self.assertTrue(result.predictions)
        self.assertTrue(result.memory_queries)
        self.assertEqual(result.intentions, [])
        self.assertEqual(result.semantic_intents, [])
        self.assertFalse(result.memory_queries[0].read_requested)
        self.assertFalse(result.memory_queries[0].durable_write_authority)

    def test_decompose_precedes_acceptance_and_emits_no_downstream_candidates(self):
        cycle, workspace, state = self.cycle()
        result = adjudicate_cycle(
            cycle,
            workspace=workspace,
            metacognition=self.meta(
                state,
                decomposition_required=True,
                verification_required=True,
            ),
        )
        self.assertEqual(result.receipt.decision, "DECOMPOSE")
        self.assertEqual(result.hypotheses, [])
        self.assertEqual(result.intentions, [])
        self.assertEqual(result.predictions, [])
        self.assertEqual(result.memory_queries, [])
        self.assertEqual(result.semantic_intents, [])

    def test_empty_proposal_is_requeried(self):
        payload = self.proposal()
        payload.update(
            {
                "interpretation": "",
                "hypotheses": [],
                "candidate_intentions": [],
                "predicted_outcomes": [],
                "questions": [],
                "memory_queries": [],
                "attention_suggestions": [],
                "response_intent": None,
                "body_intent": None,
                "uncertainty": 0.1,
            }
        )
        cycle, workspace, state = self.cycle(payload)
        result = adjudicate_cycle(
            cycle,
            workspace=workspace,
            metacognition=self.meta(state),
        )
        self.assertEqual(result.receipt.decision, "REQUERY")

    def test_unknown_attention_reference_is_held_fail_closed(self):
        payload = self.proposal()
        payload["attention_suggestions"] = ["wc-" + "9" * 32]
        cycle, workspace, state = self.cycle(payload)
        result = adjudicate_cycle(
            cycle,
            workspace=workspace,
            metacognition=self.meta(state),
        )
        self.assertEqual(result.receipt.decision, "HOLD")
        self.assertEqual(result.receipt.accepted_attention_refs, [])
        self.assertEqual(result.receipt.rejected_attention_refs, ["wc-" + "9" * 32])
        self.assertEqual(result.intentions, [])

    def test_high_proposal_uncertainty_is_held(self):
        payload = self.proposal()
        payload["uncertainty"] = 0.9
        cycle, workspace, state = self.cycle(payload)
        result = adjudicate_cycle(
            cycle,
            workspace=workspace,
            metacognition=self.meta(state),
        )
        self.assertEqual(result.receipt.decision, "HOLD")

    def test_mid_uncertainty_requires_verification(self):
        payload = self.proposal()
        payload["uncertainty"] = 0.5
        cycle, workspace, state = self.cycle(payload)
        result = adjudicate_cycle(
            cycle,
            workspace=workspace,
            metacognition=self.meta(state),
        )
        self.assertEqual(result.receipt.decision, "VERIFY")
        self.assertEqual(result.intentions, [])
        self.assertEqual(result.semantic_intents, [])

    def test_cycle_workspace_binding_mismatch_fails_closed(self):
        cycle, workspace, state = self.cycle()
        other = build_workspace(
            cycle_id=workspace.cycle_id,
            max_active=1,
            candidates=[
                WorkspaceCandidate(
                    candidate_id="wc-" + "8" * 32,
                    kind="perception",
                    salience=1.0,
                    summary="Different bound workspace.",
                    source_ref="test:other",
                )
            ],
        )
        with self.assertRaises(CognitiveExecutiveError):
            adjudicate_cycle(
                cycle,
                workspace=other,
                metacognition=self.meta(state),
            )

    def test_goal_binding_must_match_self_and_person_revision(self):
        cycle, workspace, state = self.cycle()
        goal = self.active_goal(state)
        wrong = goal.model_copy(update={"self_id": "self-" + "9" * 32})
        with self.assertRaises(CognitiveExecutiveError):
            adjudicate_cycle(
                cycle,
                workspace=workspace,
                metacognition=self.meta(state),
                active_goal=wrong,
            )

    def test_policy_is_model_independent(self):
        cycle_a, workspace_a, state_a = self.cycle(profile=self.profile("a"))
        cycle_f, workspace_f, state_f = self.cycle(profile=self.profile("f"))

        policy = ExecutivePolicy(
            schema="kaliv-consciousness-core/executive-policy/v1",
            hold_uncertainty_threshold=0.85,
            verify_uncertainty_threshold=0.45,
            verify_task_uncertainty_threshold=0.60,
            allow_verify_memory_queries=True,
            production_activation=False,
        )
        a = adjudicate_cycle(
            cycle_a,
            workspace=workspace_a,
            metacognition=self.meta(state_a),
            policy=policy,
        )
        f = adjudicate_cycle(
            cycle_f,
            workspace=workspace_f,
            metacognition=self.meta(state_f),
            policy=policy,
        )
        self.assertEqual(a.receipt.decision, f.receipt.decision)
        self.assertEqual(a.receipt.policy_ref, f.receipt.policy_ref)


if __name__ == "__main__":
    unittest.main(verbosity=2)
