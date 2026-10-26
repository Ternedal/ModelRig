"""Hardware smoke receipt tests without needing a GPU."""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "kaliv_v1_hardware_smoke.py"
spec = importlib.util.spec_from_file_location("kaliv_v1_hardware_smoke", SCRIPT)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class HardwareSmokeTests(unittest.TestCase):
    def test_no_nvidia_smi_is_not_pass(self):
        with patch.object(module.shutil, "which", return_value=None):
            self.assertEqual(module.gpu_inventory()["status"], "UNAVAILABLE")

    def test_two_gpus_are_inventory_only(self):
        fake = subprocess.CompletedProcess(
            args=[], returncode=0,
            stdout="0, NVIDIA RTX 3060, 12288, 617.14\n1, NVIDIA RTX 3060, 12288, 617.14\n",
            stderr="",
        )
        with patch.object(module.shutil, "which", return_value="nvidia-smi"):
            with patch.object(module.subprocess, "run", return_value=fake):
                inventory = module.gpu_inventory()
        self.assertEqual(inventory["status"], "OBSERVED")
        self.assertEqual(len(inventory["gpus"]), 2)
        self.assertEqual(inventory["gpus"][0]["memory_mib"], 12288)

    def test_malformed_output_fails_closed(self):
        fake = subprocess.CompletedProcess(args=[], returncode=0, stdout="nonsense\n", stderr="")
        with patch.object(module.shutil, "which", return_value="nvidia-smi"):
            with patch.object(module.subprocess, "run", return_value=fake):
                self.assertEqual(module.gpu_inventory()["status"], "ERROR")

    def test_missing_gpu_report_does_not_claim_release(self):
        with tempfile.TemporaryDirectory() as td:
            output = Path(td) / "hardware.json"
            with patch.object(module.shutil, "which", return_value=None):
                with patch.object(sys, "argv", [str(SCRIPT), "--output", str(output)]):
                    self.assertEqual(module.main(), 2)
            report = json.loads(output.read_text(encoding="utf-8"))
            self.assertFalse(report["release_ready"])
            self.assertFalse(report["production_activation"])
            self.assertEqual(report["physical_qualification"], "PENDING")
            with patch.object(sys, "argv", [str(SCRIPT), "--output", str(output)]):
                self.assertEqual(module.main(), 2)


if __name__ == "__main__":
    unittest.main()
