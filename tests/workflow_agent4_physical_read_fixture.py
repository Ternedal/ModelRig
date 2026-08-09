#!/usr/bin/env python3
"""A4-18 canonical physical-read fixture contracts."""

from __future__ import annotations

import ast
import json
import shutil
import subprocess
import sys
import unittest
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "agent4-physical-fixture.py"
RUNTIME = ROOT / "validation" / "agent4-physical-runtime"


class Agent4PhysicalReadFixtureTests(unittest.TestCase):
    def test_script_builds_paged_canonical_fixture_without_activation(self) -> None:
        run_root = RUNTIME / f"ci-{uuid.uuid4().hex}"
        data_root = run_root / "data"
        manifest_path = run_root / "fixture.json"
        try:
            completed = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--data-root",
                    str(data_root),
                    "--manifest",
                    str(manifest_path),
                ],
                cwd=ROOT,
                check=False,
                capture_output=True,
                text=True,
                timeout=60,
            )
            self.assertEqual(
                completed.returncode,
                0,
                msg=f"stdout:\n{completed.stdout}\nstderr:\n{completed.stderr}",
            )
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(
                manifest["schema"],
                "modelrig-agent4/physical-read-fixture/v1",
            )
            self.assertEqual(manifest["selected_campaign_id"], "a4-18-physical-primary")
            self.assertGreater(manifest["campaign_count"], 25)
            self.assertGreater(manifest["timeline_count"], 25)
            self.assertGreater(manifest["evidence_count"], 25)
            self.assertEqual(
                manifest["evidence_verification_count"],
                manifest["evidence_count"],
            )
            self.assertTrue(manifest["latest_timeline_hash"].startswith("sha256:"))
            self.assertTrue(manifest["evidence_head_hash"].startswith("sha256:"))
            self.assertFalse(manifest["external_dispatch"])
            self.assertFalse(manifest["background_runtime"])
            self.assertFalse(manifest["production_activation"])
            self.assertTrue(data_root.is_dir())
            self.assertGreater(len(manifest["persisted_files"]), manifest["evidence_count"])
            for item in manifest["persisted_files"]:
                self.assertFalse(Path(item["path"]).is_absolute())
                self.assertTrue(item["sha256"].startswith("sha256:"))
                self.assertGreaterEqual(item["size_bytes"], 0)
        finally:
            shutil.rmtree(run_root, ignore_errors=True)

    def test_fixture_is_confined_and_contains_no_runtime_activation(self) -> None:
        source = SCRIPT.read_text(encoding="utf-8")
        tree = ast.parse(source)
        called_attributes = {
            node.func.attr
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        }
        self.assertNotIn("start", called_attributes)
        self.assertNotIn("recover", called_attributes)
        self.assertNotIn("reconcile_projections", called_attributes)
        for forbidden in (
            "KALIV_AGENT3_ENABLED",
            "mount_agent4_operator",
            "uvicorn",
            "threading.Thread",
            "asyncio.create_task",
            "subprocess",
            "requests.",
            "httpx.",
        ):
            self.assertNotIn(forbidden, source)
        self.assertIn("validation/agent4-physical-runtime", source)
        self.assertIn('"production_activation": False', source)
        self.assertIn('"external_dispatch": False', source)

    def test_fixture_refuses_paths_outside_validation_runtime(self) -> None:
        completed = subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "--data-root",
                str(ROOT / "outside-agent4-fixture"),
                "--manifest",
                str(ROOT / "outside-agent4-fixture.json"),
            ],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("validation/agent4-physical-runtime", completed.stderr)
        self.assertFalse((ROOT / "outside-agent4-fixture").exists())
        self.assertFalse((ROOT / "outside-agent4-fixture.json").exists())


if __name__ == "__main__":
    unittest.main()
