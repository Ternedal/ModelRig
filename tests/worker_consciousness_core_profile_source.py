#!/usr/bin/env python3
"""C22-A operator-calibrated CognitiveProfile source tests.

Run:
    PYTHONPATH=worker python3 tests/worker_consciousness_core_profile_source.py
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

from app.consciousness_core.profile_source import (  # noqa: E402
    CONSCIOUSNESS_PROFILE_FILE_ENV,
    CognitiveProfileSourceError,
    build_cognitive_profile,
    cognitive_profile_config_path,
    load_cognitive_profile,
)


class CognitiveProfileSourceTests(unittest.TestCase):
    def payload(self, *, model: str = "qwen3:14b", reasoning: float = 0.7):
        return {
            "schema": "kaliv-consciousness-core/cognitive-profile-config/v1",
            "provider": "ollama",
            "model": model,
            "reasoning_depth": reasoning,
            "planning_capacity": 0.65,
            "context_capacity_tokens": 32768,
            "multimodal_capacity": 0.0,
            "tool_reasoning": 0.5,
            "uncertainty_calibration": 0.8,
            "calibration_refs": [
                "benchmark:consciousness:local-v1",
                "operator:profile-review",
            ],
        }

    def write(self, path: Path, payload: dict, *, indent=None) -> None:
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=indent),
            encoding="utf-8",
        )

    def test_missing_profile_is_unavailable_not_fabricated(self):
        with tempfile.TemporaryDirectory() as td:
            result = load_cognitive_profile(
                path=Path(td) / "missing.json",
            )
            self.assertIsNone(result)

    def test_default_path_is_stable_data_root_and_override_is_exact(self):
        default = cognitive_profile_config_path(env={})
        self.assertEqual(default.name, "kaliv-consciousness-profile.json")

        explicit = cognitive_profile_config_path(
            env={CONSCIOUSNESS_PROFILE_FILE_ENV: "relative/custom-profile.json"}
        )
        self.assertEqual(explicit, Path("relative/custom-profile.json"))

    def test_load_builds_authority_free_ephemeral_profile(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "profile.json"
            self.write(path, self.payload())
            loaded = load_cognitive_profile(path=path)
            self.assertIsNotNone(loaded)
            profile = loaded.profile
            self.assertEqual(profile.provider, "ollama")
            self.assertEqual(profile.model, "qwen3:14b")
            self.assertTrue(profile.ephemeral)
            self.assertFalse(profile.identity_authority)
            self.assertFalse(profile.persistent_state_authority)
            self.assertFalse(profile.action_authority)
            self.assertFalse(profile.production_activation)
            self.assertEqual(
                loaded.receipt.profile_id,
                profile.profile_id,
            )
            self.assertEqual(
                loaded.receipt.engine_instance_id,
                "thought-engine:ollama:v1",
            )
            self.assertEqual(loaded.receipt.model_calls, 0)
            self.assertFalse(loaded.receipt.execution_authority)
            self.assertFalse(loaded.receipt.scheduling_authority)
            self.assertFalse(loaded.receipt.self_state_store_write_applied)

    def test_profile_id_is_canonical_across_json_formatting_and_key_order(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            a = root / "a.json"
            b = root / "b.json"
            payload = self.payload()
            self.write(a, payload, indent=2)
            reversed_payload = dict(reversed(list(payload.items())))
            b.write_text(
                json.dumps(reversed_payload, ensure_ascii=False, separators=(",", ":")),
                encoding="utf-8",
            )
            first = load_cognitive_profile(path=a)
            second = load_cognitive_profile(path=b)
            self.assertEqual(first.profile, second.profile)
            self.assertEqual(
                first.receipt.config_sha256,
                second.receipt.config_sha256,
            )
            self.assertNotEqual(
                first.receipt.config_bytes,
                second.receipt.config_bytes,
            )

    def test_model_or_capability_change_changes_profile_identity(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "profile.json"
            self.write(path, self.payload())
            first = load_cognitive_profile(path=path)

            self.write(
                path,
                self.payload(model="qwen3:30b", reasoning=0.9),
            )
            second = load_cognitive_profile(path=path)

            self.assertNotEqual(first.profile.profile_id, second.profile.profile_id)
            self.assertNotEqual(first.receipt.profile_ref, second.receipt.profile_ref)
            self.assertEqual(second.profile.model, "qwen3:30b")
            self.assertEqual(second.profile.reasoning_depth, 0.9)

    def test_engine_instance_change_changes_profile_identity(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "profile.json"
            self.write(path, self.payload())
            first = load_cognitive_profile(
                path=path,
                engine_instance_id="thought-engine:ollama:v1",
            )
            second = load_cognitive_profile(
                path=path,
                engine_instance_id="thought-engine:test-other:v1",
            )
            self.assertNotEqual(first.profile.profile_id, second.profile.profile_id)
            self.assertNotEqual(first.receipt.profile_ref, second.receipt.profile_ref)

    def test_hot_reload_reads_file_fresh_each_time(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "profile.json"
            self.write(path, self.payload(model="model-a"))
            first = load_cognitive_profile(path=path)
            self.write(path, self.payload(model="model-b", reasoning=0.4))
            second = load_cognitive_profile(path=path)
            self.assertEqual(first.profile.model, "model-a")
            self.assertEqual(second.profile.model, "model-b")
            self.assertNotEqual(first.profile.profile_id, second.profile.profile_id)

    def test_unknown_authority_fields_are_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "profile.json"
            payload = self.payload()
            payload["action_authority"] = True
            self.write(path, payload)
            with self.assertRaises(CognitiveProfileSourceError):
                load_cognitive_profile(path=path)

    def test_duplicate_json_keys_are_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "profile.json"
            path.write_text(
                """{
                  "schema":"kaliv-consciousness-core/cognitive-profile-config/v1",
                  "provider":"ollama",
                  "model":"model-a",
                  "model":"model-b",
                  "reasoning_depth":0.7,
                  "planning_capacity":0.6,
                  "context_capacity_tokens":8192,
                  "multimodal_capacity":0.0,
                  "tool_reasoning":0.5,
                  "uncertainty_calibration":0.8,
                  "calibration_refs":["benchmark:test"]
                }""",
                encoding="utf-8",
            )
            with self.assertRaises(CognitiveProfileSourceError):
                load_cognitive_profile(path=path)

    def test_non_finite_numbers_are_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "profile.json"
            raw = json.dumps(self.payload()).replace(
                '"reasoning_depth": 0.7',
                '"reasoning_depth": NaN',
            )
            path.write_text(raw, encoding="utf-8")
            with self.assertRaises(CognitiveProfileSourceError):
                load_cognitive_profile(path=path)

    def test_duplicate_calibration_refs_are_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "profile.json"
            payload = self.payload()
            payload["calibration_refs"] = ["benchmark:test", "benchmark:test"]
            self.write(path, payload)
            with self.assertRaises(CognitiveProfileSourceError):
                load_cognitive_profile(path=path)

    def test_oversized_profile_file_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "profile.json"
            path.write_bytes(b"{" + b" " * (33 * 1024) + b"}")
            with self.assertRaises(CognitiveProfileSourceError):
                load_cognitive_profile(path=path)

    def test_blank_or_invalid_engine_instance_id_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "profile.json"
            self.write(path, self.payload())
            with self.assertRaises(CognitiveProfileSourceError):
                load_cognitive_profile(
                    path=path,
                    engine_instance_id="",
                )

    def test_builder_requires_validated_config_not_arbitrary_mapping(self):
        with self.assertRaises(TypeError):
            build_cognitive_profile(self.payload())  # type: ignore[arg-type]


if __name__ == "__main__":
    unittest.main()
