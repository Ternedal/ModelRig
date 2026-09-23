#!/usr/bin/env python3
"""C16 deterministic post-cycle reducer tests.

Run:
    PYTHONPATH=worker python3 tests/worker_consciousness_core_reducer.py
"""
from __future__ import annotations

import asyncio
import copy
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "worker") not in sys.path:
    sys.path.insert(0, str(ROOT / "worker"))

from app.consciousness_core import (  # noqa: E402
    CognitiveCycleCoordinator,
    CognitiveProfile,
    ConsciousnessCoreRuntime,
    PersistentSelfState,
    PersonalitySnapshot,
    RuntimeWorldState,
    SelfAffect,
    WorkspaceCandidate,
    WorldObservation,
    build_workspace,
    workspace_ref,
    world_state_ref,
)
from app.consciousness_core.reducer import (  # noqa: E402
    PostCycleReductionError,
    reduce_post_cycle,
)


FIXTURES = json.loads(
    (ROOT / "contracts" / "consciousness-core" / "fixtures-v1.json").read_text(
        encoding="utf-8"
    )
)


def run(coro):
    return asyncio.run(coro)


class ReducerEngine:
    def __init__(self, *, attention_suggestions=None, interpretation=None) -> None:
        self.attention_suggestions = attention_suggestions
        self.interpretation = interpretation

    async def think(self, request, cognitive_profile, *, context=None):
        payload = copy.deepcopy(FIXTURES["thought_proposal"])
        payload["request_id"] = request.request_id
        payload["proposal_id"] = "thinkprop-" + "6" * 32
        payload["uncertainty"] = 0.20
        payload["attention_suggestions"] = (
            self.attention_suggestions
            if self.attention_suggestions is not None
            else ["wc-" + "2" * 32]
        )
        payload["interpretation"] = (
            self.interpretation
            if self.interpretation is not None
            else "Carry the verified result into the next bounded cognitive moment."
        )
        return payload


