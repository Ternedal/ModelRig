"""Contract checks for C31-G model-swap continuity qualification."""
import copy
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "worker"))

from app.consciousness_core.model_swap_continuity import (
    ModelSwapContinuityError,
    qualify_model_swap_continuity,
)

FIXTURES = json.loads(
    (ROOT / "contracts" / "consciousness-core" / "fixtures-v1.json").read_text(
        encoding="utf-8"
    )
)


def profiles():
    weak = copy.deepcopy(FIXTURES["cognitive_profile"])
    weak.update(
        {
            "engine_instance_id": "engine:c31g:weak",
            "provider": "mock-a",
            "model": "mock-weak",
            "reasoning_depth": 0.2,
            "planning_capacity": 0.2,
        }
    )
    strong = copy.deepcopy(FIXTURES["cognitive_profile"])
    strong.update(
        {
            "engine_instance_id": "engine:c31g:strong",
            "provider": "mock-b",
            "model": "mock-strong",
            "reasoning_depth": 0.95,
            "planning_capacity": 0.95,
        }
    )
    return weak, strong


def qualify(**overrides):
    weak, strong = profiles()
    args = {
        "self_before": copy.deepcopy(FIXTURES["self_state"]),
        "self_after": copy.deepcopy(FIXTURES["self_state"]),
        "profile_before": weak,
        "profile_after": strong,
        "durable_memory_authority_ref_before": "memory4:authority:1",
        "durable_memory_authority_ref_after": "memory4:authority:1",
        "continuity_refs_before": ["continuity:state:1", "episode:review:7"],
        "continuity_refs_after": ["continuity:state:1", "episode:review:7"],
    }
    args.update(overrides)
    return qualify_model_swap_continuity(**args)


class ModelSwapContinuityTests(unittest.TestCase):
    def test_model_swap_changes_capability_without_changing_identity_authorities(self):
        out = qualify()
        self.assertTrue(out.cognitive_capability_changed)
        self.assertTrue(out.self_identity_stable)
        self.assertTrue(out.person_binding_stable)
        self.assertTrue(out.durable_memory_authority_stable)
        self.assertTrue(out.continuity_refs_stable)
        self.assertNotEqual(out.engine_before_ref, out.engine_after_ref)
        self.assertEqual(out.model_calls, 0)
        self.assertEqual(out.persistent_writes, 0)
        self.assertFalse(out.thought_engine_identity_authority)
        self.assertFalse(out.thought_engine_durable_memory_authority)
        self.assertFalse(out.thought_engine_execution_authority)
        self.assertFalse(out.thought_engine_scheduling_authority)
        self.assertFalse(out.production_activation)

    def test_identity_drift_fails_closed(self):
        cases = [
            ("self_id", "self-" + "9" * 32, "self identity"),
            ("person_id", "person-" + "9" * 32, "Person binding"),
            ("person_revision", "person-r9999", "Person Revision"),
        ]
        for field, new_value, error in cases:
            with self.subTest(field=field):
                changed = copy.deepcopy(FIXTURES["self_state"])
                changed[field] = new_value
                with self.assertRaisesRegex(ModelSwapContinuityError, error):
                    qualify(self_after=changed)

    def test_memory_authority_drift_fails_closed(self):
        with self.assertRaisesRegex(
            ModelSwapContinuityError, "durable-memory authority"
        ):
            qualify(durable_memory_authority_ref_after="memory4:authority:2")

    def test_continuity_ref_drift_fails_closed(self):
        with self.assertRaisesRegex(ModelSwapContinuityError, "continuity references"):
            qualify(
                continuity_refs_after=["continuity:state:2", "episode:review:7"]
            )

    def test_same_engine_is_not_a_model_swap(self):
        weak, _ = profiles()
        with self.assertRaisesRegex(
            ModelSwapContinuityError, "real ThoughtEngine replacement"
        ):
            qualify(profile_before=weak, profile_after=copy.deepcopy(weak))

    def test_engine_change_without_capability_change_does_not_qualify(self):
        weak, same_capability = profiles()
        same_capability["reasoning_depth"] = weak["reasoning_depth"]
        same_capability["planning_capacity"] = weak["planning_capacity"]
        same_capability["context_capacity_tokens"] = weak["context_capacity_tokens"]
        same_capability["multimodal_capacity"] = weak["multimodal_capacity"]
        same_capability["tool_reasoning"] = weak["tool_reasoning"]
        same_capability["uncertainty_calibration"] = weak["uncertainty_calibration"]
        with self.assertRaisesRegex(
            ModelSwapContinuityError, "cognitive capability change"
        ):
            qualify(profile_before=weak, profile_after=same_capability)


if __name__ == "__main__":
    unittest.main(verbosity=2)
