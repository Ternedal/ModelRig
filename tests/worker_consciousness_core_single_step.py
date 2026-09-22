#!/usr/bin/env python3
"""C18 exactly-one-cycle runtime runner tests.

Run:
    PYTHONPATH=worker python3 tests/worker_consciousness_core_single_step.py
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
    CognitiveSingleStepError,
    ConsciousnessCoreRuntime,
    PersistentSelfState,
    PersonalitySnapshot,
    RuntimeWorldState,
    SelfAffect,
    StateTransitionCommitReceipt,
    WorkspaceCandidate,
    WorldObservation,
    adjudicate_cycle,
    build_workspace,
    initial_metacognitive_state,
    initial_supervisor_progress,
    plan_supervisor_step,
    run_single_cognitive_step,
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
        self.calls = 0

    async def think(self, request, cognitive_profile, *, context=None):
        self.calls += 1
        payload = copy.deepcopy(self.payload)
        payload["request_id"] = request.request_id
        return payload


class RecordingCommitter:
    def __init__(self) -> None:
        self.calls = 0
        self.committed = False
        self.transition = None

    def commit(self, transition):
        self.calls += 1
        self.transition = transition
        self.committed = True
        return StateTransitionCommitReceipt(
            schema="kaliv-consciousness-core/state-transition-commit-receipt/v1",
            transition_id=transition.transition_id,
            from_self_state_ref=transition.from_self_state_ref,
            committed_self_state_ref=self_state_ref(transition.next_self_state),
            committed_revision=transition.next_self_state.revision,
            commit_ref=f"commit:test:{self.calls}",
            persisted=True,
            production_activation=False,
        )


class OrderAwareEngine:
    def __init__(
        self,
        committer: RecordingCommitter,
        payload: dict[str, Any],
        *,
        marker: str = "7",
        interpretation: str = "committed bounded cognition",
    ) -> None:
        self.committer = committer
        self.payload = payload
        self.marker = marker
        self.interpretation = interpretation
        self.calls = 0

    async def think(self, request, cognitive_profile, *, context=None):
        if not self.committer.committed:
            raise AssertionError("model was called before state commit")
        self.calls += 1
        payload = copy.deepcopy(self.payload)
        payload["request_id"] = request.request_id
        payload["proposal_id"] = "thinkprop-" + self.marker * 32
        payload["interpretation"] = self.interpretation
        return payload


class BadReceiptCommitter:
    def __init__(self) -> None:
        self.calls = 0

    def commit(self, transition):
        self.calls += 1
        return StateTransitionCommitReceipt(
            schema="kaliv-consciousness-core/state-transition-commit-receipt/v1",
            transition_id=transition.transition_id,
            from_self_state_ref=transition.from_self_state_ref,
            committed_self_state_ref="self-state:wrong",
            committed_revision=transition.next_self_state.revision,
            commit_ref="commit:test:bad",
            persisted=True,
            production_activation=False,
        )


class FailingCommitter:
    def __init__(self) -> None:
        self.calls = 0

    def commit(self, transition):
        self.calls += 1
        raise RuntimeError("simulated persistence refusal")


class CognitiveSingleStepTests(unittest.TestCase):
    def world(self) -> RuntimeWorldState:
        return RuntimeWorldState(
            schema="kaliv-consciousness-core/world-state/v1",
            world_id="world-" + "c" * 32,
            revision=9,
            observations=[
                WorldObservation(
                    observation_id="obs-" + "d" * 32,
                    subject_ref="project:modelrig",
                    proposition="C18 is being evaluated as one bounded runtime step.",
                    confidence=1.0,
                    epistemic_status="observed",
                    source_refs=["github:branch:c18"],
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
                    kind="goal",
                    salience=0.85,
                    summary="Advance exactly one bounded cognitive runtime step.",
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

    def profile(
        self,
        *,
        marker: str = "f",
        model: str = "single-step-strong",
        depth: float = 0.9,
    ) -> CognitiveProfile:
        return CognitiveProfile(
            schema="kaliv-consciousness-core/cognitive-profile/v1",
            profile_id="cog-" + marker * 32,
            engine_instance_id=f"engine:test:c18:{marker}",
            provider="mock",
            model=model,
            reasoning_depth=depth,
            planning_capacity=depth,
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
            revision=20,
            person_id="person-" + "b" * 32,
            person_revision=personality.person_revision,
            personality_state_ref=personality.personality_state_ref,
            world_state_ref=world_state_ref(world),
            workspace_ref=workspace_ref(workspace),
            active_goal_refs=["goal:consciousness-core"],
            active_intention_refs=[],
            affect=SelfAffect(
                labels=["focused"],
                valence=0.15,
                arousal=0.35,
                confidence=0.9,
                source_refs=["event:user-turn"],
            ),
            known_uncertainties=[],
            last_experience_ref=None,
            production_activation=False,
        )

    def proposal(
        self,
        *,
        uncertainty: float = 0.05,
        interpretation: str = "one bounded cognitive step is sufficient",
    ) -> dict[str, Any]:
        payload = copy.deepcopy(FIXTURES["thought_proposal"])
        payload["proposal_id"] = "thinkprop-" + "4" * 32
        payload["uncertainty"] = uncertainty
        payload["interpretation"] = interpretation
        payload["attention_suggestions"] = ["wc-" + "1" * 32]
        payload["hypotheses"] = [
            {
                "summary": "The runtime boundary remains bounded.",
                "confidence": 0.8,
            }
        ]
        payload["candidate_intentions"] = []
        payload["predicted_outcomes"] = []
        payload["memory_queries"] = []
        payload["response_intent"] = None
        payload["body_intent"] = None
        return payload

    def initial_context(self):
        world = self.world()
        workspace = self.workspace()
        personality = self.personality()
        state = self.state(world, workspace, personality)
        return world, workspace, personality, state

    def next_cycle_directive(self):
        world, workspace, personality, state = self.initial_context()
        initial_cycle = run(
            CognitiveCycleCoordinator(
                ConsciousnessCoreRuntime(StaticEngine(self.proposal()))
            ).run(
                state=state,
                world=world,
                workspace=workspace,
                personality_snapshot=personality,
                profile=self.profile(),
            )
        )
        meta = initial_metacognitive_state(self_ref=self_state_ref(state)).model_copy(
            update={"verification_required": True}
        )
        executive = adjudicate_cycle(
            initial_cycle,
            workspace=workspace,
            metacognition=meta,
        )
        self.assertEqual(executive.receipt.decision, "VERIFY")
        directive = plan_supervisor_step(
            executive,
            cycle=initial_cycle,
            current_state=state,
            workspace=workspace,
            progress=initial_supervisor_progress(
                cycle_id=initial_cycle.request.cycle_id
            ),
        )
        self.assertEqual(directive.action, "NEXT_CYCLE")
        self.assertIsNotNone(directive.transition)
        return directive, world, personality, state

    def test_commit_happens_before_exactly_one_model_call(self):
        directive, world, personality, _ = self.next_cycle_directive()
        assert directive.transition is not None
        committer = RecordingCommitter()
        engine = OrderAwareEngine(committer, self.proposal())
        next_meta = initial_metacognitive_state(
            self_ref=self_state_ref(directive.transition.next_self_state)
        )

        result = run(
            run_single_cognitive_step(
                directive,
                committer=committer,
                runtime=ConsciousnessCoreRuntime(engine),
                world=world,
                personality_snapshot=personality,
                profile=self.profile(),
                metacognition=next_meta,
            )
        )

        self.assertEqual(committer.calls, 1)
        self.assertTrue(committer.committed)
        self.assertEqual(engine.calls, 1)
        self.assertEqual(result.receipt.model_invocations, 1)
        self.assertEqual(result.receipt.adjudications, 1)
        self.assertEqual(result.receipt.supervisor_plans, 1)
        self.assertTrue(result.receipt.state_committed_before_cognition)
        self.assertFalse(result.receipt.recursive_loop)
        self.assertEqual(result.executive.receipt.decision, "ACCEPT_COGNITION")
        self.assertEqual(result.next_directive.action, "COMPLETE")

    def test_bad_commit_receipt_fails_before_model_call(self):
        directive, world, personality, _ = self.next_cycle_directive()
        assert directive.transition is not None
        committer = BadReceiptCommitter()
        engine = StaticEngine(self.proposal())
        with self.assertRaises(CognitiveSingleStepError):
            run(
                run_single_cognitive_step(
                    directive,
                    committer=committer,
                    runtime=ConsciousnessCoreRuntime(engine),
                    world=world,
                    personality_snapshot=personality,
                    profile=self.profile(),
                    metacognition=initial_metacognitive_state(
                        self_ref=self_state_ref(
                            directive.transition.next_self_state
                        )
                    ),
                )
            )
        self.assertEqual(committer.calls, 1)
        self.assertEqual(engine.calls, 0)

    def test_failed_commit_fails_before_model_call(self):
        directive, world, personality, _ = self.next_cycle_directive()
        assert directive.transition is not None
        committer = FailingCommitter()
        engine = StaticEngine(self.proposal())
        with self.assertRaises(CognitiveSingleStepError):
            run(
                run_single_cognitive_step(
                    directive,
                    committer=committer,
                    runtime=ConsciousnessCoreRuntime(engine),
                    world=world,
                    personality_snapshot=personality,
                    profile=self.profile(),
                    metacognition=initial_metacognitive_state(
                        self_ref=self_state_ref(
                            directive.transition.next_self_state
                        )
                    ),
                )
            )
        self.assertEqual(committer.calls, 1)
        self.assertEqual(engine.calls, 0)

    def test_non_next_cycle_directive_is_rejected_before_commit(self):
        directive, world, personality, state = self.next_cycle_directive()
        assert directive.transition is not None

        # Run one ordinary bounded step to obtain a COMPLETE directive.
        first_committer = RecordingCommitter()
        first_engine = OrderAwareEngine(first_committer, self.proposal())
        first = run(
            run_single_cognitive_step(
                directive,
                committer=first_committer,
                runtime=ConsciousnessCoreRuntime(first_engine),
                world=world,
                personality_snapshot=personality,
                profile=self.profile(),
                metacognition=initial_metacognitive_state(
                    self_ref=self_state_ref(directive.transition.next_self_state)
                ),
            )
        )
        self.assertEqual(first.next_directive.action, "COMPLETE")

        second_committer = RecordingCommitter()
        second_engine = StaticEngine(self.proposal())
        with self.assertRaises(CognitiveSingleStepError):
            run(
                run_single_cognitive_step(
                    first.next_directive,
                    committer=second_committer,
                    runtime=ConsciousnessCoreRuntime(second_engine),
                    world=world,
                    personality_snapshot=personality,
                    profile=self.profile(),
                    metacognition=initial_metacognitive_state(
                        self_ref=self_state_ref(state)
                    ),
                )
            )
        self.assertEqual(second_committer.calls, 0)
        self.assertEqual(second_engine.calls, 0)

    def test_interrupt_after_cycle_returns_control_without_second_model_call(self):
        directive, world, personality, _ = self.next_cycle_directive()
        assert directive.transition is not None
        committer = RecordingCommitter()
        engine = OrderAwareEngine(committer, self.proposal())
        result = run(
            run_single_cognitive_step(
                directive,
                committer=committer,
                runtime=ConsciousnessCoreRuntime(engine),
                world=world,
                personality_snapshot=personality,
                profile=self.profile(),
                metacognition=initial_metacognitive_state(
                    self_ref=self_state_ref(directive.transition.next_self_state)
                ),
                interrupt_requested_after_cycle=True,
            )
        )
        self.assertEqual(engine.calls, 1)
        self.assertEqual(result.next_directive.action, "INTERRUPTED")
        self.assertTrue(result.next_directive.interrupt_observed)
        self.assertEqual(result.receipt.model_invocations, 1)

    def test_result_is_bound_to_exact_committed_state_and_transition(self):
        directive, world, personality, _ = self.next_cycle_directive()
        assert directive.transition is not None
        committer = RecordingCommitter()
        engine = OrderAwareEngine(committer, self.proposal())
        result = run(
            run_single_cognitive_step(
                directive,
                committer=committer,
                runtime=ConsciousnessCoreRuntime(engine),
                world=world,
                personality_snapshot=personality,
                profile=self.profile(),
                metacognition=initial_metacognitive_state(
                    self_ref=self_state_ref(directive.transition.next_self_state)
                ),
            )
        )
        expected = self_state_ref(directive.transition.next_self_state)
        self.assertEqual(result.commit.committed_self_state_ref, expected)
        self.assertEqual(result.cycle.receipt.self_state_ref, expected)
        self.assertEqual(
            result.receipt.transition_id,
            directive.transition.transition_id,
        )
        self.assertEqual(
            result.receipt.committed_self_state_ref,
            expected,
        )
        self.assertEqual(
            result.cycle.receipt.self_id,
            directive.transition.next_self_state.self_id,
        )
        self.assertEqual(
            result.cycle.receipt.person_revision,
            directive.transition.next_self_state.person_revision,
        )

    def test_model_swap_changes_cognition_not_self_or_person_binding(self):
        directive, world, personality, _ = self.next_cycle_directive()
        assert directive.transition is not None
        expected_self = directive.transition.next_self_state.self_id
        expected_person = directive.transition.next_self_state.person_id
        expected_revision = directive.transition.next_self_state.person_revision

        outputs = []
        for marker, interpretation, profile in (
            (
                "5",
                "shallower bounded cognition",
                self.profile(marker="5", model="weak-c18", depth=0.35),
            ),
            (
                "6",
                "deeper bounded cognition",
                self.profile(marker="6", model="strong-c18", depth=0.95),
            ),
        ):
            committer = RecordingCommitter()
            engine = OrderAwareEngine(
                committer,
                self.proposal(),
                marker=marker,
                interpretation=interpretation,
            )
            result = run(
                run_single_cognitive_step(
                    directive,
                    committer=committer,
                    runtime=ConsciousnessCoreRuntime(engine),
                    world=world,
                    personality_snapshot=personality,
                    profile=profile,
                    metacognition=initial_metacognitive_state(
                        self_ref=self_state_ref(
                            directive.transition.next_self_state
                        )
                    ),
                )
            )
            outputs.append(result)

        self.assertNotEqual(
            outputs[0].cycle.proposal.interpretation,
            outputs[1].cycle.proposal.interpretation,
        )
        self.assertNotEqual(
            outputs[0].cycle.proposal.proposal_id,
            outputs[1].cycle.proposal.proposal_id,
        )
        for result in outputs:
            self.assertEqual(result.cycle.receipt.self_id, expected_self)
            self.assertEqual(result.cycle.receipt.person_id, expected_person)
            self.assertEqual(
                result.cycle.receipt.person_revision,
                expected_revision,
            )

    def test_tampered_transition_binding_fails_before_commit(self):
        directive, world, personality, _ = self.next_cycle_directive()
        assert directive.transition is not None
        tampered_transition = directive.transition.model_copy(
            update={"decision_ref": "adjudication:wrong"}
        )
        tampered = directive.model_copy(update={"transition": tampered_transition})
        committer = RecordingCommitter()
        engine = StaticEngine(self.proposal())
        with self.assertRaises(CognitiveSingleStepError):
            run(
                run_single_cognitive_step(
                    tampered,
                    committer=committer,
                    runtime=ConsciousnessCoreRuntime(engine),
                    world=world,
                    personality_snapshot=personality,
                    profile=self.profile(),
                    metacognition=initial_metacognitive_state(
                        self_ref=self_state_ref(
                            directive.transition.next_self_state
                        )
                    ),
                )
            )
        self.assertEqual(committer.calls, 0)
        self.assertEqual(engine.calls, 0)

    def test_c18_has_no_store_scheduler_executor_or_background_loop(self):
        source = (
            ROOT / "worker" / "app" / "consciousness_core" / "single_step.py"
        ).read_text(encoding="utf-8")
        for forbidden in (
            "SelfStateStore",
            "schedule_service",
            "ScheduleStore",
            "Agent3Orchestrator",
            "ToolGate",
            "Memory4ExperienceBridge",
            "asyncio.create_task",
            "threading",
        ):
            self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main(verbosity=2)