class PostCycleReducerTests(unittest.TestCase):
    def world(self) -> RuntimeWorldState:
        return RuntimeWorldState(
            schema="kaliv-consciousness-core/world-state/v1",
            world_id="world-" + "c" * 32,
            revision=8,
            observations=[
                WorldObservation(
                    observation_id="obs-" + "d" * 32,
                    subject_ref="project:modelrig",
                    proposition="C16 is running on an isolated stacked branch.",
                    confidence=1.0,
                    epistemic_status="observed",
                    source_refs=["github:issue:1644"],
                )
            ],
            production_activation=False,
        )

    def workspace(self):
        return build_workspace(
            cycle_id="cycle-" + "e" * 32,
            max_active=3,
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
                    kind="memory",
                    salience=0.70,
                    summary="Identity persists while cognition is replaceable.",
                    source_ref="memory4:continuity-invariant",
                ),
                WorkspaceCandidate(
                    candidate_id="wc-" + "3" * 32,
                    kind="goal",
                    salience=0.65,
                    summary="Advance the Core without granting model authority.",
                    source_ref="goal:consciousness-core",
                ),
            ],
        )

    def personality(self) -> PersonalitySnapshot:
        return PersonalitySnapshot(
            person_revision="person-r0007",
            personality_revision="personality-r0005",
            personality_state_ref="personality-state:pstate-" + "7" * 32,
            source_refs=[
                "person-profile:person-r0007",
                "bodyrig:movement-identity:active",
                "voicerig:voice:active",
            ],
        )

    def profile(self) -> CognitiveProfile:
        return CognitiveProfile(
            schema="kaliv-consciousness-core/cognitive-profile/v1",
            profile_id="cog-" + "f" * 32,
            engine_instance_id="engine:test:c16",
            provider="mock",
            model="replaceable-cognition",
            reasoning_depth=0.8,
            planning_capacity=0.8,
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
            revision=13,
            person_id="person-" + "b" * 32,
            person_revision=personality.person_revision,
            personality_state_ref=personality.personality_state_ref,
            world_state_ref=world_state_ref(world),
            workspace_ref=workspace_ref(workspace),
            active_goal_refs=["goal:consciousness-core"],
            active_intention_refs=["intent:continue-core"],
            affect=SelfAffect(
                labels=["curious"],
                valence=0.2,
                arousal=0.35,
                confidence=0.9,
                source_refs=["event:user-turn"],
            ),
            known_uncertainties=[],
            last_experience_ref="memory4:experience:last",
            production_activation=False,
        )

    def cycle_result(self, engine=None):
        world = self.world()
        workspace = self.workspace()
        personality = self.personality()
        state = self.state(world, workspace, personality)
        result = run(
            CognitiveCycleCoordinator(
                ConsciousnessCoreRuntime(engine or ReducerEngine())
            ).run(
                state=state,
                world=world,
                workspace=workspace,
                personality_snapshot=personality,
                profile=self.profile(),
                relevant_memory_refs=["memory4:continuity-invariant"],
            )
        )
        return state, workspace, result

    def test_reducer_advances_only_workspace_binding_and_revision(self) -> None:
        state, workspace, result = self.cycle_result()
        reduced = reduce_post_cycle(
            result,
            current_state=state,
            current_workspace=workspace,
        )

        self.assertEqual(reduced.next_self_state.revision, state.revision + 1)
        self.assertNotEqual(reduced.next_self_state.workspace_ref, state.workspace_ref)
        self.assertEqual(reduced.next_self_state.self_id, state.self_id)
        self.assertEqual(reduced.next_self_state.person_id, state.person_id)
        self.assertEqual(reduced.next_self_state.person_revision, state.person_revision)
        self.assertEqual(
            reduced.next_self_state.personality_state_ref,
            state.personality_state_ref,
        )
        self.assertEqual(reduced.next_self_state.world_state_ref, state.world_state_ref)
        self.assertEqual(
            reduced.next_self_state.active_goal_refs,
            state.active_goal_refs,
        )
        self.assertEqual(
            reduced.next_self_state.active_intention_refs,
            state.active_intention_refs,
        )
        self.assertEqual(reduced.next_self_state.affect, state.affect)
        self.assertEqual(
            reduced.next_self_state.known_uncertainties,
            state.known_uncertainties,
        )
        self.assertEqual(
            reduced.next_self_state.last_experience_ref,
            state.last_experience_ref,
        )

    def test_thought_result_becomes_bounded_transient_workspace_material(self) -> None:
        state, workspace, result = self.cycle_result()
        reduced = reduce_post_cycle(
            result,
            current_state=state,
            current_workspace=workspace,
        )
        thought = next(
            item
            for item in reduced.next_workspace.candidates
            if item.candidate_id == reduced.receipt.thought_result_candidate_id
        )
        self.assertEqual(thought.kind, "thought_result")
        self.assertTrue(thought.source_ref.startswith("thought-proposal:"))
        self.assertEqual(thought.summary, result.proposal.interpretation)
        self.assertLessEqual(len(thought.summary), 2048)
        self.assertFalse(reduced.receipt.raw_chain_of_thought_persisted)

    def test_attention_suggestion_can_only_boost_known_material(self) -> None:
        state, workspace, result = self.cycle_result(
            ReducerEngine(
                attention_suggestions=[
                    "wc-" + "2" * 32,
                    "invented:authority",
                ]
            )
        )
        reduced = reduce_post_cycle(
            result,
            current_state=state,
            current_workspace=workspace,
        )

        self.assertEqual(
            reduced.receipt.accepted_attention_targets,
            ["wc-" + "2" * 32],
        )
        carried = {
            item.candidate_id: item
            for item in reduced.next_workspace.candidates
            if item.candidate_id != reduced.receipt.thought_result_candidate_id
        }
        self.assertEqual(carried["wc-" + "2" * 32].salience, 0.75)
        self.assertNotIn(
            "invented:authority",
            [item.source_ref for item in reduced.next_workspace.candidates],
        )

    def test_empty_interpretation_gets_non_model_fallback_summary(self) -> None:
        state, workspace, result = self.cycle_result(
            ReducerEngine(interpretation="")
        )
        reduced = reduce_post_cycle(
            result,
            current_state=state,
            current_workspace=workspace,
        )
        thought = next(
            item
            for item in reduced.next_workspace.candidates
            if item.candidate_id == reduced.receipt.thought_result_candidate_id
        )
        self.assertTrue(thought.summary.startswith("Completed thought proposal "))

    def test_stale_workspace_fails_closed(self) -> None:
        state, workspace, result = self.cycle_result()
        changed = workspace.model_copy(
            update={"cycle_id": "cycle-" + "9" * 32}
        )
        with self.assertRaises(PostCycleReductionError):
            reduce_post_cycle(
                result,
                current_state=state,
                current_workspace=changed,
            )

    def test_stale_self_revision_fails_closed(self) -> None:
        state, workspace, result = self.cycle_result()
        changed = state.model_copy(update={"revision": state.revision + 1})
        with self.assertRaises(PostCycleReductionError):
            reduce_post_cycle(
                result,
                current_state=changed,
                current_workspace=workspace,
            )

    def test_receipt_grants_no_store_or_execution_authority(self) -> None:
        state, workspace, result = self.cycle_result()
        reduced = reduce_post_cycle(
            result,
            current_state=state,
            current_workspace=workspace,
        )
        receipt = reduced.receipt
        self.assertFalse(receipt.model_state_mutation_applied)
        self.assertFalse(receipt.self_state_store_write_applied)
        self.assertFalse(receipt.durable_memory_write_authority)
        self.assertFalse(receipt.execution_authority)
        self.assertFalse(receipt.scheduling_authority)
        self.assertFalse(receipt.production_activation)


if __name__ == "__main__":
    unittest.main()
