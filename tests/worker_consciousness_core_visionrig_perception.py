#!/usr/bin/env python3
"""C31-A VisionRig perception bridge contracts.

Run:
    PYTHONPATH=worker python3 tests/worker_consciousness_core_visionrig_perception.py
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "worker") not in sys.path:
    sys.path.insert(0, str(ROOT / "worker"))

from app.consciousness_core.cycle import RuntimeWorldState, world_state_ref  # noqa: E402
from app.consciousness_core.self_state import PersistentSelfState, SelfAffect  # noqa: E402
from app.consciousness_core.supervisor import SupervisorState  # noqa: E402
from app.consciousness_core.visionrig_perception import (  # noqa: E402
    VisionRigBridgeError,
    VisionRigPerceptionProjector,
    admit_visionrig_projection,
)


class VisionRigPerceptionBridgeTests(unittest.TestCase):
    def event(self, *, x: float = 0.10, sequence: int = 10):
        return {
            "schema_id": "visionrig/perception-event/v2",
            "event_id": "evt-test-0001",
            "observed_at": "2026-09-25T12:00:00+00:00",
            "source": {
                "source_id": "camera-0",
                "source_type": "camera",
                "device": "0",
            },
            "frame_sequence": sequence,
            "entities": [
                {
                    "entity_id": "det-person",
                    "kind": "person",
                    "label": "person",
                    "confidence": 0.9,
                    "bbox": {"x": x, "y": 0.2, "width": 0.2, "height": 0.5},
                    "track_id": "trk-00000001",
                    "identity_hint": "must-not-be-promoted",
                },
                {
                    "entity_id": "det-cup",
                    "kind": "object",
                    "label": "coffee cup",
                    "confidence": 0.8,
                    "bbox": {"x": 0.7, "y": 0.6, "width": 0.1, "height": 0.2},
                    "track_id": "trk-00000002",
                    "identity_hint": None,
                },
            ],
            "relations": [],
            "landmarks": [],
            "depth": [],
            "scene_label": None,
            "scene_confidence": None,
            "dropped_frames": 0,
            "production_authority": False,
        }

    def world(self):
        return RuntimeWorldState(
            schema="kaliv-consciousness-core/world-state/v1",
            world_id="world-" + "a" * 32,
            revision=1,
            observations=[],
            production_activation=False,
        )

    def state(self, world):
        return PersistentSelfState(
            schema="kaliv-consciousness-core/self-state/v1",
            self_id="self-" + "b" * 32,
            revision=5,
            person_id="person-" + "c" * 32,
            person_revision="person-r0001",
            personality_state_ref="personality-state:test",
            world_state_ref=world_state_ref(world),
            workspace_ref="workspace:test",
            active_goal_refs=[],
            active_intention_refs=[],
            affect=SelfAffect(
                labels=["neutral"],
                valence=0.0,
                arousal=0.0,
                confidence=1.0,
                source_refs=["test:affect"],
            ),
            known_uncertainties=[],
            last_experience_ref=None,
            production_activation=False,
        )

    def supervisor(self):
        return SupervisorState(
            schema="kaliv-consciousness-core/supervisor-state/v1",
            supervisor_id="csup-" + "d" * 32,
            revision=1,
            runtime_epoch_id="epoch-" + "e" * 32,
            pending_events=[],
            epoch_started_monotonic_ms=0,
            epoch_started_clock_sequence=0,
            last_cycle_id=None,
            last_cycle_monotonic_ms=None,
            last_cycle_clock_sequence=None,
            production_activation=False,
        )

    def test_projects_entities_into_existing_core_contracts(self):
        projection = VisionRigPerceptionProjector().project(self.event())
        self.assertEqual(len(projection.world_evidence), 2)
        self.assertEqual(len(projection.cognition_events), 2)
        self.assertTrue(
            all(item.epistemic_status == "inferred" for item in projection.world_evidence)
        )
        self.assertTrue(
            all(item.kind == "world_change" for item in projection.cognition_events)
        )
        serialized = str(projection.model_dump(mode="json"))
        self.assertNotIn("must-not-be-promoted", serialized)
        self.assertFalse(projection.identity_hints_promoted)
        self.assertFalse(projection.production_activation)

    def test_unchanged_tracks_are_deduplicated(self):
        projector = VisionRigPerceptionProjector()
        first = projector.project(self.event())
        second = projector.project(self.event(sequence=11))
        self.assertEqual(len(first.world_evidence), 2)
        self.assertEqual(second.world_evidence, [])
        self.assertEqual(second.cognition_events, [])
        self.assertEqual(second.deduplicated_items, 2)

    def test_meaningful_region_change_reappears(self):
        projector = VisionRigPerceptionProjector()
        projector.project(self.event(x=0.05, sequence=10))
        moved = projector.project(self.event(x=0.75, sequence=11))
        person = [
            item for item in moved.world_evidence
            if "a person is visible" in item.proposition
        ]
        self.assertEqual(len(person), 1)
        self.assertIn("right-", person[0].proposition)

    def test_stale_source_sequence_fails_closed(self):
        projector = VisionRigPerceptionProjector()
        projector.project(self.event(sequence=10))
        with self.assertRaises(VisionRigBridgeError):
            projector.project(self.event(sequence=9))

    def test_projection_admits_through_world_and_supervisor_authorities(self):
        world = self.world()
        state = self.state(world)
        supervisor = self.supervisor()
        projection = VisionRigPerceptionProjector().project(self.event())

        result = admit_visionrig_projection(
            state=state,
            world=world,
            supervisor_state=supervisor,
            projection=projection,
        )

        self.assertEqual(result.world.revision, world.revision + 2)
        self.assertEqual(result.state.revision, state.revision + 2)
        self.assertEqual(len(result.supervisor_state.pending_events), 2)
        self.assertEqual(len(result.world_receipts), 2)
        self.assertTrue(all(r.model_calls == 0 for r in result.world_receipts))
        self.assertEqual(result.model_calls, 0)
        self.assertFalse(result.execution_authority)
        self.assertFalse(result.scheduling_authority)
        self.assertFalse(result.durable_memory_write_authority)
        self.assertFalse(result.production_activation)

    def test_wrong_visionrig_schema_is_rejected(self):
        event = self.event()
        event["schema_id"] = "visionrig/perception-event/v1"
        with self.assertRaises(VisionRigBridgeError):
            VisionRigPerceptionProjector().project(event)


if __name__ == "__main__":
    unittest.main()
