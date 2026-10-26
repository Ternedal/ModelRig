"""Contract tests for the read-only Kaliv V1 physical preflight."""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "kaliv_v1_physical_preflight.py"
REPOS = ("ModelRig", "BodyRig", "VisionRig", "VoiceRig")


def git(path: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(path), *args], check=True, capture_output=True, text=True)


class PhysicalPreflightTests(unittest.TestCase):
    def test_missing_repositories_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            output = base / "report.json"
            run = subprocess.run([sys.executable, str(SCRIPT), "--workspace", str(base),
                                  "--output", str(output)], capture_output=True, text=True)
            self.assertEqual(run.returncode, 2)
            report = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(report["status"], "BLOCKED")
            self.assertFalse(report["release_ready"])
            self.assertFalse(report["production_activation"])
            self.assertEqual(len(report["gates"]), 10)
            self.assertTrue(all(v == "PENDING" for v in report["gates"].values()))

    def test_clean_pinned_repositories_still_do_not_pass_release(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            for name in REPOS:
                path = base / name
                path.mkdir()
                git(path, "init", "-q")
                git(path, "-c", "user.name=Test", "-c", "user.email=test@example.invalid",
                    "commit", "-q", "--allow-empty", "-m", "initial")
            output = base / "report.json"
            run = subprocess.run([sys.executable, str(SCRIPT), "--workspace", str(base),
                                  "--output", str(output)], capture_output=True, text=True)
            self.assertEqual(run.returncode, 0, run.stderr)
            report = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(report["status"], "READY_FOR_PHYSICAL_QUALIFICATION")
            self.assertTrue(all(len(r["sha"]) == 40 and r["clean"]
                                for r in report["repositories"].values()))
            self.assertFalse(report["release_ready"])
            self.assertTrue(all(v == "PENDING" for v in report["gates"].values()))
            repeat = subprocess.run([sys.executable, str(SCRIPT), "--workspace", str(base),
                                     "--output", str(output)], capture_output=True, text=True)
            self.assertEqual(repeat.returncode, 2)
            self.assertEqual(json.loads(output.read_text(encoding="utf-8")), report)

    def test_dirty_checkout_blocks(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            for name in REPOS:
                path = base / name
                path.mkdir()
                git(path, "init", "-q")
                git(path, "-c", "user.name=Test", "-c", "user.email=test@example.invalid",
                    "commit", "-q", "--allow-empty", "-m", "initial")
            (base / "VoiceRig" / "untracked.txt").write_text("not clean", encoding="utf-8")
            output = base / "report.json"
            run = subprocess.run([sys.executable, str(SCRIPT), "--workspace", str(base),
                                  "--output", str(output)], capture_output=True, text=True)
            self.assertEqual(run.returncode, 2)
            report = json.loads(output.read_text(encoding="utf-8"))
            self.assertFalse(report["repositories"]["VoiceRig"]["clean"])


if __name__ == "__main__":
    unittest.main()
