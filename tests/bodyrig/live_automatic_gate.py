#!/usr/bin/env python3
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
FINAL_GATE_PATH = ROOT / "scripts" / "bodyrig_unity_live_automatic_final_gate.py"
SPEC = importlib.util.spec_from_file_location("bodyrig_auto_final_gate", FINAL_GATE_PATH)
assert SPEC and SPEC.loader
GATE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(GATE)

SHA = "a" * 40
BODY = "bodyid-" + "b" * 24
PACKAGE = "c" * 64
RIG = "http://127.0.0.1:8080"


def write_json(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class AutomaticSealTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.evidence = Path(self.temp.name)
        now = datetime.now(timezone.utc).isoformat()
        self.run_path = self.evidence / "live-run-receipt.json"
        self.quality_path = self.evidence / "live-quality-receipt.json"
        self.exercise_path = self.evidence / "live-automatic-exercise-receipt.json"
        write_json(self.run_path, {"candidate_git_sha": SHA})
        write_json(self.quality_path, {"candidate_git_sha": SHA, "created_at": now})
        self.exercise = {
            "schema": "bodyrig.live_automatic_exercise/v0.1",
            "created_at": now,
            "production_activation": False,
            "candidate_git_sha": SHA,
            "body_id": BODY,
            "package_sha256": PACKAGE,
            "rig_url": RIG,
            "token_source": "environment",
            "states_driven": ["idle", "listening", "speaking", "interrupted", "idle"],
            "voice_chunk_observed": True,
            "playback_reanchored": True,
            "interrupt_sent": True,
            "idle_restored": True,
            "bindings": {
                "live_run_sha256": sha(self.run_path),
                "live_quality_sha256": sha(self.quality_path),
            },
        }
        write_json(self.exercise_path, self.exercise)
        self.base = {
            "candidate_git_sha": SHA,
            "body_id": BODY,
            "package_sha256": PACKAGE,
            "rig_url": RIG,
        }

    def tearDown(self) -> None:
        self.temp.cleanup()

    def validate(self) -> dict:
        with patch.object(GATE, "validate_automatic_evidence", return_value=self.base):
            return GATE.validate_final_evidence(
                evidence_dir=self.evidence,
                expected_sha=SHA,
                repo_root=ROOT,
                require_git_state=False,
            )

    def rewrite_exercise(self) -> None:
        self.exercise["bindings"] = {
            "live_run_sha256": sha(self.run_path),
            "live_quality_sha256": sha(self.quality_path),
        }
        write_json(self.exercise_path, self.exercise)

    def test_complete_machine_seal_passes(self) -> None:
        result = self.validate()
        self.assertEqual(result["schema"], "bodyrig.unity_live_automatic_final/v0.1")
        self.assertTrue(result["machine_live_proof"])
        self.assertTrue(result["machine_quality"])
        self.assertTrue(result["product_exercise"])
        self.assertFalse(result["production_activation"])

    def test_quality_tamper_after_exercise_is_rejected(self) -> None:
        quality = json.loads(self.quality_path.read_text(encoding="utf-8"))
        quality["tampered"] = True
        write_json(self.quality_path, quality)
        with self.assertRaisesRegex(GATE.LivePhysicalGateError, "no longer binds Unity quality"):
            self.validate()

    def test_missing_product_action_is_rejected(self) -> None:
        self.exercise["playback_reanchored"] = False
        self.rewrite_exercise()
        with self.assertRaisesRegex(GATE.LivePhysicalGateError, "playback_reanchored"):
            self.validate()

    def test_state_sequence_cannot_be_weakened(self) -> None:
        self.exercise["states_driven"] = ["idle", "speaking", "idle"]
        self.rewrite_exercise()
        with self.assertRaisesRegex(GATE.LivePhysicalGateError, "state sequence"):
            self.validate()

    def test_exercise_cannot_self_activate_production(self) -> None:
        self.exercise["production_activation"] = True
        self.rewrite_exercise()
        with self.assertRaisesRegex(GATE.LivePhysicalGateError, "activated production"):
            self.validate()


class SourceBoundaryTests(unittest.TestCase):
    def test_quality_observes_only_post_apply_frames(self) -> None:
        source = (ROOT / "renderers/bodyrig-unity/Assets/BodyRig/Runtime/BodyRigFrameSource.cs").read_text(encoding="utf-8")
        self.assertIn("public static event Action<BodyRigRenderFrame> FrameApplied;", source)
        self.assertLess(source.index("renderer.Apply(frame);"), source.index("FrameApplied?.Invoke(frame);"))

    def test_quality_receipt_is_machine_only_and_create_only(self) -> None:
        source = (ROOT / "renderers/bodyrig-unity/Assets/BodyRig/Runtime/BodyRigLiveQualityProbe.cs").read_text(encoding="utf-8")
        for marker in (
            '"bodyrig.unity_live_quality/v0.1"',
            '"BODYRIG_LIVE_QUALITY_RECEIPT"',
            "machine_quality_pass",
            "FileMode.CreateNew",
            "production_activation = false",
        ):
            self.assertIn(marker, source)

    def test_exercise_uses_existing_product_routes_and_env_token(self) -> None:
        source = (ROOT / "scripts/bodyrig_live_automatic_exercise.py").read_text(encoding="utf-8")
        for marker in (
            "/api/v1/body/state/listening",
            "/api/v1/voice/converse/stream",
            "/api/v1/body/speech/{quoted}/started",
            "/api/v1/body/interrupt",
            "os.environ.get(token_env",
        ):
            self.assertIn(marker, source)
        self.assertNotIn("--token\"", source)


if __name__ == "__main__":
    unittest.main(verbosity=2)
