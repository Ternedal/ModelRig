#!/usr/bin/env python3
"""C31-A VisionRig semantic projection contracts."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "worker") not in sys.path:
    sys.path.insert(0, str(ROOT / "worker"))

from app.consciousness_core.visionrig_perception import (  # noqa: E402
    VisionRigBridgeError,
    VisionRigPerceptionProjector,
)


class VisionRigPerceptionBridgeTests(unittest.TestCase):
    def event(self, *, x: float = 0.10, sequence: int = 10):
        return {
            "schema_id": "visionrig/perception-event/v2",
            "event_id": f"evt-test-{sequence:04d}",
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

    def test_projects_entities_into_evidence_plans(self):
        projection = VisionRigPerceptionProjector().project(self.event())
        self.assertEqual(len(projection.evidence_plans), 2)
        self.assertTrue(
            all(
                item.evidence.epistemic_status == "inferred"
                for item in projection.evidence_plans
            )
        )
        serialized = str(projection.model_dump(mode="json"))
        self.assertNotIn("must-not-be-promoted", serialized)
        self.assertFalse(projection.identity_hints_promoted)
        self.assertEqual(projection.model_calls, 0)
        self.assertFalse(projection.production_activation)

    def test_unchanged_tracks_are_deduplicated(self):
        projector = VisionRigPerceptionProjector()
        first = projector.project(self.event(sequence=10))
        second = projector.project(self.event(sequence=11))
        self.assertEqual(len(first.evidence_plans), 2)
        self.assertEqual(second.evidence_plans, [])
        self.assertEqual(second.deduplicated_items, 2)

    def test_meaningful_region_change_reappears(self):
        projector = VisionRigPerceptionProjector()
        projector.project(self.event(x=0.05, sequence=10))
        moved = projector.project(self.event(x=0.75, sequence=11))
        person = [
            item.evidence
            for item in moved.evidence_plans
            if "a person is visible" in item.evidence.proposition
        ]
        self.assertEqual(len(person), 1)
        self.assertIn("right-", person[0].proposition)

    def test_stale_source_sequence_fails_closed(self):
        projector = VisionRigPerceptionProjector()
        projector.project(self.event(sequence=10))
        with self.assertRaises(VisionRigBridgeError):
            projector.project(self.event(sequence=9))

    def test_checkpoint_restore_replays_same_projection(self):
        projector = VisionRigPerceptionProjector()
        checkpoint = projector.checkpoint()
        first = projector.project(self.event(sequence=10))
        projector.restore(checkpoint)
        replay = projector.project(self.event(sequence=10))
        self.assertEqual(
            [p.evidence for p in first.evidence_plans],
            [p.evidence for p in replay.evidence_plans],
        )

    def test_wrong_visionrig_schema_is_rejected(self):
        event = self.event()
        event["schema_id"] = "visionrig/perception-event/v1"
        with self.assertRaises(VisionRigBridgeError):
            VisionRigPerceptionProjector().project(event)


if __name__ == "__main__":
    unittest.main()
