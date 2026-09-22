#!/usr/bin/env python3
"""C15 cognitive-cycle and inner-monologue boundary tests.

Run:
    PYTHONPATH=worker python3 tests/worker_consciousness_core_cycle.py
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
    CognitiveCycleError,
    CognitiveProfile,
    ConsciousnessCoreRuntime,
    PersistentSelfState,
    PersonalitySnapshot,
    RuntimeWorldState,
    SelfAffect,
    ThoughtEngineContractError,
    WorkspaceCandidate,
    WorldObservation,
    build_workspace,
    cognitive_profile_ref,
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


class ContextAwareEngine:
    def __init__(self) -> None:
        self.calls = 0
        self.context: dict[str, Any] | None = None
        self.profile: CognitiveProfile | None = None

    async def think(self, request, cognitive_profile, *, context=None):
        self.calls += 1
        self.context = copy.deepcopy(context)
        self.profile = cognitive_profile
        payload = copy.deepcopy(FIXTURES["thought_proposal"])
        payload["request_id"] = request.request_id
        payload["proposal_id"] = (
            "thinkprop-"
            + ("1" if cognitive_profile.reasoning_depth < 0.5 else "2") * 32
        )
        payload["interpretation"] = (
            "bounded shallow interpretation"
            if cognitive_profile.reasoning_depth < 0.5
            else "bounded deep interpretation"
        )
        payload["uncertainty"] = (
            0.4 if cognitive_profile.reasoning_depth < 0.5 else 0.08
        )
        return payload


class WrongBindingEngine:
    async def think(self, request, cognitive_profile, *, context=None):
        payload = copy.deepcopy(FIXTURES["thought_proposal"])
        payload["request_id"] = "thinkreq-" + "9" * 32
        return payload


class CognitiveCycleTests(unittest.TestCase):
    def world(self) -> RuntimeWorldState:
        return RuntimeWorldState(
            schema="kaliv-consciousness-core/world-state/v1",
            world_id="world-" + "c" * 32,
            revision=7,
            observations=[
                WorldObservation(
                    observation_id="obs-" + "d" * 32,
                    subject_ref="project:modelrig",
                    proposition="C15 is being evaluated on an isolated branch.",
                    confidence=1.0,
                    epistemic_status="observed",
                    source_refs=["github:branch:c15"],
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
                    candidate_id="wc-" + "2" * 32,
                    kind="memory",
                    salience=0.8,
                    summary="Remember the persistent-self invariant.",
                    source_ref="memory4:record:continuity",
                ),
                WorkspaceCandidate(
                    candidate_id="wc-" + "1" * 32,
                    kind="perception",
                    salience=0.95,
                    summary="The user asked the Core to continue.",
                    source_ref="event:user-turn",
                ),
                WorkspaceCandidate(
                    candidate_id="wc-" + "3" * 32,
                    kind="goal",
                    salience=0.8,
                    summary="Advance the cognitive architecture carefully.",
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

    def profile(self, *, strong: bool = True) -> CognitiveProfile:
        marker = "f" if strong else "a"
        return CognitiveProfile(
            schema="kaliv-consciousness-core/cognitive-profile/v1",
            profile_id="cog-" + marker * 32,
            engine_instance_id="engine:test:" + ("strong" if strong else "weak"),
            provider="mock",
            model="strong-model" if strong else "weak-model",
            reasoning_depth=0.95 if strong else 0.25,
            planning_capacity=0.95 if strong else 0.25,
            context_capacity_tokens=8192 if strong else 2048,
            multimodal_capacity=0.0,
            tool_reasoning=0.0,
            uncertainty_calibration=0.9 if strong else 0.4,
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
            revision=12,
            person_id="person-" + "b" * 32,
            person_revision=personality.person_revision,
            personality_state_ref=personality.personality_state_ref,
            world_state_ref=world_state_ref(world),
            workspace_ref=workspace_ref(workspace),
            active_goal_refs=["goal:consciousness-core"],
            active_intention_refs=["intent:continue-c15"],
            affect=SelfAffect(
                labels=["curious"],
                valence=0.2,
                arousal=0.35,
                confidence=0.9,
                source_refs=["event:user-turn"],
            ),
            known_uncertainties=[],
            last_experience_ref=None,
            production_activation=False,
        )

    def context(self):
        world = self.world()
        workspace = self.workspace()
        personality = self.personality()
        state = self.state(world, workspace, personality)
        return state, world, workspace, personality

    def test_workspace_selection_is_bounded_and_deterministic(self) -> None:
        workspace = self.workspace()
        self.assertEqual(
            workspace.selected_candidate_ids,
            [
                "wc-" + "1" * 32,
                "wc-" + "2" * 32,
            ],
        )
        self.assertEqual(workspace.max_active, 2)
        self.assertEqual(len(workspace.candidates), 3)

    def test_exact_state_world_workspace_binding_is_required(self) -> None:
        state, world, workspace, personality = self.context()
        engine = ContextAwareEngine()
        coordinator = CognitiveCycleCoordinator(ConsciousnessCoreRuntime(engine))

        result = run(
            coordinator.run(
                state=state,
                world=world,
                workspace=workspace,
                personality_snapshot=personality,
                profile=self.profile(),
                relevant_memory_refs=["memory4:record:continuity"],
            )
        )
        self.assertEqual(result.request.self_state_ref, self_state_ref(state))
        self.assertEqual(result.request.world_state_ref, world_state_ref(world))
        self.assertEqual(result.request.workspace_ref, workspace_ref(workspace))

        changed_world = world.model_copy(update={"revision": world.revision + 1})
        with self.assertRaises(CognitiveCycleError):
            run(
                coordinator.run(
                    state=state,
                    world=changed_world,
                    workspace=workspace,
                    personality_snapshot=personality,
                    profile=self.profile(),
                )
            )

    def test_model_receives_bounded_materialized_context_not_authority(self) -> None:
        state, world, workspace, personality = self.context()
        engine = ContextAwareEngine()
        result = run(
            CognitiveCycleCoordinator(ConsciousnessCoreRuntime(engine)).run(
                state=state,
                world=world,
                workspace=workspace,
                personality_snapshot=personality,
                profile=self.profile(),
                relevant_memory_refs=[
                    "memory4:record:continuity",
                    "memory4:record:continuity",
                ],
                embodiment_state_ref="embodiment:observed:42",
                requested_reasoning_mode="verify",
            )
        )

        self.assertEqual(engine.calls, 1)
        self.assertIsNotNone(engine.context)
        assert engine.context is not None
        self.assertEqual(engine.context["self_state"]["self_id"], state.self_id)
        self.assertEqual(
            engine.context["world_state"]["observations"][0]["proposition"],
            world.observations[0].proposition,
        )
        self.assertEqual(
            engine.context["workspace"]["selected_candidate_ids"],
            workspace.selected_candidate_ids,
        )
        self.assertEqual(
            engine.context["relevant_memory_refs"],
            ["memory4:record:continuity"],
        )
        self.assertNotIn("memory_contents", engine.context)
        self.assertEqual(result.request.requested_reasoning_mode, "verify")
        self.assertEqual(
            result.request.cognitive_profile_ref,
            cognitive_profile_ref(self.profile()),
        )

    def test_cycle_receipt_proves_no_model_state_or_execution_authority(self) -> None:
        state, world, workspace, personality = self.context()
        before = state.model_dump(mode="json")
        result = run(
            CognitiveCycleCoordinator(
                ConsciousnessCoreRuntime(ContextAwareEngine())
            ).run(
                state=state,
                world=world,
                workspace=workspace,
                personality_snapshot=personality,
                profile=self.profile(),
            )
        )

        receipt = result.receipt
        self.assertTrue(receipt.self_state_unchanged)
        self.assertEqual(receipt.self_revision_before, 12)
        self.assertEqual(receipt.self_revision_after, 12)
        self.assertFalse(receipt.model_state_mutation_applied)
        self.assertFalse(receipt.execution_authority)
        self.assertFalse(receipt.scheduling_authority)
        self.assertFalse(receipt.durable_memory_write_authority)
        self.assertFalse(receipt.raw_chain_of_thought_persisted)
        self.assertEqual(state.model_dump(mode="json"), before)
        self.assertEqual(result.proposal.actions, [])
        self.assertEqual(result.proposal.state_mutations, [])

    def test_model_swap_changes_cognition_not_self_or_person_binding(self) -> None:
        state, world, workspace, personality = self.context()
        before_ref = self_state_ref(state)

        weak_engine = ContextAwareEngine()
        strong_engine = ContextAwareEngine()
        weak = run(
            CognitiveCycleCoordinator(
                ConsciousnessCoreRuntime(weak_engine)
            ).run(
                state=state,
                world=world,
                workspace=workspace,
                personality_snapshot=personality,
                profile=self.profile(strong=False),
            )
        )
        strong = run(
            CognitiveCycleCoordinator(
                ConsciousnessCoreRuntime(strong_engine)
            ).run(
                state=state,
                world=world,
                workspace=workspace,
                personality_snapshot=personality,
                profile=self.profile(strong=True),
            )
        )

        self.assertNotEqual(weak.proposal.proposal_id, strong.proposal.proposal_id)
        self.assertNotEqual(
            weak.proposal.interpretation,
            strong.proposal.interpretation,
        )
        self.assertGreater(weak.proposal.uncertainty, strong.proposal.uncertainty)
        for result in (weak, strong):
            self.assertEqual(result.receipt.self_state_ref, before_ref)
            self.assertEqual(result.receipt.self_id, state.self_id)
            self.assertEqual(result.receipt.person_id, state.person_id)
            self.assertEqual(result.receipt.person_revision, state.person_revision)
            self.assertTrue(result.receipt.self_state_unchanged)

    def test_wrong_proposal_request_binding_still_fails_closed(self) -> None:
        state, world, workspace, personality = self.context()
        coordinator = CognitiveCycleCoordinator(
            ConsciousnessCoreRuntime(WrongBindingEngine())
        )
        with self.assertRaises(ThoughtEngineContractError):
            run(
                coordinator.run(
                    state=state,
                    world=world,
                    workspace=workspace,
                    personality_snapshot=personality,
                    profile=self.profile(),
                )
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)
