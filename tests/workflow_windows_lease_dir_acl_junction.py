"""The Windows lease-directory contract must FAIL when it cannot create its junction.

ChatGPT on #2275 (6699231451): the contract's junction case printed "case skipped" and
the run still passed when `mklink /J` failed, so a runner that cannot make junctions
would silently prove nothing about them. The case is now a failing assertion with a
bounded, one-line diagnostic. This test runs everywhere (the contract itself only runs
on Windows) and drives the junction step with a fake `mklink` and a fake ACL verdict.

Run: PYTHONPATH=worker python3 tests/workflow_windows_lease_dir_acl_junction.py
"""
import subprocess
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests" / "support"))

import windows_lease_dir_acl_contract as contract  # noqa: E402


class JunctionCaseTests(unittest.TestCase):
    def setUp(self):
        contract.passed = contract.failed = 0

    def run_case(self, made, verdict=(False, "a junction")):
        calls = []

        def fake_run(args, **kwargs):
            calls.append(args)
            return made
        with patch.object(contract.subprocess, "run", side_effect=fake_run), \
                patch.object(contract, "lease_dir_private", return_value=verdict) as judged:
            contract.junction_case(Path("C:/t/junction"), Path("C:/t/target"))
        return calls, judged

    def test_a_junction_that_cannot_be_created_fails_the_contract(self):
        made = SimpleNamespace(returncode=1, stdout="You do not have sufficient privilege\r\nto perform this.",
                               stderr="x" * 5000)
        calls, judged = self.run_case(made)
        self.assertEqual((contract.passed, contract.failed), (0, 1), "a failure, never a skip")
        self.assertEqual(calls[0][:4], ["cmd", "/c", "mklink", "/J"])
        judged.assert_not_called()

    def test_the_diagnostic_is_one_bounded_line(self):
        made = SimpleNamespace(returncode=5, stdout="line one\r\nline two\n", stderr="e" * 5000)
        with patch("builtins.print") as printed:
            self.run_case(made)
        lines = [str(c.args[0]) for c in printed.call_args_list]
        failing = [line for line in lines if "FAIL" in line]
        self.assertEqual(len(failing), 1)
        self.assertNotIn("\n", failing[0])
        self.assertNotIn("\r", failing[0])
        self.assertLessEqual(len(failing[0]), 400)
        self.assertIn("rc=5", failing[0])

    def test_a_created_junction_must_be_refused(self):
        ok = SimpleNamespace(returncode=0, stdout="Junction created", stderr="")
        self.run_case(ok, verdict=(False, "opened object is a symlink or junction"))
        self.assertEqual((contract.passed, contract.failed), (1, 0))
        contract.passed = contract.failed = 0
        self.run_case(ok, verdict=(True, "only the process user can use it"))
        self.assertEqual((contract.passed, contract.failed), (0, 1), "a followed junction fails")

    def test_a_hung_mklink_fails_the_contract(self):
        with patch.object(contract.subprocess, "run", side_effect=subprocess.TimeoutExpired("mklink", 30)), \
                patch.object(contract, "lease_dir_private") as judged:
            contract.junction_case(Path("C:/t/junction"), Path("C:/t/target"))
        self.assertEqual((contract.passed, contract.failed), (0, 1))
        judged.assert_not_called()

    def test_main_no_longer_has_a_skip_path_for_the_junction(self):
        source = (ROOT / "tests" / "support" / "windows_lease_dir_acl_contract.py").read_text(encoding="utf-8")
        self.assertNotIn("case skipped", source)
        self.assertIn("junction_case(", source.split("def main", 1)[1])


if __name__ == "__main__":
    unittest.main()
