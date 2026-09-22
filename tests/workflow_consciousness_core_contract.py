#!/usr/bin/env python3
"""Deterministic C0-C3 contract checks for Consciousness Core.

This slice is deliberately documentation/contracts/tests only. The test uses only
the Python standard library so it cannot create a runtime dependency merely by
existing.
"""
from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONTRACTS = ROOT / "contracts" / "consciousness-core"
DOCS = ROOT / "docs" / "consciousness-core"


def load_json(name: str) -> dict:
    value = json.loads((CONTRACTS / name).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise AssertionError(f"{name} must contain one JSON object")
    return value


class ConsciousnessCoreContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.schemas = {
            name: load_json(name)
            for name in (
                "self-state-v1.schema.json",
                "world-state-v1.schema.json",
                "workspace-v1.schema.json",
                "cognitive-profile-v1.schema.json",
                "thought-request-v1.schema.json",
                "thought-proposal-v1.schema.json",
            )
        }
        self.fixtures = load_json("fixtures-v1.json")

    def test_all_contracts_are_draft_2020_12_and_non_activating(self) -> None:
        for name, schema in self.schemas.items():
            self.assertEqual(
                schema.get("$schema"),
                "https://json-schema.org/draft/2020-12/schema",
                name,
            )
            self.assertEqual(
                schema["properties"]["production_activation"].get("const"),
                False,
                name,
            )

    def test_self_state_is_model_independent(self) -> None:
        props = self.schemas["self-state-v1.schema.json"]["properties"]
        forbidden = ("model", "provider", "llm", "thought_engine", "engine_instance")
        lowered = {key.lower() for key in props}
        for token in forbidden:
            self.assertFalse(
                any(token in key for key in lowered),
                f"SelfState must not persist ThoughtEngine identity: {token}",
            )
        self.assertIn("person_id", props)
        self.assertIn("person_revision", props)
        self.assertIn("personality_state_ref", props)

    def test_cognitive_profile_is_explicitly_ephemeral_and_non_authoritative(self) -> None:
        props = self.schemas["cognitive-profile-v1.schema.json"]["properties"]
        self.assertTrue(props["ephemeral"]["const"])
        for key in ("identity_authority", "persistent_state_authority", "action_authority"):
            self.assertIs(props[key]["const"], False)

    def test_thought_proposal_cannot_mutate_or_act(self) -> None:
        props = self.schemas["thought-proposal-v1.schema.json"]["properties"]
        self.assertEqual(props["state_mutations"]["maxItems"], 0)
        self.assertEqual(props["actions"]["maxItems"], 0)
        authority = props["authority"]["properties"]
        self.assertEqual(
            {key: value["const"] for key, value in authority.items()},
            {"identity": False, "persistent_state": False, "durable_memory": False, "action": False},
        )

    def test_workspace_is_bounded_and_information_only(self) -> None:
        props = self.schemas["workspace-v1.schema.json"]["properties"]
        self.assertLessEqual(props["candidates"]["maxItems"], 256)
        self.assertLessEqual(props["selected_candidate_ids"]["maxItems"], 16)
        self.assertLessEqual(props["max_active"]["maximum"], 16)
        self.assertNotIn("actions", props)
        self.assertNotIn("tools", props)
        self.assertNotIn("schedule", props)

    def test_personality_snapshot_has_multiple_source_capacity(self) -> None:
        props = self.schemas["thought-request-v1.schema.json"]["properties"]
        personality = props["personality_snapshot"]["properties"]
        self.assertIn("source_refs", personality)
        self.assertGreaterEqual(personality["source_refs"]["maxItems"], 3)
        source_refs = self.fixtures["thought_request"]["personality_snapshot"]["source_refs"]
        self.assertTrue(any(ref.startswith("person-profile:") for ref in source_refs))
        self.assertTrue(any(ref.startswith("bodyrig:") for ref in source_refs))
        self.assertTrue(any(ref.startswith("voicerig:") for ref in source_refs))

    def test_model_swap_changes_profile_not_identity_fixture(self) -> None:
        before = dict(self.fixtures["self_state"])
        after = dict(before)
        profile_a = dict(self.fixtures["cognitive_profile"])
        profile_b = dict(profile_a)
        profile_b["engine_instance_id"] = "engine:test:2"
        profile_b["provider"] = "another-provider"
        profile_b["model"] = "stronger-model"
        profile_b["reasoning_depth"] = 0.9
        profile_b["planning_capacity"] = 0.9

        self.assertNotEqual(profile_a, profile_b)
        self.assertEqual(before, after)
        for key in ("self_id", "person_id", "person_revision", "personality_state_ref"):
            self.assertEqual(before[key], after[key])

    def test_valid_fixtures_keep_authority_false(self) -> None:
        for key in (
            "self_state",
            "world_state",
            "workspace",
            "cognitive_profile",
            "thought_request",
            "thought_proposal",
        ):
            self.assertIs(self.fixtures[key]["production_activation"], False)
        proposal = self.fixtures["thought_proposal"]
        self.assertEqual(proposal["actions"], [])
        self.assertEqual(proposal["state_mutations"], [])
        self.assertTrue(all(value is False for value in proposal["authority"].values()))

    def test_docs_freeze_name_and_core_invariants(self) -> None:
        architecture = (DOCS / "ARCHITECTURE.md").read_text(encoding="utf-8")
        roadmap = (DOCS / "ROADMAP.md").read_text(encoding="utf-8")
        combined = architecture + "\n" + roadmap
        self.assertIn("Consciousness Core", combined)
        self.assertIn("Identity and personality persist. Cognition is replaceable.", combined)
        self.assertIn("Kaliv is not the model. Kaliv uses the model.", combined)
        self.assertIn("BodyRig is one source, not the whole", architecture)
        self.assertIn("Personality Resolver", combined)
        self.assertIn("ThoughtEngine", combined)
        self.assertIn("KALIV_CONSCIOUSNESS_CORE_ENABLED=0", architecture)

    def test_current_slice_contains_no_runtime_python_package(self) -> None:
        forbidden_roots = (
            ROOT / "worker" / "app" / "consciousness_core",
            ROOT / "backend" / "consciousness_core",
            ROOT / "consciousness_core",
        )
        for path in forbidden_roots:
            self.assertFalse(path.exists(), f"C0-C3 must remain runtime-isolated: {path}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
