#!/usr/bin/env python3
"""C17 bounded cognitive supervisor tests.

Run:
    PYTHONPATH=worker python3 tests/worker_consciousness_core_supervisor.py
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
    CognitiveProfile,
    CognitiveSupervisorError,
    ConsciousnessCoreRuntime,
    PersistentSelfState,
    PersonalitySnapshot,
    RuntimeWorldState,
    SelfAffect,
    SupervisorBudget,
    SupervisorProgress,
    WorkspaceCandidate,
    WorldObservation,
    adjudicate_cycle,
    build_workspace,
    initial_metacognitive_state,
    initial_supervisor_progress,
    plan_supervisor_step,
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


class CognitiveSupervisorTests(unittest.TestCase):
    def world(self) -> RuntimeWorldState:
        return RuntimeWorldState(
            schema="kaliv-consciousness-core/world-state/v1",
            world_id="world-" + "c" * 32,
            revision=5,
            observations=[
                WorldObservation(
                    observation_id="obs-" + "d" * 32,
                    subject_ref="project:modelrig",
                    proposition="C17 is being evaluated as an isolated control plane.",
                    confidence=1.0,
                    epistemic_status="observed",
                    source_refs=["github:branch:c17"],
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
                    summary="Keep cognition bounded and interruptible.",
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

    def profile(self) -> CognitiveProfile:
        return CognitiveProfile(
            schema="kaliv-consciousness-core/cognitive-profile/v1",
            profile_id="cog-" + "f" * 32,
            engine_instance_id="engine:test:c17",
            provider="mock",
            model="bounded-test",
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
            revision=8,
            person_id="person-" + "b" * 32,
            person_revision=personality.person_revision,
            personality_state_ref=personality.personality_state_ref,
            world_state_ref=world_state_ref(world),
            workspace_ref=workspace_ref(workspace),
            active_goal_refs=["goal:consciousness-core"],
            active_intention_refs=[],
            affect=SelfAffect(
                labels=["focused"],
                valence=0.1,
                arousal=0.4,
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
            {"summary": "A bounded next step is sufficient.", "confidence": 0.8}
        ]
        payload["candidate_intentions"] = []
        payload["predicted_outcomes"] = []
        payload["memory_queries"] = []
        payload["response_intent"] = None
        payload["body_intent"] = None
        return payload

    def context(self, payload: dict[str, Any] | None = None):
        world = self.world()
        workspace = self.workspace()
        personality = self.personality()
        state = self.state(world, workspace, personality)
        cycle = run(
            CognitiveCycleCoordinator(
                ConsciousnessCoreRuntime(StaticEngine(payload or self.proposal()))
            ).run(
                state=state,
                world=world,
                workspace=workspace,
                personality_snapshot=personality,
                profile=self.profile(),
            )
        )
        return cycle, workspace, state

    def executive(self, decision: str):
        payload = self.proposal()
        cycle, workspace, state = self.context(payload)
        meta = initial_metacognitive_state(self_ref=self_state_ref(state))

        if decision == "VERIFY":
            meta = meta.model_copy(update={"verification_required": True})
        elif decision == "DECOMPOSE":
            meta = meta.model_copy(update={"decomposition_required": True})
        elif decision == "REQUERY":
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
            cycle, workspace, state = self.context(payload)
            meta = initial_metacognitive_state(self_ref=self_state_ref(state))
        elif decision == "HOLD":
            payload["uncertainty"] = 0.95
            cycle, workspace, state = self.context(payload)
            meta = initial_metacognitive_state(self_ref=self_state_ref(state))

        result = adjudicate_cycle(
            cycle,
            workspace=workspace,
            metacognition=meta,
        )
        self.assertEqual(result.receipt.decision, decision)
        return result, cycle, workspace, state

    def test_accept_completes_without_next_cycle(self):
        executive, cycle, workspace, state = self.executive("ACCEPT_COGNITION")
        progress = initial_supervisor_progress(cycle_id=cycle.request.cycle_id)
        directive = plan_supervisor_step(
            executive,
            cycle=cycle,
            current_state=state,
            workspace=workspace,
            progress=progress,
        )
        self.assertEqual(directive.action, "COMPLETE")
        self.assertIsNone(directive.transition)
        self.assertEqual(directive.progress_if_executed, progress)

    def test_hold_pauses_without_next_cycle(self):
        executive, cycle, workspace, state = self.executive("HOLD")
        directive = plan_supervisor_step(
            executive,
            cycle=cycle,
            current_state=state,
            workspace=workspace,
            progress=initial_supervisor_progress(cycle_id=cycle.request.cycle_id),
        )
        self.assertEqual(directive.action, "PAUSE")
        self.assertIsNone(directive.transition)

    def test_interrupt_always_wins(self):
        executive, cycle, workspace, state = self.executive("VERIFY")
        directive = plan_supervisor_step(
            executive,
            cycle=cycle,
            current_state=state,
            workspace=workspace,
            progress=initial_supervisor_progress(cycle_id=cycle.request.cycle_id),
            interrupt_requested=True,
        )
        self.assertEqual(directive.action, "INTERRUPTED")
        self.assertTrue(directive.interrupt_observed)
        self.assertIsNone(directive.transition)

    def test_verify_plans_one_non_persisted_next_cycle(self):
        executive, cycle, workspace, state = self.executive("VERIFY")
        progress = initial_supervisor_progress(cycle_id=cycle.request.cycle_id)
        directive = plan_supervisor_step(
            executive,
            cycle=cycle,
            current_state=state,
            workspace=workspace,
            progress=progress,
        )
        self.assertEqual(directive.action, "NEXT_CYCLE")
        self.assertIsNotNone(directive.transition)
        transition = directive.transition
        assert transition is not None
        self.assertEqual(transition.next_reasoning_mode, "verify")
        self.assertNotEqual(transition.next_cycle_id, cycle.request.cycle_id)
        self.assertEqual(transition.next_workspace.cycle_id, transition.next_cycle_id)
        self.assertEqual(transition.next_self_state.self_id, state.self_id)
        self.assertEqual(transition.next_self_state.person_id, state.person_id)
        self.assertEqual(
            transition.next_self_state.person_revision,
            state.person_revision,
        )
        self.assertEqual(transition.next_self_state.revision, state.revision + 1)
        self.assertEqual(
            transition.next_self_state.workspace_ref,
            workspace_ref(transition.next_workspace),
        )
        self.assertFalse(transition.persistence_committed)
        self.assertFalse(transition.model_invoked)
        self.assertFalse(transition.execution_authority)
        self.assertFalse(transition.scheduling_authority)
        self.assertEqual(directive.progress_if_executed.cycles_consumed, 2)
        self.assertEqual(directive.progress_if_executed.verify_cycles_consumed, 1)

    def test_requery_and_decompose_map_to_bounded_reasoning_modes(self):
        for decision, expected_mode in (("REQUERY", "normal"), ("DECOMPOSE", "deep")):
            with self.subTest(decision=decision):
                executive, cycle, workspace, state = self.executive(decision)
                directive = plan_supervisor_step(
                    executive,
                    cycle=cycle,
                    current_state=state,
                    workspace=workspace,
                    progress=initial_supervisor_progress(
                        cycle_id=cycle.request.cycle_id
                    ),
                )
                self.assertEqual(directive.action, "NEXT_CYCLE")
                assert directive.transition is not None
                self.assertEqual(
                    directive.transition.next_reasoning_mode,
                    expected_mode,
                )

    def test_total_budget_hard_stops_next_cycle(self):
        executive, cycle, workspace, state = self.executive("VERIFY")
        progress = SupervisorProgress(
            schema="kaliv-consciousness-core/supervisor-progress/v1",
            root_cycle_id=cycle.request.cycle_id,
            last_cycle_id=cycle.request.cycle_id,
            cycles_consumed=2,
            verify_cycles_consumed=1,
            requery_cycles_consumed=0,
            decompose_cycles_consumed=0,
            production_activation=False,
        )
        directive = plan_supervisor_step(
            executive,
            cycle=cycle,
            current_state=state,
            workspace=workspace,
            progress=progress,
            budget=SupervisorBudget(
                schema="kaliv-consciousness-core/supervisor-budget/v1",
                max_cycles=2,
                max_verify_cycles=2,
                max_requery_cycles=1,
                max_decompose_cycles=1,
                production_activation=False,
            ),
        )
        self.assertEqual(directive.action, "BUDGET_EXHAUSTED")
        self.assertIsNone(directive.transition)

    def test_per_decision_budget_hard_stops(self):
        executive, cycle, workspace, state = self.executive("REQUERY")
        progress = SupervisorProgress(
            schema="kaliv-consciousness-core/supervisor-progress/v1",
            root_cycle_id=cycle.request.cycle_id,
            last_cycle_id=cycle.request.cycle_id,
            cycles_consumed=1,
            verify_cycles_consumed=0,
            requery_cycles_consumed=1,
            decompose_cycles_consumed=0,
            production_activation=False,
        )
        directive = plan_supervisor_step(
            executive,
            cycle=cycle,
            current_state=state,
            workspace=workspace,
            progress=progress,
            budget=SupervisorBudget(
                schema="kaliv-consciousness-core/supervisor-budget/v1",
                max_cycles=4,
                max_verify_cycles=2,
                max_requery_cycles=1,
                max_decompose_cycles=2,
                production_activation=False,
            ),
        )
        self.assertEqual(directive.action, "BUDGET_EXHAUSTED")

    def test_same_inputs_produce_same_transition(self):
        executive, cycle, workspace, state = self.executive("DECOMPOSE")
        progress = initial_supervisor_progress(cycle_id=cycle.request.cycle_id)
        first = plan_supervisor_step(
            executive,
            cycle=cycle,
            current_state=state,
            workspace=workspace,
            progress=progress,
        )
        second = plan_supervisor_step(
            executive,
            cycle=cycle,
            current_state=state,
            workspace=workspace,
            progress=progress,
        )
        self.assertEqual(first, second)

    def test_stale_progress_or_state_binding_fails_closed(self):
        executive, cycle, workspace, state = self.executive("VERIFY")
        stale_progress = initial_supervisor_progress(
            cycle_id="cycle-" + "9" * 32
        )
        with self.assertRaises(CognitiveSupervisorError):
            plan_supervisor_step(
                executive,
                cycle=cycle,
                current_state=state,
                workspace=workspace,
                progress=stale_progress,
            )

        wrong_state = state.model_copy(update={"revision": state.revision + 1})
        with self.assertRaises(CognitiveSupervisorError):
            plan_supervisor_step(
                executive,
                cycle=cycle,
                current_state=wrong_state,
                workspace=workspace,
                progress=initial_supervisor_progress(
                    cycle_id=cycle.request.cycle_id
                ),
            )

    def test_c17_has_no_model_scheduler_executor_or_store_calls(self):
        source = (
            ROOT / "worker" / "app" / "consciousness_core" / "supervisor.py"
        ).read_text(encoding="utf-8")
        for forbidden in (
            "OllamaThoughtEngine",
            "ConsciousnessCoreRuntime",
            "ollama_client",
            "schedule_service",
            "ScheduleStore",
            "Agent3Orchestrator",
            "ToolGate",
            "SelfStateStore(",
            "Memory4ExperienceBridge",
            "asyncio.create_task",
            "threading",
        ):
            self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main(verbosity=2)
