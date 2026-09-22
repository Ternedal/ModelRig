#!/usr/bin/env python3
"""C22-B strict production CognitiveProfile resolution tests.

Run:
    PYTHONPATH=worker python3 tests/worker_consciousness_core_production_profile.py
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "worker") not in sys.path:
    sys.path.insert(0, str(ROOT / "worker"))

from app.consciousness_core.production_profile import (  # noqa: E402
    CONSCIOUSNESS_PROFILE_PATH_ENV,
    MAX_PROFILE_CONFIG_BYTES,
    ProductionCognitiveProfileError,
    resolve_production_cognitive_profile,
)


class ProductionProfileTests(unittest.TestCase):
    def payload(self):
        return {
            "schema": (
                "kaliv-consciousness-core/"
                "production-cognitive-profile-config/v1"
            ),
            "provider": "ollama",
            "model": "qwen2.5-coder:7b",
            "reasoning_depth": 0.55,
            "planning_capacity": 0.45,
            "context_capacity_tokens": 8192,
            "multimodal_capacity": 0.0,
            "tool_reasoning": 0.0,
            "uncertainty_calibration": 0.5,
            "source_ref": "operator-profile:local-cognition-v1",
            "capacity_basis": "operator_declared",
            "production_activation": False,
        }

    def write(self, root: Path, payload=None, *, raw: str | None = None) -> Path:
        path = root / "profile.json"
        if raw is not None:
            path.write_text(raw, encoding="utf-8")
        else:
            path.write_text(
                json.dumps(payload if payload is not None else self.payload()),
                encoding="utf-8",
            )
        return path

    def test_missing_config_is_unavailable_not_guessed(self):
        with tempfile.TemporaryDirectory() as td:
            missing = Path(td) / "missing.json"
            before = "app.ollama_client" in sys.modules
            result = resolve_production_cognitive_profile(path=missing)
            self.assertIsNone(result)
            self.assertEqual(
                "app.ollama_client" in sys.modules,
                before,
            )

    def test_valid_operator_declared_profile_is_deterministic(self):
        with tempfile.TemporaryDirectory() as td:
            path = self.write(Path(td))
            first = resolve_production_cognitive_profile(path=path)
            second = resolve_production_cognitive_profile(path=path)

            self.assertIsNotNone(first)
            self.assertEqual(
                first.model_dump(mode="json"),
                second.model_dump(mode="json"),
            )
            profile = first.profile
            receipt = first.receipt
            self.assertEqual(profile.provider, "ollama")
            self.assertEqual(profile.model, "qwen2.5-coder:7b")
            self.assertEqual(profile.reasoning_depth, 0.55)
            self.assertEqual(profile.planning_capacity, 0.45)
            self.assertEqual(profile.context_capacity_tokens, 8192)
            self.assertTrue(profile.ephemeral)
            self.assertFalse(profile.identity_authority)
            self.assertFalse(profile.persistent_state_authority)
            self.assertFalse(profile.action_authority)
            self.assertEqual(receipt.capacity_basis, "operator_declared")
            self.assertFalse(receipt.measured_capability_claim)
            self.assertEqual(receipt.model_calls, 0)
            self.assertFalse(receipt.production_activation)

    def test_resolver_does_not_import_ollama_provider(self):
        with tempfile.TemporaryDirectory() as td:
            path = self.write(Path(td))
            sys.modules.pop("app.ollama_client", None)
            self.assertNotIn("app.ollama_client", sys.modules)
            result = resolve_production_cognitive_profile(path=path)
            self.assertIsNotNone(result)
            self.assertNotIn("app.ollama_client", sys.modules)

    def test_env_path_resolves_exact_file(self):
        with tempfile.TemporaryDirectory() as td:
            path = self.write(Path(td))
            result = resolve_production_cognitive_profile(
                env={CONSCIOUSNESS_PROFILE_PATH_ENV: str(path)}
            )
            self.assertIsNotNone(result)
            self.assertEqual(
                result.receipt.source_ref,
                "operator-profile:local-cognition-v1",
            )

    def test_changed_config_changes_canonical_profile_identity(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            first_path = root / "first.json"
            second_path = root / "second.json"
            first = self.payload()
            second = self.payload()
            second["model"] = "gemma3:12b"
            first_path.write_text(json.dumps(first), encoding="utf-8")
            second_path.write_text(json.dumps(second), encoding="utf-8")

            a = resolve_production_cognitive_profile(path=first_path)
            b = resolve_production_cognitive_profile(path=second_path)
            self.assertNotEqual(a.profile.profile_id, b.profile.profile_id)
            self.assertNotEqual(
                a.profile.engine_instance_id,
                b.profile.engine_instance_id,
            )
            self.assertNotEqual(
                a.receipt.config_ref,
                b.receipt.config_ref,
            )

    def test_extra_field_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            payload = self.payload()
            payload["invented"] = "not allowed"
            path = self.write(Path(td), payload)
            with self.assertRaises(ProductionCognitiveProfileError):
                resolve_production_cognitive_profile(path=path)

    def test_duplicate_json_key_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            payload = self.payload()
            raw = json.dumps(payload)
            raw = raw[:-1] + ', "model": "other"}'
            path = self.write(Path(td), raw=raw)
            with self.assertRaises(ProductionCognitiveProfileError):
                resolve_production_cognitive_profile(path=path)

    def test_non_finite_json_number_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            payload = self.payload()
            raw = json.dumps(payload).replace(
                '"reasoning_depth": 0.55',
                '"reasoning_depth": NaN',
            )
            path = self.write(Path(td), raw=raw)
            with self.assertRaises(ProductionCognitiveProfileError):
                resolve_production_cognitive_profile(path=path)

    def test_out_of_range_capacity_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            payload = self.payload()
            payload["planning_capacity"] = 1.1
            path = self.write(Path(td), payload)
            with self.assertRaises(ProductionCognitiveProfileError):
                resolve_production_cognitive_profile(path=path)

    def test_boolean_is_not_accepted_as_numeric_capacity(self):
        with tempfile.TemporaryDirectory() as td:
            payload = self.payload()
            payload["reasoning_depth"] = True
            path = self.write(Path(td), payload)
            with self.assertRaises(ProductionCognitiveProfileError):
                resolve_production_cognitive_profile(path=path)

    def test_oversize_config_fails_before_json_contract(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "profile.json"
            path.write_bytes(b"{" + b"x" * MAX_PROFILE_CONFIG_BYTES + b"}")
            with self.assertRaises(ProductionCognitiveProfileError):
                resolve_production_cognitive_profile(path=path)

    def test_empty_config_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "profile.json"
            path.write_bytes(b"")
            with self.assertRaises(ProductionCognitiveProfileError):
                resolve_production_cognitive_profile(path=path)

    def test_config_cannot_claim_measured_basis(self):
        with tempfile.TemporaryDirectory() as td:
            payload = self.payload()
            payload["capacity_basis"] = "measured"
            path = self.write(Path(td), payload)
            with self.assertRaises(ProductionCognitiveProfileError):
                resolve_production_cognitive_profile(path=path)

    def test_profile_config_never_grants_identity_or_action_authority(self):
        with tempfile.TemporaryDirectory() as td:
            result = resolve_production_cognitive_profile(
                path=self.write(Path(td))
            )
            self.assertFalse(result.profile.identity_authority)
            self.assertFalse(result.profile.persistent_state_authority)
            self.assertFalse(result.profile.action_authority)
            self.assertFalse(result.receipt.identity_authority)
            self.assertFalse(result.receipt.persistent_state_authority)
            self.assertFalse(result.receipt.action_authority)


if __name__ == "__main__":
    unittest.main()
