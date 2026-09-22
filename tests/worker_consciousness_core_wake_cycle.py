#!/usr/bin/env python3
"""C17 wake reorientation and first cognitive-cycle tests.

Run:
    PYTHONPATH=worker python3 tests/worker_consciousness_core_wake_cycle.py
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
    CognitiveProfile,
    ConsciousnessCoreRuntime,
    PersistentSelfState,
    PersonalitySnapshot,
    RuntimeWorldState,
    SelfAffect,
    TemporalAnchor,
    WorkspaceCandidate,
    WorldObservation,
    build_workspace,
    prepare_sleep,
    wake_from_sleep,
    workspace_ref,
    world_state_ref,
)
from app.consciousness_core.wake_cycle import (  # noqa: E402
    WakeCycleError,
    WakeFirstCycleCoordinator,
    build_wake_orientation,
    wake_receipt_ref,
)


FIXTURES = json.loads(
    (ROOT / "contracts" / "consciousness-core" / "fixtures-v1.json").read_text(
        encoding="utf-8"
    )
)


def run(coro):
    return asyncio.run(coro)


class WakeEngine:
    def __init__(self) -> None:
        self.calls = 0
        self.context = None

    async def think(self, request, cognitive_profile, *, context=None):
        self.calls += 1
        self.context = copy.deepcopy(context)
        payload = copy.deepcopy(FIXTURES["thought_proposal"])
        payload["request_id"] = request.request_id
        payload["proposal_id"] = "thinkprop-" + "8" * 32
        payload["interpretation"] = (
            "Reorient after the continuity gap before considering further work."
        )
        payload["attention_suggestions"] = []
        payload["uncertainty"] = 0.12
        return payload


class WakeCycleTests(unittest.TestCase):
    def anchor(
        self,
        marker: str,
        *,
        epoch: str,
        wall_ms: int,
        monotonic_ms: int,
        sequence: int,
    ) -> TemporalAnchor:
        return TemporalAnchor(
            schema="kaliv-consciousness-core/temporal-anchor/v1",
            anchor_id="tanch-" + marker * 32,
            event_ref=f"test:{marker}",
            wall_time_unix_ms=wall_ms,
            runtime_epoch_id="epoch-" + epoch * 32,
            monotonic_ms=monotonic_ms,
            sequence=sequence,
            source_refs=[f"clock:test:{marker}"],
            confidence=1.0,
            production_activation=False,
        )

    def planned_wake(self):
        sleep = prepare_sleep(
            self_id="self-" + "a" * 32,
            person_revision="person-r0007",
            entry_anchor=self.anchor(
                "1",
                epoch="1",
                wall_ms=1_000_000,
                monotonic_ms=50_000,
                sequence=10,
            ),
            reason="app_closed",
            open_goal_refs=[
                "goal:consciousness-core",
                "goal:open-before-sleep",
            ],
            open_loop_refs=["loop:unfinished-design"],
            pending_review_refs=["review:pending:17"],
        )
        return wake_from_sleep(
            wake_anchor=self.anchor(
                "2",
                epoch="2",
                wall_ms=1_600_000,
                monotonic_ms=2_000,
                sequence=11,
            ),
            sleep_record=sleep,
            expected_self_id="self-" + "a" * 32,
            expected_person_revision="person-r0007",
        )

    def unplanned_wake(self):
        return wake_from_sleep(
            wake_anchor=self.anchor(
                "4",
                epoch="4",
                wall_ms=2_100_000,
                monotonic_ms=1_000,
                sequence=22,
            ),
            last_known_anchor=self.anchor(
                "3",
                epoch="3",
                wall_ms=2_000_000,
                monotonic_ms=90_000,
                sequence=21,
            ),
            expected_self_id="self-" + "a" * 32,
            expected_person_revision="person-r0007",
        )

    def world(self) -> RuntimeWorldState:
        return RuntimeWorldState(
            schema="kaliv-consciousness-core/world-state/v1",
            world_id="world-" + "c" * 32,
            revision=9,
            observations=[
                WorldObservation(
                    observation_id="obs-" + "d" * 32,
                    subject_ref="project:modelrig",
                    proposition="The process is running after a continuity gap.",
                    confidence=1.0,
                    epistemic_status="observed",
                    source_refs=["runtime:startup"],
                )
            ],
            production_activation=False,
        )

    def workspace(self):
        return build_workspace(
            cycle_id="cycle-" + "e" * 32,
            max_active=8,
            candidates=[
                WorkspaceCandidate(
                    candidate_id="wc-" + "1" * 32,
                    kind="memory",
                    salience=0.72,
                    summary="Identity persists across runtime epochs.",
                    source_ref="memory4:continuity-invariant",
                ),
                WorkspaceCandidate(
                    candidate_id="wc-" + "2" * 32,
                    kind="goal",
                    salience=0.68,
                    summary="Continue Consciousness Core development.",
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
            ],
        )

    def profile(self) -> CognitiveProfile:
        return CognitiveProfile(
            schema="kaliv-consciousness-core/cognitive-profile/v1",
            profile_id="cog-" + "f" * 32,
            engine_instance_id="engine:test:wake",
            provider="mock",
            model="replaceable-wake-cognition",
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
            revision=20,
            person_id="person-" + "b" * 32,
            person_revision=personality.person_revision,
            personality_state_ref=personality.personality_state_ref,
            world_state_ref=world_state_ref(world),
            workspace_ref=workspace_ref(workspace),
            active_goal_refs=["goal:consciousness-core"],
            active_intention_refs=["intent:continue-core"],
            affect=SelfAffect(
                labels=["neutral"],
                valence=0.0,
                arousal=0.2,
                confidence=0.9,
                source_refs=["self-state:pre-wake"],
            ),
            known_uncertainties=[],
            last_experience_ref="memory4:experience:before-sleep",
            production_activation=False,
        )

    def context(self):
        world = self.world()
        workspace = self.workspace()
        personality = self.personality()
        state = self.state(world, workspace, personality)
        return state, world, workspace, personality

    def test_planned_wake_becomes_bounded_context_not_execution(self) -> None:
        state, _, workspace, _ = self.context()
        wake = self.planned_wake()
        oriented = build_wake_orientation(
            wake_receipt=wake,
            current_state=state,
            current_workspace=workspace,
        )

        self.assertEqual(oriented.oriented_self_state.revision, state.revision + 1)
        self.assertEqual(oriented.oriented_self_state.self_id, state.self_id)
        self.assertEqual(
            oriented.oriented_self_state.active_goal_refs,
            state.active_goal_refs,
        )
        self.assertNotIn(
            "goal:open-before-sleep",
            oriented.oriented_self_state.active_goal_refs,
        )
        self.assertEqual(
            oriented.receipt.resume_goal_refs_exposed,
            ["goal:consciousness-core", "goal:open-before-sleep"],
        )
        self.assertEqual(
            oriented.receipt.resume_open_loop_refs_exposed,
            ["loop:unfinished-design"],
        )
        self.assertEqual(
            oriented.receipt.pending_review_refs_exposed,
            ["review:pending:17"],
        )
        self.assertFalse(oriented.receipt.automatic_goal_resume)
        self.assertFalse(oriented.receipt.automatic_loop_resume)
        self.assertFalse(oriented.receipt.execution_authority)
        self.assertFalse(oriented.receipt.scheduling_authority)

        wake_item = next(
            item
            for item in oriented.oriented_workspace.candidates
            if item.candidate_id == oriented.receipt.wake_candidate_id
        )
        self.assertEqual(wake_item.source_ref, wake_receipt_ref(wake))
        self.assertIn("cognition during the gap was false", wake_item.summary)

    def test_first_wake_cycle_calls_thought_engine_exactly_once(self) -> None:
        state, world, workspace, personality = self.context()
        engine = WakeEngine()
        result = run(
            WakeFirstCycleCoordinator(
                ConsciousnessCoreRuntime(engine)
            ).run(
                wake_receipt=self.planned_wake(),
                current_state=state,
                current_world=world,
                current_workspace=workspace,
                personality_snapshot=personality,
                profile=self.profile(),
                relevant_memory_refs=["memory4:continuity-invariant"],
            )
        )

        self.assertEqual(engine.calls, 1)
        self.assertEqual(result.receipt.thought_engine_calls, 1)
        self.assertEqual(
            result.orientation.oriented_self_state.revision,
            state.revision + 1,
        )
        self.assertEqual(
            result.reduction.next_self_state.revision,
            state.revision + 2,
        )
        self.assertEqual(
            result.reduction.next_self_state.self_id,
            state.self_id,
        )
        self.assertEqual(
            result.reduction.next_self_state.person_revision,
            state.person_revision,
        )
        self.assertEqual(
            result.cognitive_cycle.request.requested_reasoning_mode,
            "verify",
        )
        self.assertFalse(result.receipt.cognition_during_gap)
        self.assertFalse(result.receipt.self_state_store_write_applied)
        self.assertFalse(result.receipt.durable_memory_write_authority)
        self.assertFalse(result.receipt.execution_authority)
        self.assertFalse(result.receipt.scheduling_authority)
        self.assertFalse(result.receipt.raw_chain_of_thought_persisted)

    def test_identity_mismatch_fails_before_model_call(self) -> None:
        state, world, workspace, personality = self.context()
        engine = WakeEngine()
        wake = self.planned_wake().model_copy(
            update={"self_id": "self-" + "9" * 32}
        )
        with self.assertRaises(WakeCycleError):
            run(
                WakeFirstCycleCoordinator(
                    ConsciousnessCoreRuntime(engine)
                ).run(
                    wake_receipt=wake,
                    current_state=state,
                    current_world=world,
                    current_workspace=workspace,
                    personality_snapshot=personality,
                    profile=self.profile(),
                )
            )
        self.assertEqual(engine.calls, 0)

    def test_person_revision_mismatch_fails_before_model_call(self) -> None:
        state, world, workspace, personality = self.context()
        engine = WakeEngine()
        wake = self.planned_wake().model_copy(
            update={"person_revision": "person-r9999"}
        )
        with self.assertRaises(WakeCycleError):
            run(
                WakeFirstCycleCoordinator(
                    ConsciousnessCoreRuntime(engine)
                ).run(
                    wake_receipt=wake,
                    current_state=state,
                    current_world=world,
                    current_workspace=workspace,
                    personality_snapshot=personality,
                    profile=self.profile(),
                )
            )
        self.assertEqual(engine.calls, 0)

    def test_unplanned_dormancy_reorients_without_inventing_resume_refs(self) -> None:
        state, _, workspace, _ = self.context()
        wake = self.unplanned_wake()
        oriented = build_wake_orientation(
            wake_receipt=wake,
            current_state=state,
            current_workspace=workspace,
        )
        self.assertEqual(wake.dormancy_kind, "UNPLANNED_DORMANCY")
        self.assertEqual(oriented.receipt.resume_goal_refs_exposed, [])
        self.assertEqual(oriented.receipt.resume_open_loop_refs_exposed, [])
        self.assertEqual(oriented.receipt.pending_review_refs_exposed, [])
        self.assertEqual(
            oriented.oriented_self_state.active_goal_refs,
            state.active_goal_refs,
        )

    def test_orientation_is_deterministic_for_same_wake_and_state(self) -> None:
        state, _, workspace, _ = self.context()
        wake = self.planned_wake()
        first = build_wake_orientation(
            wake_receipt=wake,
            current_state=state,
            current_workspace=workspace,
        )
        second = build_wake_orientation(
            wake_receipt=wake,
            current_state=state,
            current_workspace=workspace,
        )
        self.assertEqual(
            first.model_dump(mode="json"),
            second.model_dump(mode="json"),
        )


if __name__ == "__main__":
    unittest.main()
