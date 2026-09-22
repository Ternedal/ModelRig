#!/usr/bin/env python3
"""C20-A provenance-bound epistemic WorldState reducer tests.

Run:
    PYTHONPATH=worker python3 tests/worker_consciousness_core_world_reducer.py
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "worker") not in sys.path:
    sys.path.insert(0, str(ROOT / "worker"))

from app.consciousness_core import (  # noqa: E402
    PersistentSelfState,
    RuntimeWorldState,
    SelfAffect,
    WorldObservation,
    world_state_ref,
)
from app.consciousness_core.world_reducer import (  # noqa: E402
    WorldEvidenceEvent,
    WorldReducerError,
    reduce_world_evidence,
)


class WorldReducerTests(unittest.TestCase):
    def world(self, *, count: int = 1) -> RuntimeWorldState:
        observations = []
        for i in range(count):
            marker = f"{i:032x}"[-32:]
            observations.append(
                WorldObservation(
                    observation_id="obs-" + marker,
                    subject_ref=f"subject:{i}",
                    proposition=f"Existing observation {i}.",
                    confidence=1.0,
                    epistemic_status="observed",
                    source_refs=[f"source:{i}"],
                )
            )
        return RuntimeWorldState(
            schema="kaliv-consciousness-core/world-state/v1",
            world_id="world-" + "c" * 32,
            revision=7,
            observations=observations,
            production_activation=False,
        )

    def state(self, world: RuntimeWorldState) -> PersistentSelfState:
        return PersistentSelfState(
            schema="kaliv-consciousness-core/self-state/v1",
            self_id="self-" + "a" * 32,
            revision=60,
            person_id="person-" + "b" * 32,
            person_revision="person-r0007",
            personality_state_ref="personality-state:test",
            world_state_ref=world_state_ref(world),
            workspace_ref="workspace:test",
            active_goal_refs=["goal:test"],
            active_intention_refs=["intent:test"],
            affect=SelfAffect(
                labels=["focused"],
                valence=0.2,
                arousal=0.3,
                confidence=0.9,
                source_refs=["affect:test"],
            ),
            known_uncertainties=[],
            last_experience_ref="memory4:experience:last",
            production_activation=False,
        )

    def evidence(
        self,
        marker: str = "1",
        *,
        proposition: str = "The build completed successfully.",
        status: str = "observed",
        confidence: float = 1.0,
    ) -> WorldEvidenceEvent:
        return WorldEvidenceEvent(
            schema="kaliv-consciousness-core/world-evidence-event/v1",
            event_id="wevt-" + marker * 32,
            subject_ref="project:modelrig",
            proposition=proposition,
            confidence=confidence,
            epistemic_status=status,
            source_refs=["github:workflow:exact-head"],
            observed_sequence=100,
            production_activation=False,
        )

    def test_new_evidence_advances_world_and_only_world_binding(self):
        world = self.world()
        state = self.state(world)
        result = reduce_world_evidence(
            state=state,
            world=world,
            evidence=self.evidence(),
        )

        self.assertEqual(result.world.revision, world.revision + 1)
        self.assertEqual(result.state.revision, state.revision + 1)
        self.assertNotEqual(result.state.world_state_ref, state.world_state_ref)
        self.assertEqual(result.state.workspace_ref, state.workspace_ref)
        self.assertEqual(result.state.self_id, state.self_id)
        self.assertEqual(result.state.person_id, state.person_id)
        self.assertEqual(result.state.person_revision, state.person_revision)
        self.assertEqual(
            result.state.personality_state_ref,
            state.personality_state_ref,
        )
        self.assertEqual(result.state.active_goal_refs, state.active_goal_refs)
        self.assertEqual(
            result.state.active_intention_refs,
            state.active_intention_refs,
        )
        self.assertEqual(result.state.affect, state.affect)
        self.assertEqual(
            result.state.last_experience_ref,
            state.last_experience_ref,
        )
        self.assertTrue(result.receipt.world_changed)
        self.assertFalse(result.receipt.idempotent_replay)
        self.assertEqual(result.receipt.model_calls, 0)
        self.assertFalse(result.receipt.execution_authority)
        self.assertFalse(result.receipt.scheduling_authority)
        self.assertFalse(result.receipt.self_state_store_write_applied)

    def test_epistemic_status_is_preserved_not_inferred(self):
        for status in ("observed", "reported", "inferred", "predicted"):
            with self.subTest(status=status):
                world = self.world()
                state = self.state(world)
                result = reduce_world_evidence(
                    state=state,
                    world=world,
                    evidence=self.evidence(
                        marker={
                            "observed": "1",
                            "reported": "2",
                            "inferred": "3",
                            "predicted": "4",
                        }[status],
                        status=status,
                        confidence=0.6,
                    ),
                )
                self.assertEqual(
                    result.world.observations[-1].epistemic_status,
                    status,
                )
                self.assertEqual(
                    result.world.observations[-1].confidence,
                    0.6,
                )

    def test_identical_event_replay_is_idempotent(self):
        world = self.world()
        state = self.state(world)
        first = reduce_world_evidence(
            state=state,
            world=world,
            evidence=self.evidence(),
        )
        replay = reduce_world_evidence(
            state=first.state,
            world=first.world,
            evidence=self.evidence(),
        )
        self.assertEqual(replay.world, first.world)
        self.assertEqual(replay.state, first.state)
        self.assertTrue(replay.receipt.idempotent_replay)
        self.assertFalse(replay.receipt.world_changed)
        self.assertEqual(
            replay.receipt.world_revision_before,
            replay.receipt.world_revision_after,
        )
        self.assertEqual(
            replay.receipt.self_revision_before,
            replay.receipt.self_revision_after,
        )

    def test_conflicting_reuse_of_event_id_fails_closed(self):
        world = self.world()
        state = self.state(world)
        first = reduce_world_evidence(
            state=state,
            world=world,
            evidence=self.evidence(),
        )
        conflict = self.evidence(
            proposition="Conflicting proposition under the same event id."
        )
        with self.assertRaises(WorldReducerError):
            reduce_world_evidence(
                state=first.state,
                world=first.world,
                evidence=conflict,
            )

    def test_stale_self_world_binding_fails_closed(self):
        world = self.world()
        state = self.state(world).model_copy(
            update={"world_state_ref": "world-state:stale"}
        )
        with self.assertRaises(WorldReducerError):
            reduce_world_evidence(
                state=state,
                world=world,
                evidence=self.evidence(),
            )

    def test_retention_is_bounded_and_evicts_oldest_observation(self):
        world = self.world(count=512)
        state = self.state(world)
        oldest = world.observations[0].observation_id
        result = reduce_world_evidence(
            state=state,
            world=world,
            evidence=self.evidence(marker="f"),
        )
        self.assertEqual(len(result.world.observations), 512)
        self.assertNotIn(
            oldest,
            [item.observation_id for item in result.world.observations],
        )
        self.assertEqual(
            result.receipt.evicted_observation_ids,
            [oldest],
        )
        self.assertEqual(
            result.world.observations[-1].subject_ref,
            "project:modelrig",
        )

    def test_duplicate_source_refs_fail_strict_validation(self):
        with self.assertRaises(Exception):
            WorldEvidenceEvent(
                schema="kaliv-consciousness-core/world-evidence-event/v1",
                event_id="wevt-" + "9" * 32,
                subject_ref="project:modelrig",
                proposition="Duplicate provenance is invalid.",
                confidence=1.0,
                epistemic_status="observed",
                source_refs=["source:a", "source:a"],
                observed_sequence=1,
                production_activation=False,
            )

    def test_model_authored_claim_is_not_promoted_by_reducer(self):
        world = self.world()
        state = self.state(world)
        event = WorldEvidenceEvent(
            schema="kaliv-consciousness-core/world-evidence-event/v1",
            event_id="wevt-" + "8" * 32,
            subject_ref="project:modelrig",
            proposition="A model predicted a future test result.",
            confidence=0.4,
            epistemic_status="predicted",
            source_refs=["thought-proposal:bounded-ref"],
            observed_sequence=101,
            production_activation=False,
        )
        result = reduce_world_evidence(
            state=state,
            world=world,
            evidence=event,
        )
        observation = result.world.observations[-1]
        self.assertEqual(observation.epistemic_status, "predicted")
        self.assertEqual(observation.confidence, 0.4)
        self.assertEqual(
            observation.source_refs,
            ["thought-proposal:bounded-ref"],
        )


if __name__ == "__main__":
    unittest.main()
