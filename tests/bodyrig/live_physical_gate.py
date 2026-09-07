#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts.bodyrig_unity_live_physical_gate import (  # noqa: E402
    LivePhysicalGateError,
    validate_evidence,
)

SHA = "a" * 40
BODY = "bodyid-" + "b" * 24
PACKAGE = "c" * 64
RIG = "http://127.0.0.1:8080"
NOW = "2026-09-07T08:00:00+00:00"
LATER = "2026-09-07T08:05:00+00:00"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True, indent=2) + "\n", encoding="utf-8")


class LivePhysicalGateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.evidence = Path(self.temp.name) / "evidence"
        self.renderer = self.evidence / "renderer"
        self.renderer.mkdir(parents=True)
        self._build_valid_evidence()

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _build_valid_evidence(self) -> None:
        exe = self.renderer / "build" / "BodyRigRendererProof.exe"
        log = self.renderer / "unity-build.log"
        exe.parent.mkdir(parents=True)
        exe.write_bytes(b"unity-player-proof")
        log.write_text("Build Finished, Result: Success\n", encoding="utf-8")

        runtime_path = self.renderer / "runtime-receipt.json"
        runtime = {
            "schema": "bodyrig.unity_runtime_load/v0.1",
            "created_at": NOW,
            "production_activation": False,
            "visual_acceptance": False,
            "vrm_loaded": True,
            "renderer_bound": True,
            "candidate_git_sha": SHA,
            "body_id": BODY,
            "package_sha256": PACKAGE,
            "avatar_sha256": "d" * 64,
            "unity_version": "6000.3.21f1",
            "vrm_path": "C:\\BodyRig\\avatar.vrm",
        }
        write_json(runtime_path, runtime)

        build_path = self.renderer / "build-receipt.json"
        build = {
            "schema": "bodyrig.unity_physical_build/v0.2",
            "created_at": NOW,
            "production_activation": False,
            "visual_acceptance": False,
            "pr_number": 720,
            "candidate": {"git_sha": SHA},
            "profile": {
                "body_id": BODY,
                "package_sha256": PACKAGE,
                "avatar_sha256": "d" * 64,
                "vrm_path": "C:\\BodyRig\\avatar.vrm",
            },
            "build": {
                "success": True,
                "exit_code": 0,
                "launched": True,
                "runtime_load_verified": True,
            },
            "artifacts": {
                "executable": {"path": str(exe), "bytes": exe.stat().st_size, "sha256": sha(exe)},
                "unity_log": {"path": str(log), "bytes": log.stat().st_size, "sha256": sha(log)},
                "runtime_receipt": {
                    "path": str(runtime_path),
                    "bytes": runtime_path.stat().st_size,
                    "sha256": sha(runtime_path),
                },
            },
        }
        write_json(build_path, build)

        preflight_path = self.evidence / "live-preflight-receipt.json"
        preflight = {
            "schema": "bodyrig.live_stream_probe/v0.1",
            "created_at": NOW,
            "production_activation": False,
            "candidate_git_sha": SHA,
            "base_url": RIG,
            "token_source": "environment",
            "active_body_id": BODY,
            "active_package_sha256": PACKAGE,
            "frame_count": 5,
            "first_timestamp_ms": 1000,
            "last_timestamp_ms": 1200,
            "states_observed": ["idle"],
            "slice_b_compatibility_extras": ["body_id", "session_id"],
            "canonical_frame_validation": True,
        }
        write_json(preflight_path, preflight)

        unity_path = self.evidence / "unity-live-receipt.json"
        unity_live = {
            "schema": "bodyrig.unity_live_stream/v0.1",
            "created_at": NOW,
            "production_activation": False,
            "candidate_git_sha": SHA,
            "body_id": BODY,
            "package_sha256": PACKAGE,
            "source_url": RIG,
            "bearer_auth_used": True,
            "renderer_bound": True,
            "frame_applied": True,
            "first_frame_timestamp_ms": 1250,
            "first_frame_state": "idle",
        }
        write_json(unity_path, unity_live)

        run_path = self.evidence / "live-run-receipt.json"
        run = {
            "schema": "bodyrig.unity_live_run/v0.1",
            "created_at": NOW,
            "production_activation": False,
            "visual_acceptance": False,
            "pr_number": 846,
            "candidate_git_sha": SHA,
            "rig_url": RIG,
            "profile": {"body_id": BODY, "package_sha256": PACKAGE},
            "receipts": {
                "preflight": {"path": str(preflight_path), "sha256": sha(preflight_path)},
                "renderer_build": {"path": str(build_path), "sha256": sha(build_path)},
                "renderer_runtime": {"path": str(runtime_path), "sha256": sha(runtime_path)},
                "unity_live": {"path": str(unity_path), "sha256": sha(unity_path)},
            },
        }
        write_json(run_path, run)

        visual_path = self.evidence / "live-visual-receipt.json"
        visual = {
            "schema": "bodyrig.unity_live_visual_acceptance/v0.1",
            "accepted_at": LATER,
            "production_activation": False,
            "visual_acceptance": True,
            "pr_number": 846,
            "candidate_git_sha": SHA,
            "rig_url": RIG,
            "profile": {"body_id": BODY, "package_sha256": PACKAGE},
            "evidence_sha256": {
                "live_run": sha(run_path),
                "preflight": sha(preflight_path),
                "unity_live": sha(unity_path),
                "renderer_build": sha(build_path),
                "renderer_runtime": sha(runtime_path),
            },
            "checks": {
                "idle_listening_thinking_speaking_interrupted_are_visibly_distinct": True,
                "gaze_blink_breath_are_visible": True,
                "mouth_motion_tracks_live_speech_playback": True,
                "interruption_immediately_neutralizes_mouth_and_gesture": True,
            },
            "operator": {
                "user": "anders",
                "machine": "rig",
                "attestation": "direct observation",
            },
        }
        write_json(visual_path, visual)

    def validate(self, expected_sha: str = SHA) -> dict:
        return validate_evidence(
            evidence_dir=self.evidence,
            expected_sha=expected_sha,
            repo_root=ROOT,
            require_git_state=False,
        )

    def test_complete_chain_passes(self) -> None:
        result = self.validate()
        self.assertEqual(result["candidate_git_sha"], SHA)
        self.assertEqual(result["pr_number"], 846)
        self.assertTrue(result["machine_live_proof"])
        self.assertTrue(result["visual_acceptance"])
        self.assertFalse(result["production_activation"])

    def test_expected_sha_is_exact_authority(self) -> None:
        with self.assertRaisesRegex(LivePhysicalGateError, "candidate SHA mismatch"):
            self.validate("f" * 40)

    def test_tampered_preflight_is_rejected_by_digest_binding(self) -> None:
        path = self.evidence / "live-preflight-receipt.json"
        value = json.loads(path.read_text(encoding="utf-8"))
        value["frame_count"] = 99
        write_json(path, value)
        with self.assertRaisesRegex(LivePhysicalGateError, "SHA-256 binding mismatch"):
            self.validate()

    def test_unattested_live_frame_is_rejected(self) -> None:
        path = self.evidence / "unity-live-receipt.json"
        value = json.loads(path.read_text(encoding="utf-8"))
        value["frame_applied"] = False
        write_json(path, value)
        # Rebind machine receipt and visual hashes so the semantic gate, not
        # tamper detection, is what rejects this fixture.
        run_path = self.evidence / "live-run-receipt.json"
        run = json.loads(run_path.read_text(encoding="utf-8"))
        run["receipts"]["unity_live"]["sha256"] = sha(path)
        write_json(run_path, run)
        visual_path = self.evidence / "live-visual-receipt.json"
        visual = json.loads(visual_path.read_text(encoding="utf-8"))
        visual["evidence_sha256"]["unity_live"] = sha(path)
        visual["evidence_sha256"]["live_run"] = sha(run_path)
        write_json(visual_path, visual)
        with self.assertRaisesRegex(LivePhysicalGateError, "applied frame"):
            self.validate()

    def test_partial_visual_acceptance_is_rejected(self) -> None:
        path = self.evidence / "live-visual-receipt.json"
        visual = json.loads(path.read_text(encoding="utf-8"))
        visual["checks"]["mouth_motion_tracks_live_speech_playback"] = False
        write_json(path, visual)
        with self.assertRaisesRegex(LivePhysicalGateError, "visual checks"):
            self.validate()

    def test_any_production_activation_is_rejected(self) -> None:
        path = self.evidence / "unity-live-receipt.json"
        value = json.loads(path.read_text(encoding="utf-8"))
        value["production_activation"] = True
        write_json(path, value)
        run_path = self.evidence / "live-run-receipt.json"
        run = json.loads(run_path.read_text(encoding="utf-8"))
        run["receipts"]["unity_live"]["sha256"] = sha(path)
        write_json(run_path, run)
        visual_path = self.evidence / "live-visual-receipt.json"
        visual = json.loads(visual_path.read_text(encoding="utf-8"))
        visual["evidence_sha256"]["unity_live"] = sha(path)
        visual["evidence_sha256"]["live_run"] = sha(run_path)
        write_json(visual_path, visual)
        with self.assertRaisesRegex(LivePhysicalGateError, "activated production"):
            self.validate()


if __name__ == "__main__":
    unittest.main(verbosity=2)
