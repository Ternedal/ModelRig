#!/usr/bin/env python3
"""Deterministic C0-C3 contract checks for Consciousness Core.

This slice is deliberately documentation/contracts/tests only. The test uses only
the Python standard library so it cannot create a runtime dependency merely by
existing.
"""
from __future__ import annotations

import copy
import importlib.util
import json
import math
import re
import unittest
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[1]
CONTRACTS = ROOT / "contracts" / "consciousness-core"
DOCS = ROOT / "docs" / "consciousness-core"
EXPERIMENTS = ROOT / "experiments" / "consciousness_core"


class ContractError(ValueError):
    pass


def load_json(name: str) -> dict:
    value = json.loads(
        (CONTRACTS / name).read_text(encoding="utf-8"),
        parse_constant=lambda token: (_ for _ in ()).throw(
            ContractError(f"non-finite JSON constant in {name}: {token}")
        ),
    )
    if not isinstance(value, dict):
        raise ContractError(f"{name} must contain one JSON object")
    return value


def _json_equal(left: Any, right: Any) -> bool:
    """JSON equality without Python's True == 1 aliasing."""
    if type(left) in {int, float} and type(right) in {int, float}:
        return math.isfinite(float(left)) and math.isfinite(float(right)) and float(left) == float(right)
    if type(left) is not type(right):
        return False
    if isinstance(left, dict):
        return left.keys() == right.keys() and all(_json_equal(left[k], right[k]) for k in left)
    if isinstance(left, list):
        return len(left) == len(right) and all(_json_equal(a, b) for a, b in zip(left, right))
    return left == right


def validate(schema: Mapping[str, Any], value: Any, *, path: str = "$") -> None:
    """Validate the Draft-2020-12 subset used by the C0-C3 contracts."""
    if "const" in schema and not _json_equal(value, schema["const"]):
        raise ContractError(f"{path}: const mismatch")

    if "enum" in schema:
        candidates = schema["enum"]
        if not isinstance(candidates, list) or not any(_json_equal(value, item) for item in candidates):
            raise ContractError(f"{path}: enum mismatch")

    schema_type = schema.get("type")
    if schema_type == "object" and not isinstance(value, dict):
        raise ContractError(f"{path}: expected object")
    if schema_type == "array" and not isinstance(value, list):
        raise ContractError(f"{path}: expected array")
    if schema_type == "string" and not isinstance(value, str):
        raise ContractError(f"{path}: expected string")
    if schema_type == "integer" and type(value) is not int:
        raise ContractError(f"{path}: expected integer")
    if schema_type == "number" and not (type(value) in {int, float} and math.isfinite(float(value))):
        raise ContractError(f"{path}: expected finite number")
    if schema_type == "boolean" and type(value) is not bool:
        raise ContractError(f"{path}: expected boolean")
    if schema_type == "null" and value is not None:
        raise ContractError(f"{path}: expected null")

    any_of = schema.get("anyOf")
    if isinstance(any_of, list):
        matches = 0
        for candidate in any_of:
            try:
                validate(candidate, value, path=path)
            except ContractError:
                continue
            matches += 1
        if matches < 1:
            raise ContractError(f"{path}: anyOf did not match")

    if isinstance(value, dict):
        required = schema.get("required", [])
        if not isinstance(required, list):
            raise ContractError(f"{path}: malformed required")
        for name in required:
            if name not in value:
                raise ContractError(f"{path}: missing required property {name}")

        properties = schema.get("properties", {})
        if not isinstance(properties, Mapping):
            raise ContractError(f"{path}: malformed properties")
        for name, child in value.items():
            if name in properties:
                child_schema = properties[name]
                if not isinstance(child_schema, Mapping):
                    raise ContractError(f"{path}.{name}: malformed property schema")
                validate(child_schema, child, path=f"{path}.{name}")
            elif schema.get("additionalProperties") is False:
                raise ContractError(f"{path}: unexpected property {name}")

    if isinstance(value, list):
        minimum = schema.get("minItems")
        maximum = schema.get("maxItems")
        if isinstance(minimum, int) and len(value) < minimum:
            raise ContractError(f"{path}: too few items")
        if isinstance(maximum, int) and len(value) > maximum:
            raise ContractError(f"{path}: too many items")
        if schema.get("uniqueItems") is True:
            for index, item in enumerate(value):
                if any(_json_equal(item, previous) for previous in value[:index]):
                    raise ContractError(f"{path}: duplicate item")
        item_schema = schema.get("items")
        if isinstance(item_schema, Mapping):
            for index, child in enumerate(value):
                validate(item_schema, child, path=f"{path}[{index}]")

    if isinstance(value, str):
        minimum = schema.get("minLength")
        maximum = schema.get("maxLength")
        if isinstance(minimum, int) and len(value) < minimum:
            raise ContractError(f"{path}: string too short")
        if isinstance(maximum, int) and len(value) > maximum:
            raise ContractError(f"{path}: string too long")
        pattern = schema.get("pattern")
        if isinstance(pattern, str) and re.search(pattern, value) is None:
            raise ContractError(f"{path}: pattern mismatch")

    if type(value) in {int, float}:
        numeric = float(value)
        minimum = schema.get("minimum")
        maximum = schema.get("maximum")
        if type(minimum) in {int, float} and numeric < float(minimum):
            raise ContractError(f"{path}: below minimum")
        if type(maximum) in {int, float} and numeric > float(maximum):
            raise ContractError(f"{path}: above maximum")


class ConsciousnessCoreContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.schema_by_fixture = {
            "self_state": "self-state-v1.schema.json",
            "world_state": "world-state-v1.schema.json",
            "workspace": "workspace-v1.schema.json",
            "cognitive_profile": "cognitive-profile-v1.schema.json",
            "thought_request": "thought-request-v1.schema.json",
            "thought_proposal": "thought-proposal-v1.schema.json",
        }
        self.schemas = {
            name: load_json(name)
            for name in self.schema_by_fixture.values()
        }
        self.fixtures = load_json("fixtures-v1.json")
        self.model_swap_schema = load_json("model-swap-evaluation-v1.schema.json")

    def assertRejected(self, schema_name: str, value: Any) -> None:
        with self.assertRaises(ContractError):
            validate(self.schemas[schema_name], value)

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

    def test_every_reference_fixture_validates_against_its_schema(self) -> None:
        for fixture_name, schema_name in self.schema_by_fixture.items():
            validate(self.schemas[schema_name], self.fixtures[fixture_name])

    def test_reference_fixtures_fail_closed_on_unknown_fields(self) -> None:
        for fixture_name, schema_name in self.schema_by_fixture.items():
            mutated = copy.deepcopy(self.fixtures[fixture_name])
            mutated["future_unreviewed_field"] = True
            self.assertRejected(schema_name, mutated)

    def test_self_state_is_model_independent(self) -> None:
        schema_name = "self-state-v1.schema.json"
        props = self.schemas[schema_name]["properties"]
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

        mutated = copy.deepcopy(self.fixtures["self_state"])
        mutated["model"] = "some-model"
        self.assertRejected(schema_name, mutated)

    def test_cognitive_profile_is_explicitly_ephemeral_and_non_authoritative(self) -> None:
        schema_name = "cognitive-profile-v1.schema.json"
        props = self.schemas[schema_name]["properties"]
        self.assertTrue(props["ephemeral"]["const"])
        for key in ("identity_authority", "persistent_state_authority", "action_authority"):
            self.assertIs(props[key]["const"], False)
            mutated = copy.deepcopy(self.fixtures["cognitive_profile"])
            mutated[key] = True
            self.assertRejected(schema_name, mutated)

    def test_thought_proposal_cannot_mutate_or_act(self) -> None:
        schema_name = "thought-proposal-v1.schema.json"
        props = self.schemas[schema_name]["properties"]
        self.assertEqual(props["state_mutations"]["maxItems"], 0)
        self.assertEqual(props["actions"]["maxItems"], 0)
        authority = props["authority"]["properties"]
        self.assertEqual(
            {key: value["const"] for key, value in authority.items()},
            {"identity": False, "persistent_state": False, "durable_memory": False, "action": False},
        )

        action = copy.deepcopy(self.fixtures["thought_proposal"])
        action["actions"] = [{"tool": "forbidden"}]
        self.assertRejected(schema_name, action)

        mutation = copy.deepcopy(self.fixtures["thought_proposal"])
        mutation["state_mutations"] = [{"path": "person_id", "value": "replacement"}]
        self.assertRejected(schema_name, mutation)

        for key in ("identity", "persistent_state", "durable_memory", "action"):
            escalated = copy.deepcopy(self.fixtures["thought_proposal"])
            escalated["authority"][key] = True
            self.assertRejected(schema_name, escalated)

    def test_workspace_is_bounded_and_information_only(self) -> None:
        schema_name = "workspace-v1.schema.json"
        props = self.schemas[schema_name]["properties"]
        self.assertLessEqual(props["candidates"]["maxItems"], 256)
        self.assertLessEqual(props["selected_candidate_ids"]["maxItems"], 16)
        self.assertLessEqual(props["max_active"]["maximum"], 16)
        self.assertNotIn("actions", props)
        self.assertNotIn("tools", props)
        self.assertNotIn("schedule", props)

        over_selected = copy.deepcopy(self.fixtures["workspace"])
        over_selected["selected_candidate_ids"] = [
            f"wc-{index:032x}" for index in range(17)
        ]
        self.assertRejected(schema_name, over_selected)

    def test_world_state_requires_provenance_and_epistemic_status(self) -> None:
        schema_name = "world-state-v1.schema.json"
        no_source = copy.deepcopy(self.fixtures["world_state"])
        no_source["observations"][0]["source_refs"] = []
        self.assertRejected(schema_name, no_source)

        invented_status = copy.deepcopy(self.fixtures["world_state"])
        invented_status["observations"][0]["epistemic_status"] = "known"
        self.assertRejected(schema_name, invented_status)

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
        before = copy.deepcopy(self.fixtures["self_state"])
        after = copy.deepcopy(before)
        profile_a = copy.deepcopy(self.fixtures["cognitive_profile"])
        profile_b = copy.deepcopy(profile_a)
        profile_b["engine_instance_id"] = "engine:test:2"
        profile_b["provider"] = "another-provider"
        profile_b["model"] = "stronger-model"
        profile_b["reasoning_depth"] = 0.9
        profile_b["planning_capacity"] = 0.9

        validate(self.schemas["cognitive-profile-v1.schema.json"], profile_a)
        validate(self.schemas["cognitive-profile-v1.schema.json"], profile_b)
        self.assertNotEqual(profile_a, profile_b)
        self.assertEqual(before, after)
        for key in ("self_id", "person_id", "person_revision", "personality_state_ref"):
            self.assertEqual(before[key], after[key])

    def test_mock_thought_engine_proves_external_replaceable_cognition(self) -> None:
        module_path = EXPERIMENTS / "mock_thought_engine.py"
        spec = importlib.util.spec_from_file_location("cc_mock_thought_engine", module_path)
        self.assertIsNotNone(spec)
        self.assertIsNotNone(spec.loader)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        engine = module.MockThoughtEngine()
        request = copy.deepcopy(self.fixtures["thought_request"])
        workspace = copy.deepcopy(self.fixtures["workspace"])
        self_state_before = copy.deepcopy(self.fixtures["self_state"])

        weaker = copy.deepcopy(self.fixtures["cognitive_profile"])
        weaker["engine_instance_id"] = "engine:weak:1"
        weaker["model"] = "mock-weak"
        weaker["reasoning_depth"] = 0.2
        weaker["planning_capacity"] = 0.2

        stronger = copy.deepcopy(self.fixtures["cognitive_profile"])
        stronger["engine_instance_id"] = "engine:strong:1"
        stronger["model"] = "mock-strong"
        stronger["reasoning_depth"] = 0.95
        stronger["planning_capacity"] = 0.95

        weak_proposal = engine.think(request, weaker, workspace)
        strong_proposal = engine.think(request, stronger, workspace)

        validate(self.schemas["thought-proposal-v1.schema.json"], weak_proposal)
        validate(self.schemas["thought-proposal-v1.schema.json"], strong_proposal)
        self.assertNotEqual(weak_proposal["proposal_id"], strong_proposal["proposal_id"])
        self.assertNotEqual(weak_proposal["interpretation"], strong_proposal["interpretation"])
        self.assertGreater(weak_proposal["uncertainty"], strong_proposal["uncertainty"])
        self.assertEqual(self.fixtures["self_state"], self_state_before)

        for proposal in (weak_proposal, strong_proposal):
            self.assertEqual(proposal["actions"], [])
            self.assertEqual(proposal["state_mutations"], [])
            self.assertTrue(all(value is False for value in proposal["authority"].values()))

    def test_model_swap_eval_emits_identity_preserving_receipt(self) -> None:
        module_path = EXPERIMENTS / "model_swap_eval.py"
        spec = importlib.util.spec_from_file_location("cc_model_swap_eval", module_path)
        self.assertIsNotNone(spec)
        self.assertIsNotNone(spec.loader)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        receipt = module.run(self.fixtures)
        validate(self.model_swap_schema, receipt)
        self.assertTrue(receipt["identity_unchanged"])
        self.assertTrue(receipt["cognition_changed"])
        self.assertTrue(receipt["authority_preserved"])
        self.assertEqual(receipt["self_before_sha256"], receipt["self_after_sha256"])
        self.assertGreater(receipt["weak_uncertainty"], receipt["strong_uncertainty"])
        self.assertFalse(receipt["production_activation"])

    def test_valid_fixtures_keep_authority_false(self) -> None:
        for key in self.schema_by_fixture:
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
